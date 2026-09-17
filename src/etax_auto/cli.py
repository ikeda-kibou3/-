"""コマンド入口.

    etax-auto plan                 今月の対象関与先を一覧表示（ブラウザは開かない）
    etax-auto run                  本番実行（e-Taxから取得してPDFを作る）
    etax-auto run --dry-run        e-Taxにはつながず、チェックリストだけ作る
    etax-auto cred set 1234...     暗証番号を登録
    etax-auto cred list            登録済みの利用者識別番号を確認
    etax-auto capture              今の画面を保存（セレクタ調査用）
    etax-auto calibrate <PDF>      チェックリストの座標確認用PDFを作る
    etax-auto check                設定と環境の健康診断
"""

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

from . import __version__
from .checklist import FillValues, build_checklists, calibrate, load_checklist_config
from .clients import Client, Target, load_clients, select_targets
from .config import DEFAULT_CHECKLISTS, ROOT, load_selectors, load_settings
from .crypto import CredentialStore, get_master
from .logs import get_logger, setup_logging
from .report import Report, Row

log = get_logger(__name__)

CLIENTS_CSV = ROOT / "data" / "clients.csv"
CRED_FILE = ROOT / "data" / "credentials.enc"


# ---------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="etax-auto",
        description="e-Taxの決算通知書を自動で取得し、チェックリストと束ねます。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--version", action="version", version=f"etax-auto {__version__}")
    p.add_argument("--settings", type=Path, default=None, help="設定ファイル（既定 config/settings.toml）")
    p.add_argument("--clients", type=Path, default=None, help="関与先マスタCSV（既定 data/clients.csv）")
    p.add_argument("-v", "--verbose", action="store_true", help="詳しいログを出す")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("plan", help="今月の対象関与先を一覧表示する")
    sp.add_argument("--date", help="実行日を仮に指定（例 2026-04-15）")

    sr = sub.add_parser("run", help="本番実行")
    sr.add_argument("--date", help="実行日を仮に指定（例 2026-04-15）")
    sr.add_argument("--only", nargs="*", help="この関与先コードだけ処理する")
    sr.add_argument("--dry-run", action="store_true", help="e-Taxにはつながない（チェックリストのみ作成）")
    sr.add_argument("--headless", action="store_true", help="ブラウザ画面を出さない")

    sc = sub.add_parser("cred", help="暗証番号の登録・確認")
    sc.add_argument("action", choices=["set", "list", "delete", "verify"])
    sc.add_argument("user_id", nargs="?", help="利用者識別番号")

    sub.add_parser("capture", help="e-Taxを開いて画面を保存する（セレクタ調査用）")

    scal = sub.add_parser("calibrate", help="チェックリストの座標確認用PDFを作る")
    scal.add_argument("template", type=Path)
    scal.add_argument("--step", type=int, default=50)

    sub.add_parser("check", help="設定と環境の健康診断")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings(args.settings)
    setup_logging(settings.log_dir, verbose=args.verbose)
    handlers = {
        "plan": cmd_plan,
        "run": cmd_run,
        "cred": cmd_cred,
        "capture": cmd_capture,
        "calibrate": cmd_calibrate,
        "check": cmd_check,
    }
    try:
        return handlers[args.command](args, settings)
    except KeyboardInterrupt:
        print("\n中断しました。")
        return 130
    except Exception as exc:  # noqa: BLE001
        log.error("エラー: %s", exc)
        if args.verbose:
            traceback.print_exc()
        return 1


# ---------------------------------------------------------------------
def _run_date(args) -> date:
    if getattr(args, "date", None):
        return datetime.strptime(args.date, "%Y-%m-%d").date()
    return date.today()


def _load_targets(args, settings) -> tuple[list[Target], date]:
    clients = load_clients(args.clients or CLIENTS_CSV)
    run_date = _run_date(args)
    targets = select_targets(
        clients,
        run_date,
        months_ahead=settings.months_ahead,
        corp_months_after=settings.corp_months_after,
        consumption_months_after=settings.consumption_months_after,
    )
    only = getattr(args, "only", None)
    if only:
        wanted = set(only)
        targets = [t for t in targets if t.client.code in wanted]
    return targets, run_date


