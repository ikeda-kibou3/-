"""Playwright による e-Tax 受付システムの操作.

RPA の「画面上の絵を探してクリック」ではなく、画面の文字（ラベル）で
部品を探します。候補は config/selectors.yaml に外出ししてあるので、
e-Tax の画面が変わってもコードを触らずに直せます。

想定する流れ（手順書のとおり）
  ログイン → 法人を選択 → 利用者識別番号・暗証番号 → はい
  → 送信結果・お知らせ → お知らせ・受信通知
  → 対象のお知らせを開く → お知らせの内容を確認する → PDF保存
  → 戻る → もう一方の税目 → ログアウト
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .logs import get_logger

log = get_logger(__name__)


class StepNotFound(RuntimeError):
    """画面上に想定した部品が見つからなかった."""


@dataclass
class EtaxOptions:
    login_url: str
    timeout_sec: int = 60
    headful: bool = True
    manual_assist: bool = True
    max_retry: int = 2
    capture_dir: Path | None = None
    selectors: dict[str, list[dict[str, str]]] = field(default_factory=dict)


# ---------------------------------------------------------------------
#  部品の探索
# ---------------------------------------------------------------------
def _candidates(selectors: dict, key: str) -> list[dict[str, str]]:
    cands = selectors.get(key)
    if not cands:
        raise KeyError(
            f"selectors.yaml に '{key}' の定義がありません。config/selectors.yaml を確認してください。"
        )
    return cands


def find(page, selectors: dict, key: str, timeout_ms: int = 5000):
    """候補を上から順に試し、最初に見つかった Locator を返す（無ければ None）."""
    per = max(800, timeout_ms // max(1, len(_candidates(selectors, key))))
    for cand in _candidates(selectors, key):
        loc = _build(page, cand)
        if loc is None:
            continue
        try:
            loc.first.wait_for(state="visible", timeout=per)
            log.debug("見つかりました key=%s cand=%s", key, cand)
            return loc.first
        except Exception:  # noqa: BLE001  Playwright TimeoutError 等
            continue
    return None


def _build(page, cand: dict[str, str]):
    if "css" in cand:
        return page.locator(cand["css"])
    if "label" in cand:
        return page.get_by_label(cand["label"], exact=False)
    if "text" in cand:
        # リンク・ボタン・input を順に見る
        text = cand["text"]
        return page.locator(
            f"a:has-text('{text}'), button:has-text('{text}'), "
            f"input[value*='{text}'], [role='button']:has-text('{text}')"
        )
    return None


# ---------------------------------------------------------------------
#  セッション
# ---------------------------------------------------------------------
class EtaxSession:
    def __init__(self, opts: EtaxOptions) -> None:
        self.opts = opts
        self._pw = None
        self.browser = None
        self.context = None
        self.page = None

    def __enter__(self) -> "EtaxSession":
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=not self.opts.headful)
        self.context = self.browser.new_context(accept_downloads=True)
        self.context.set_default_timeout(self.opts.timeout_sec * 1000)
        self.page = self.context.new_page()
        # e-Tax が出す確認ダイアログ（JSのalert/confirm）は承認して先へ進む。
        # Playwright の既定は「打ち消す」なので、明示的に受ける。
        self.page.on("dialog", lambda d: d.accept())
        return self

    def __exit__(self, *exc) -> None:
        for closer in (self.context, self.browser):
            try:
                if closer:
                    closer.close()
            except Exception:  # noqa: BLE001
                pass
        if self._pw:
            self._pw.stop()

    # --- 共通操作 ---------------------------------------------------
    def step_click(self, key: str, required: bool = True, hint: str = "") -> bool:
        """selectors.yaml の key に対応する部品をクリックする."""
        loc = find(self.page, self.opts.selectors, key)
        if loc is not None:
            loc.click()
            self._settle()
            return True
        if not required:
            log.info("（任意）%s は画面に見当たらないので飛ばします", key)
            return False
        return self._assist(key, hint or f"「{key}」に当たるボタン／リンクをクリックしてください")

    def step_fill(self, key: str, value: str, hint: str = "") -> bool:
        loc = find(self.page, self.opts.selectors, key)
        if loc is not None:
            loc.fill(value)
            return True
        return self._assist(key, hint or f"「{key}」の入力欄に値を入れてください")

    def _settle(self) -> None:
        """画面の読み込みが落ち着くのを待つ（待ちきれなくても処理は続ける）."""
        try:
            self.page.wait_for_load_state("networkidle", timeout=self.opts.timeout_sec * 1000)
        except Exception:  # noqa: BLE001
            log.debug("networkidle まで待てませんでしたが、処理を続けます")

    def _assist(self, key: str, hint: str) -> bool:
        """自動で見つからなかったときの手動アシスト."""
        self.capture(f"miss_{key}")
        if not (self.opts.manual_assist and self.opts.headful):
            raise StepNotFound(
                f"画面上に '{key}' が見つかりませんでした。"
                f" config/selectors.yaml の '{key}' を直してください。"
            )
        print("\n" + "=" * 62)
        print(f"【手動アシスト】'{key}' を自動で見つけられませんでした。")
        print(f"  ブラウザ画面で {hint}")
        print("  操作が終わったら、この画面で Enter を押してください。")
        print("  （中止する場合は Ctrl+C）")
        print("=" * 62)
        input()
        return True

    def capture(self, tag: str) -> None:
        """今の画面をスクリーンショットとHTMLで保存（セレクタ修正用）."""
        if not self.opts.capture_dir:
            return
        d = Path(self.opts.capture_dir)
        d.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%H%M%S")
        try:
            self.page.screenshot(path=str(d / f"{stamp}_{tag}.png"), full_page=True)
            (d / f"{stamp}_{tag}.html").write_text(self.page.content(), encoding="utf-8")
            log.info("画面を保存しました: %s", d / f"{stamp}_{tag}.png")
        except Exception as exc:  # noqa: BLE001
            log.warning("画面の保存に失敗: %s", exc)

    # --- 業務の流れ -------------------------------------------------
    def login(self, user_id: str, password: str) -> None:
        log.info("ログイン: 利用者識別番号 %s****", user_id[:6])
        self.page.goto(self.opts.login_url)
        self.step_click("login_entry", hint="「ログイン」を押してください")
        self.step_click("select_corporation", required=False, hint="「法人」を選んでください")
        self.step_fill("user_id_input", user_id)
        self.step_fill("password_input", password)
        self.step_click("login_submit", hint="「ログイン」を押してください")
        # 「はい」などの確認は出ないこともある
        self.step_click("after_login_confirm", required=False)
        if self._looks_like_login_error():
            raise RuntimeError(
                "ログインに失敗しました。利用者識別番号／暗証番号をご確認ください。"
            )

    def _looks_like_login_error(self) -> bool:
        try:
            body = self.page.inner_text("body")
        except Exception:  # noqa: BLE001
            return False
        return bool(re.search(r"(暗証番号.*誤|一致しません|ログインできません|ロック)", body))

    def open_notice_list(self) -> None:
        self.step_click("message_box", hint="「送信結果・お知らせ」を押してください")
        self.step_click("notice_folder", required=False, hint="「お知らせ・受信通知」を押してください")

    def list_notice_titles(self) -> list[str]:
        """一覧に出ているお知らせのタイトルを拾う（ログ・調査用）."""
        try:
            texts = self.page.locator("a").all_inner_texts()
        except Exception:  # noqa: BLE001
            return []
        return [t.strip() for t in texts if t.strip()]

    def open_notice(self, pattern: str) -> bool:
        """タイトルが pattern（正規表現）に一致するお知らせを開く."""
        rx = re.compile(pattern)
        links = self.page.locator("a")
        count = links.count()
        for i in range(count):
            link = links.nth(i)
            try:
                text = (link.inner_text() or "").strip()
            except Exception:  # noqa: BLE001
                continue
            if text and rx.search(text):
                log.info("お知らせを開きます: %s", text)
                link.click()
                self._settle()
                self.step_click("open_notice_body", required=False)
                return True
        log.warning("一覧に該当のお知らせがありません: %s", pattern)
        return False

    def save_current_as_pdf(self, dest: Path) -> Path:
        """表示中のお知らせを PDF として保存する.

        1) ダウンロードボタンがあればそれを使う
        2) 無ければブラウザの印刷機能（CDP printToPDF）でPDF化する
        """
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)

        loc = find(self.page, self.opts.selectors, "download_pdf", timeout_ms=4000)
        if loc is not None:
            try:
                with self.page.expect_download(timeout=self.opts.timeout_sec * 1000) as dl:
                    loc.click()
                dl.value.save_as(str(dest))
                log.info("ダウンロードで保存: %s", dest.name)
                return dest
            except Exception as exc:  # noqa: BLE001
                log.info("ダウンロードボタンでは保存できませんでした（%s）。印刷で保存します。", exc)

        self._print_to_pdf(dest)
        return dest

    def _print_to_pdf(self, dest: Path) -> None:
        """Chromium の印刷機能で、表示中のページをA4縦のPDFにする."""
        params = {
            "printBackground": True,
            "paperWidth": 8.27,   # A4
            "paperHeight": 11.69,
            "marginTop": 0.4,
            "marginBottom": 0.4,
            "marginLeft": 0.4,
            "marginRight": 0.4,
        }
        cdp = self.context.new_cdp_session(self.page)
        try:
            result = cdp.send("Page.printToPDF", params)
        finally:
            cdp.detach()
        import base64

        dest.write_bytes(base64.b64decode(result["data"]))
        log.info("印刷で保存: %s", dest.name)

    def back(self) -> None:
        if not self.step_click("back_button", required=False):
            self.page.go_back()
            self._settle()

    def logout(self) -> None:
        self.step_click("logout", required=False)


def iter_with_interval(items: Iterable[Any], seconds: int):
    """社と社の間に必ず間隔を空けるためのジェネレータ."""
    first = True
    for item in items:
        if not first and seconds > 0:
            time.sleep(seconds)
        first = False
        yield item
