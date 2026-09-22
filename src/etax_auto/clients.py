"""関与先マスタの読み込みと「今月どこが対象か」の判定.

決算期の考え方
--------------
手順書は「毎月15日頃（決算申告月の前月）」に実施となっています。

    実行月 M  →  対象の申告月 = M + 1  →  対象の決算月 = 申告月 - 2

    例) 4月に実行 → 申告月は5月 → 3月決算の関与先が対象

申告期限の延長特例（法人税1か月、消費税1か月）を受けている関与先は
申告月が1か月後ろにずれるので、マスタの「法人税延長」「消費税延長」で
個別に調整します。
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# 利用者識別番号は数字16桁
USER_ID_RX = re.compile(r"\d{16}")


def normalize_user_id(value: str) -> str:
    """全角数字・ハイフン・空白をならして、数字だけにする.

    Excel に貼り付けると全角数字が混ざることがあるので、ここで吸収します。
    """
    text = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"[^0-9]", "", text)


# CSV の列名 → 内部名
COLUMNS = {
    "関与先コード": "code",
    "法人名": "name",
    "事務所": "office",
    "利用者識別番号": "user_id",
    "決算月": "fiscal_month",
    "法人税延長": "corp_extension",
    "消費税延長": "consumption_extension",
    "消費税課税": "consumption_taxable",
    "担当者": "staff",
    "有効": "active",
    "備考": "note",
}


@dataclass
class Client:
    code: str
    name: str
    office: str
    user_id: str
    fiscal_month: int
    corp_extension: int = 0
    consumption_extension: int = 0
    consumption_taxable: int = 1
    staff: str = ""
    active: int = 1
    note: str = ""

    def __post_init__(self) -> None:
        self.fiscal_month = int(self.fiscal_month)
        self.corp_extension = _int(self.corp_extension)
        self.consumption_extension = _int(self.consumption_extension)
        self.consumption_taxable = _int(self.consumption_taxable, default=1)
        self.active = _int(self.active, default=1)
        self.user_id = normalize_user_id(self.user_id)
        if not 1 <= self.fiscal_month <= 12:
            raise ValueError(f"{self.name}: 決算月は1〜12で指定してください（{self.fiscal_month}）")
        if not USER_ID_RX.fullmatch(self.user_id):
            raise ValueError(
                f"{self.name}: 利用者識別番号は数字16桁です（入力値「{self.user_id}」は{len(self.user_id)}桁）。"
                "紙のファイルと照合してください。"
            )

    @property
    def folder_name(self) -> str:
        """出力フォルダ名。Windowsで使えない文字を除きます."""
        safe = "".join(ch for ch in self.name if ch not in r'\/:*?"<>|')
        return f"{self.code}_{safe}"

    def corp_filing_month(self, months_after: int = 2) -> int:
        return shift_month(self.fiscal_month, months_after + self.corp_extension)

    def consumption_filing_month(self, months_after: int = 2) -> int:
        return shift_month(self.fiscal_month, months_after + self.consumption_extension)


def _int(value, default: int = 0) -> int:
    s = str(value).strip()
    if s in ("", "-"):
        return default
    if s in ("1", "○", "有", "あり", "true", "TRUE", "yes"):
        return 1
    if s in ("0", "×", "無", "なし", "false", "FALSE", "no"):
        return 0
    return int(s)


def shift_month(month: int, delta: int) -> int:
    """月を delta か月ずらす（1〜12で返す）."""
    return ((month - 1 + delta) % 12) + 1


def add_months(d: date, delta: int) -> date:
    """日付を delta か月ずらす（日は月初に丸める）."""
    total = (d.year * 12 + (d.month - 1)) + delta
    return date(total // 12, total % 12 + 1, 1)


def month_end(year: int, month: int) -> date:
    """その月の末日を返す."""
    nxt = add_months(date(year, month, 1), 1)
    return date.fromordinal(nxt.toordinal() - 1)


def target_filing_month(run_date: date, months_ahead: int = 1) -> date:
    """実行日から見た「対象の申告月」の月初日を返す."""
    return add_months(date(run_date.year, run_date.month, 1), months_ahead)


def fiscal_period(filing_month_start: date, months_after: int, extension: int) -> tuple[date, date]:
    """申告月から逆算した決算期間（期首, 期末）を返す."""
    close_start = add_months(filing_month_start, -(months_after + extension))
    period_end = month_end(close_start.year, close_start.month)
    period_start = add_months(close_start, -11)
    return period_start, period_end


def load_clients(path: Path) -> list[Client]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"関与先マスタが見つかりません: {path}\n"
            "data/clients.sample.csv をコピーして data/clients.csv を作ってください。"
        )
    clients: list[Client] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [jp for jp in COLUMNS if jp not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"関与先マスタに列が足りません: {', '.join(missing)}")
        for lineno, row in enumerate(reader, start=2):
            if not (row.get("法人名") or "").strip():
                continue
            kwargs = {internal: (row.get(jp) or "") for jp, internal in COLUMNS.items()}
            try:
                clients.append(Client(**kwargs))
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"関与先マスタ {lineno}行目: {exc}") from exc
    _check_duplicates(clients)
    return clients


def _check_duplicates(clients: list[Client]) -> None:
    """関与先コードと利用者識別番号の重複を見つける.

    紙から書き写すときやコピー＆ペーストのときに起きやすい取り違えを、
    実行前にここで止めます。
    """
    for label, key in (("関与先コード", "code"), ("利用者識別番号", "user_id")):
        seen: dict[str, str] = {}
        for c in clients:
            value = getattr(c, key)
            if value in seen:
                raise ValueError(
                    f"{label}「{value}」が重複しています（{seen[value]} と {c.name}）。"
                    "どちらかが書き間違いの可能性があります。"
                )
            seen[value] = c.name


@dataclass
class Target:
    """今月処理する1社分の情報."""

    client: Client
    filing_month: date          # 申告月（月初）
    need_corp: bool             # 法人税の通知を取るか
    need_consumption: bool      # 消費税の通知を取るか
    period_start: date          # 決算期首
    period_end: date            # 決算期末

    @property
    def period_label(self) -> str:
        return (
            f"{self.period_start.year}年{self.period_start.month}月{self.period_start.day}日"
            f"〜{self.period_end.year}年{self.period_end.month}月{self.period_end.day}日"
        )


def select_targets(
    clients: list[Client],
    run_date: date,
    months_ahead: int = 1,
    corp_months_after: int = 2,
    consumption_months_after: int = 2,
) -> list[Target]:
    """実行日から見て、今回処理すべき関与先を選び出す."""
    filing = target_filing_month(run_date, months_ahead)
    targets: list[Target] = []
    for c in clients:
        if not c.active:
            continue
        need_corp = c.corp_filing_month(corp_months_after) == filing.month
        need_cons = (
            bool(c.consumption_taxable)
            and c.consumption_filing_month(consumption_months_after) == filing.month
        )
        if not (need_corp or need_cons):
            continue
        # 決算期間は法人税基準で出す（延長の有無を考慮）
        ext = c.corp_extension if need_corp else c.consumption_extension
        months = corp_months_after if need_corp else consumption_months_after
        start, end = fiscal_period(filing, months, ext)
        targets.append(
            Target(
                client=c,
                filing_month=filing,
                need_corp=need_corp,
                need_consumption=need_cons,
                period_start=start,
                period_end=end,
            )
        )
    targets.sort(key=lambda t: (t.client.office, t.client.code))
    return targets