def _pad(text: str, width: int) -> str:
    """全角を2文字分として数え、桁をそろえる."""
    import unicodedata

    used = sum(2 if unicodedata.east_asian_width(ch) in "WFA" else 1 for ch in text)
    return text + " " * max(1, width - used)


def _print_plan(targets: list[Target], run_date: date) -> None:
    if not targets:
        print(f"\n{run_date:%Y年%m月%d日} 時点で、対象になる関与先はありません。")
        return
    filing = targets[0].filing_month
    print(f"\n【{filing:%Y年%m月}申告分】対象 {len(targets)} 社（実行日 {run_date:%Y年%m月%d日}）")
    print("-" * 74)
    print(
        _pad("コード", 8) + _pad("事務所", 8) + _pad("法人名", 30)
        + _pad("決算期末", 12) + _pad("法人税", 8) + _pad("消費税", 8) + "担当"
    )
    print("-" * 74)
    for t in targets:
        print(
            _pad(t.client.code, 8)
            + _pad(t.client.office, 8)
            + _pad(t.client.name[:13], 30)
            + _pad(f"{t.period_end:%Y/%m}", 12)
            + _pad("○" if t.need_corp else "－", 8)
            + _pad("○" if t.need_consumption else "－", 8)
            + t.client.staff
        )
    print("-" * 74)


def cmd_plan(args, settings) -> int:
    targets, run_date = _load_targets(args, settings)
    _print_plan(targets, run_date)
    return 0


# ---------------------------------------------------------------------
def cmd_run(args, settings) -> int:
    targets, run_date = _load_targets(args, settings)
    _print_plan(targets, run_date)
    if not targets:
        return 0

    filing = targets[0].filing_month
    out_root = settings.output_dir / f"{filing:%Y-%m}申告分"
    out_root.mkdir(parents=True, exist_ok=True)

    checklist_specs = load_checklist_config(DEFAULT_CHECKLISTS)
    notices = settings.section("notices")
    pages_cfg = settings.section("pages")
    hl = settings.section("highlight")
    bundle = settings.section("bundle")
    etax_cfg = settings.section("etax")

    report = Report()

    store = None
    if not args.dry_run:
        store = CredentialStore(CRED_FILE, get_master()).load()
        missing = [t.client.name for t in targets if t.client.user_id not in store]
        if missing:
            print("\n暗証番号が未登録の関与先があります:")
            for name in missing:
                print(f"  ・{name}")
            print("  `etax-auto cred set <利用者識別番号>` で登録してください。")
            return 2

    session = None
    try:
        if not args.dry_run:
            from .etax import EtaxOptions, EtaxSession

            opts = EtaxOptions(
                login_url=etax_cfg.get("login_url", "https://www.e-tax.nta.go.jp/"),
                timeout_sec=int(etax_cfg.get("timeout_sec", 60)),
                headful=(not args.headless) and bool(etax_cfg.get("headful", True)),
                manual_assist=bool(etax_cfg.get("manual_assist", True)),
                max_retry=int(etax_cfg.get("max_retry", 2)),
                capture_dir=settings.log_dir / "capture",
                selectors=load_selectors(),
            )
            session = EtaxSession(opts).__enter__()

        interval = int(etax_cfg.get("interval_sec", 5))
        import time

        for i, t in enumerate(targets):
            if session and i > 0 and interval > 0:
                time.sleep(interval)
            row = _process_one(
                t, out_root, session, store,
                checklist_specs, notices, pages_cfg, hl, bundle, settings,
            )
            report.add(row)
    finally:
        if session:
            try:
                session.logout()
            except Exception:  # noqa: BLE001
                pass
            session.__exit__(None, None, None)

    report.write_csv(out_root / "_結果一覧.csv")
    print(report.summary())
    print(f"\n出力先: {out_root}")
    return 1 if report.failures else 0


