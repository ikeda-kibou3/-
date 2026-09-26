"""会計・税務ソフトが出したCSVから、関与先マスタを起こす.

「電子申告の達人」などの顧問先マスタをCSVで書き出して読み込ませます。
70〜80社を紙から手入力する作業をなくすのが目的です。

列名はソフトやバージョンで違うので、**よくある言い回しの辞書**で
自動的に突き合わせます。当たらなかった列は画面に出すので、
`config/import_map.yaml` に1行足せば次からは当たります。
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .clients import COLUMNS, normalize_user_id
from .logs import get_logger

log = get_logger(__name__)

# 会計ソフトのCSVは Shift_JIS（CP932）で出ることが多い
ENCODINGS = ["utf-8-sig", "cp932", "utf-8", "euc_jp"]

# 内部名 → よくある列名の候補
ALIASES: dict[str, list[str]] = {
    "code": ["関与先コード", "顧問先コード", "得意先コード", "顧客コード", "取引先コード",
             "関与先No", "顧問先番号", "コード", "整理番号"],
    "name": ["法人名", "顧問先名", "関与先名", "氏名又は名称", "会社名", "顧客名",
             "取引先名", "名称", "氏名"],
    "office": ["事務所", "担当事務所", "所属事務所", "部門", "部門名", "グループ"],
    "user_id": ["利用者識別番号", "eTax利用者識別番号", "e-Tax利用者識別番号",
                "識別番号", "利用者ID", "国税利用者識別番号"],
    "fiscal_month": ["決算月", "決算期", "決算年月", "事業年度終了月", "決算期末月",
                     "決算期末", "事業年度終了日", "期末日", "決算日"],
    "staff": ["担当者", "担当者名", "関与担当者", "担当", "主担当", "業務担当者"],
    "consumption_taxable": ["消費税課税", "課税区分", "消費税区分", "消費税課税区分",
                            "課税事業者"],
}

# 人が判断して入れる項目（ソフトから取れないことが多い）
MANUAL_FIELDS = ["corp_extension", "consumption_extension", "active", "note"]

# 内部名 → CSVの日本語列名
INTERNAL_TO_JP = {internal: jp for jp, internal in COLUMNS.items()}


def _key(text: str) -> str:
    """列名を突き合わせるための正規化."""
    t = unicodedata.normalize("NFKC", str(text))
    return re.sub(r"[\s　_\-・（）()【】\[\]]", "", t).lower()


@dataclass
class ImportResult:
    rows: list[dict[str, str]] = field(default_factory=list)
    mapping: dict[str, str] = field(default_factory=dict)      # 内部名 → 元の列名
    unmapped_columns: list[str] = field(default_factory=list)  # 使わなかった元の列
    missing_fields: list[str] = field(default_factory=list)    # 埋められなかった項目
    carried_over: int = 0                                      # 既存マスタから引き継いだ件数


def read_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """文字コードを順に試してCSVを読む."""
    path = Path(path)
    raw = path.read_bytes()
    last: Exception | None = None
    for enc in ENCODINGS:
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError as exc:
            last = exc
            continue
        reader = csv.DictReader(io.StringIO(text, newline=""))
        rows = list(reader)
        if reader.fieldnames:
            log.info("文字コード %s で読みました（%d行）", enc, len(rows))
            return list(reader.fieldnames), rows
    raise ValueError(
        f"{path} の文字コードを判別できませんでした（{last}）。"
        "Excelで開いて「CSV UTF-8（カンマ区切り）」で保存し直してください。"
    )


def build_mapping(
    headers: list[str], extra: dict[str, list[str]] | None = None
) -> tuple[dict[str, str], list[str]]:
    """元の列名を内部名に割り当てる."""
    aliases = {k: list(v) for k, v in ALIASES.items()}
    for internal, names in (extra or {}).items():
        aliases.setdefault(internal, [])
        aliases[internal] = list(names) + aliases[internal]

    by_key = {_key(h): h for h in headers if h}
    mapping: dict[str, str] = {}
    used: set[str] = set()

    # 完全一致を先に、そのあと部分一致
    for exact in (True, False):
        for internal, names in aliases.items():
            if internal in mapping:
                continue
            for cand in names:
                ck = _key(cand)
                for hk, original in by_key.items():
                    if original in used:
                        continue
                    hit = (hk == ck) if exact else (ck in hk or hk in ck)
                    if hit:
                        mapping[internal] = original
                        used.add(original)
                        break
                if internal in mapping:
                    break
    unmapped = [h for h in headers if h and h not in used]
    return mapping, unmapped


def extract_month(value: str) -> str:
    """「3」「3月」「2026/03/31」「令和8年3月31日」などから月だけ取り出す."""
    t = unicodedata.normalize("NFKC", str(value)).strip()
    if not t:
        return ""
    # 年月日の形（区切りが2つ以上）→ 真ん中を月とみなす
    parts = re.split(r"[/\-年月日.]", t)
    nums = [p for p in parts if p.isdigit()]
    if len(nums) >= 3:
        month = int(nums[1])
    elif len(nums) == 2:
        # 「2026/03」か「3月31日」かを、先頭が年らしいかで見分ける
        month = int(nums[1]) if len(nums[0]) == 4 else int(nums[0])
    elif len(nums) == 1:
        month = int(nums[0])
    else:
        return ""
    return str(month) if 1 <= month <= 12 else ""


def _taxable(value: str) -> str:
    t = unicodedata.normalize("NFKC", str(value)).strip()
    if not t:
        return "1"
    if re.search(r"(免税|非課税|対象外|なし|無)", t):
        return "0"
    return "1"


def convert(
    path: Path,
    existing: Path | None = None,
    extra_aliases: dict[str, list[str]] | None = None,
    default_office: str = "",
) -> ImportResult:
    """ソフトのCSVを、このツールの関与先マスタの形に変換する."""
    headers, src_rows = read_table(path)
    mapping, unmapped = build_mapping(headers, extra_aliases)

    carry = _load_existing(existing) if existing else {}
    result = ImportResult(mapping=mapping, unmapped_columns=unmapped)

    for src in src_rows:
        name = (src.get(mapping.get("name", ""), "") or "").strip()
        if not name:
            continue
        row = {jp: "" for jp in COLUMNS}
        row["法人名"] = name
        row["関与先コード"] = (src.get(mapping.get("code", ""), "") or "").strip()
        row["事務所"] = (src.get(mapping.get("office", ""), "") or "").strip() or default_office
        row["利用者識別番号"] = normalize_user_id(src.get(mapping.get("user_id", ""), ""))
        row["決算月"] = extract_month(src.get(mapping.get("fiscal_month", ""), ""))
        row["担当者"] = (src.get(mapping.get("staff", ""), "") or "").strip()
        row["消費税課税"] = (
            _taxable(src.get(mapping["consumption_taxable"], ""))
            if "consumption_taxable" in mapping else "1"
        )
        # 人が判断する項目は既定値
        row["法人税延長"] = "0"
        row["消費税延長"] = "0"
        row["有効"] = "1"
        row["備考"] = ""

        # 既存マスタに同じ関与先があれば、手で入れた項目を引き継ぐ
        prev = carry.get(row["利用者識別番号"]) or carry.get(row["関与先コード"])
        if prev:
            for internal in MANUAL_FIELDS:
                jp = INTERNAL_TO_JP[internal]
                if prev.get(jp, "").strip():
                    row[jp] = prev[jp]
            result.carried_over += 1

        result.rows.append(row)

    for internal in ("code", "name", "user_id", "fiscal_month", "staff"):
        if internal not in mapping:
            result.missing_fields.append(INTERNAL_TO_JP[internal])
    return result


def _load_existing(path: Path) -> dict[str, dict[str, str]]:
    """すでに作ってある関与先マスタを、コードと識別番号の両方で引けるようにする."""
    path = Path(path)
    if not path.exists():
        return {}
    index: dict[str, dict[str, str]] = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                uid = normalize_user_id(row.get("利用者識別番号", ""))
                code = (row.get("関与先コード") or "").strip()
                if uid:
                    index[uid] = row
                if code:
                    index.setdefault(code, row)
    except Exception as exc:  # noqa: BLE001
        log.warning("既存の関与先マスタを読めませんでした: %s", exc)
    return index


def write_clients_csv(rows: list[dict[str, str]], dest: Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return dest