def _process_one(
    t: Target, out_root: Path, session, store,
    checklist_specs, notices, pages_cfg, hl, bundle, settings,
) -> Row:
    from . import pdfwork

    c: Client = t.client
    out_dir = out_root / c.folder_name
    out_dir.mkdir(parents=True, exist_ok=True)
    row = Row(
        関与先コード=c.code, 法人名=c.name, 事務所=c.office, 担当者=c.staff,
        決算期間=t.period_label,
    )
    print(f"\n▼ {c.name}（{c.office} / {c.staff}）")

    # --- チェックリスト ---------------------------------------------
    try:
        values = FillValues(
            法人名=c.name,
            決算期間=t.period_label,
            決算期首=f"{t.period_start:%Y年%m月%d日}",
            決算期末=f"{t.period_end:%Y年%m月%d日}",
            担当者=c.staff,
            関与先コード=c.code,
            申告年月=f"{t.filing_month:%Y年%m月}",
            事務所=settings.office_name,
        )
        made = build_checklists(
            checklist_specs, values, out_dir,
            need_corp=t.need_corp, need_consumption=t.need_consumption,
            project_root=ROOT,
        )
        row.チェックリスト = f"{len(made)}件" if made else "原本なし"
    except Exception as exc:  # noqa: BLE001
        log.error("  チェックリスト作成に失敗: %s", exc)
        row.チェックリスト = "失敗"
        row.メモ = f"チェックリスト: {exc}"
        made = []

    # --- e-Tax から通知書を取得 --------------------------------------
    corp_pdf = out_dir / "a_法人税通知.pdf"
    cons_pdf = out_dir / "b_消費税通知.pdf"
    if session is None:
        row.法人税通知 = row.消費税通知 = "省略(dry-run)"
    else:
        try:
            password = store.get(c.user_id)
            session.login(c.user_id, password)
            session.open_notice_list()

            if t.need_corp:
                row.法人税通知 = _fetch(
                    session, notices["corp_tax_pattern"], corp_pdf,
                    pages_cfg.get("corp_tax_pages", [1]), hl,
                )
            if t.need_consumption:
                row.消費税通知 = _fetch(
                    session, notices["consumption_tax_pattern"], cons_pdf,
                    pages_cfg.get("consumption_tax_pages", [1]), hl,
                )
            session.logout()
        except Exception as exc:  # noqa: BLE001
            log.error("  e-Tax処理に失敗: %s", exc)
            if t.need_corp and row.法人税通知 == "-":
                row.法人税通知 = "失敗"
            if t.need_consumption and row.消費税通知 == "-":
                row.消費税通知 = "失敗"
            row.メモ = (row.メモ + " / " if row.メモ else "") + str(exc)

    # --- ①②③(a)(b) の順に束ねる --------------------------------------
    if bundle.get("enabled", True):
        order = sorted(made) + [p for p in (corp_pdf, cons_pdf) if p.exists()]
        if order:
            dest = out_dir / bundle.get("filename", "_束ね.pdf")
            try:
                pdfwork.merge(order, dest)
                row.束ねPDF = dest.name
            except Exception as exc:  # noqa: BLE001
                log.error("  束ねに失敗: %s", exc)
                row.束ねPDF = "失敗"
    return row


def _fetch(session, pattern: str, dest: Path, pages: list[int], hl: dict) -> str:
    """1つのお知らせを開いてPDF化し、必要ページを抜いてハイライトする."""
    from . import pdfwork

    if not session.open_notice(pattern):
        return "該当なし"
    raw = dest.with_name(dest.stem + "_原本.pdf")
    session.save_current_as_pdf(raw)
    pdfwork.extract_pages(raw, list(pages), dest)
    if hl.get("enabled", True):
        pdfwork.highlight_amounts(dest, list(hl.get("keywords", [])))
    session.back()
    return "取得"


# ---------------------------------------------------------------------
def cmd_cred(args, settings) -> int:
    import getpass

    store = CredentialStore(CRED_FILE, get_master()).load()
    if args.action == "list":
        if not len(store):
            print("まだ1件も登録されていません。")
            return 0
        print(f"登録済み {len(store)} 件:")
        for uid in store.user_ids():
            print(f"  {uid}")
        return 0

    if args.action == "verify":
        clients = load_clients(args.clients or CLIENTS_CSV)
        missing = [c for c in clients if c.active and c.user_id not in store]
        if missing:
            print(f"暗証番号が未登録の関与先 {len(missing)} 件:")
            for c in missing:
                print(f"  {c.code} {c.name}  利用者識別番号 {c.user_id}")
            return 2
        print("有効な関与先すべての暗証番号が登録されています。")
        return 0

    if not args.user_id:
        print("利用者識別番号を指定してください。")
        return 2

    if args.action == "delete":
        removed = store.delete(args.user_id)
        store.save()
        print("削除しました。" if removed else "その利用者識別番号は登録されていません。")
        return 0

    pw1 = getpass.getpass(f"{args.user_id} の暗証番号: ")
    pw2 = getpass.getpass("もう一度: ")
    if pw1 != pw2:
        print("一致しませんでした。")
        return 2
    store.set(args.user_id, pw1)
    store.save()
    print(f"登録しました（現在 {len(store)} 件）。")
    return 0


def cmd_capture(args, settings) -> int:
    from .etax import EtaxOptions, EtaxSession

    etax_cfg = settings.section("etax")
    opts = EtaxOptions(
        login_url=etax_cfg.get("login_url", "https://www.e-tax.nta.go.jp/"),
        timeout_sec=int(etax_cfg.get("timeout_sec", 60)),
        headful=True,
        manual_assist=True,
        capture_dir=settings.log_dir / "capture",
        selectors=load_selectors(),
    )
    print("ブラウザを開きます。手で e-Tax を操作し、記録したい画面まで進んでください。")
    print("画面ごとに、この窓で Enter を押すとスクリーンショットとHTMLを保存します。")
    print("終わるときは何も入力せず「q」＋Enter。")
    with EtaxSession(opts) as s:
        s.page.goto(opts.login_url)
        n = 1
        while True:
            ans = input(f"[{n}] 保存する画面まで進めたら Enter（qで終了）: ")
            if ans.strip().lower() == "q":
                break
            s.capture(f"manual{n:02d}")
            n += 1
    print(f"保存先: {opts.capture_dir}")
    return 0


def cmd_calibrate(args, settings) -> int:
    dest = args.template.with_name(args.template.stem + "_座標確認.pdf")
    calibrate(args.template, dest, step=args.step)
    print(f"作成しました: {dest}")
    print("この方眼を見ながら config/checklists.yaml の x, y を決めてください。")
    return 0


def cmd_check(args, settings) -> int:
    ok = True

    def line(label: str, good: bool, note: str = "") -> None:
        nonlocal ok
        ok = ok and good
        print(f"  [{'OK' if good else '要対応'}] {label}{('  … ' + note) if note else ''}")

    print("\n■ 設定と環境の健康診断")
    line("settings.toml", True, str(settings.path))

    csv_path = args.clients or CLIENTS_CSV
    if csv_path.exists():
        try:
            clients = load_clients(csv_path)
            active = [c for c in clients if c.active]
            line("関与先マスタ", True, f"{len(clients)}件（有効 {len(active)}件）")
        except Exception as exc:  # noqa: BLE001
            line("関与先マスタ", False, str(exc))
    else:
        line("関与先マスタ", False, f"{csv_path} がありません（sample をコピーしてください）")

    line("認証情報ファイル", CRED_FILE.exists(),
         str(CRED_FILE) if CRED_FILE.exists() else "`etax-auto cred set` で作成してください")

    try:
        sel = load_selectors()
        line("selectors.yaml", True, f"{len(sel)}ステップ定義")
    except Exception as exc:  # noqa: BLE001
        line("selectors.yaml", False, str(exc))

    specs = load_checklist_config(DEFAULT_CHECKLISTS)
    for spec in specs:
        tpl = ROOT / spec["template"]
        line(f"チェックリスト原本 {spec['id']}", tpl.exists(),
             str(tpl) if tpl.exists() else f"{tpl} を用意してください")

    for mod, label in [("playwright", "Playwright"), ("pypdf", "pypdf"),
                       ("pdfplumber", "pdfplumber"), ("reportlab", "reportlab"),
                       ("cryptography", "cryptography"), ("yaml", "PyYAML")]:
        try:
            __import__(mod)
            line(label, True)
        except Exception as exc:  # noqa: BLE001
            line(label, False, str(exc))

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            b.close()
        line("Chromium ブラウザ", True)
    except Exception as exc:  # noqa: BLE001
        line("Chromium ブラウザ", False, f"{exc}（`playwright install chromium` を実行）")

    print("\n" + ("すべて準備できています。" if ok else "上の「要対応」を片付けてください。"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
