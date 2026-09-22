"""すでに手元にあるPDFを取り込む口.

e-Tax に自前でログインせず、**別の手段で落としたPDFを読み込んで**
後工程（ページ抽出・ハイライト・チェックリスト・束ね）だけを回すための入口です。

想定している使いどころ:

* 電子申告の達人の「個別ダウンロード」で落としたファイル
* 将来、達人に一括ダウンロードが実装されたときの出力
* 職員が手で保存したPDF

出力形式が事前に分からなくても動くよう、**ファイル名と本文の両方**を見て
関与先と税目を突き合わせます。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .logs import get_logger

log = get_logger(__name__)

# 法人格の表記。固有部分だけで突き合わせるために取り除きます。
CORP_FORMS = [
    "株式会社", "有限会社", "合同会社", "合資会社", "合名会社",
    "一般社団法人", "一般財団法人", "公益社団法人", "公益財団法人",
    "医療法人社団", "医療法人", "社会福祉法人", "学校法人", "宗教法人",
    "特定非営利活動法人", "農業組合法人", "協同組合",
    "（株）", "(株)", "（有）", "(有)", "㈱", "㈲",
]


@dataclass
class SourceDoc:
    """取り込み対象の1ファイル."""

    path: Path
    head_text: str = ""          # 本文の先頭（税目と法人名の判定に使う）

    @property
    def haystack(self) -> str:
        return normalize(self.path.name + " " + self.head_text)


def normalize(text: str) -> str:
    """全角・半角、空白、記号のゆれをならす."""
    t = unicodedata.normalize("NFKC", str(text))
    return re.sub(r"[\s　・,，.。\-ー_（）()]", "", t)


def core_name(name: str) -> str:
    """法人名から法人格を取り除いて、固有の部分だけにする.

    「株式会社」だけで突き合わせると全社に当たってしまうため。
    """
    t = normalize(name)
    for form in CORP_FORMS:
        t = t.replace(normalize(form), "")
    return t


def load_folder(folder: Path, head_chars: int = 800) -> list[SourceDoc]:
    """フォルダ内のPDFを読み込み、本文の先頭を取り出す."""
    folder = Path(folder)
    if not folder.exists():
        raise FileNotFoundError(
            f"取り込み元のフォルダがありません: {folder}\n"
            "達人などで保存したPDFを置いたフォルダを指定してください。"
        )
    docs: list[SourceDoc] = []
    for path in sorted(folder.rglob("*.pdf")):
        docs.append(SourceDoc(path=path, head_text=_head_text(path, head_chars)))
    log.info("取り込み元 %s から %d 件のPDFを読みました", folder, len(docs))
    return docs


def _head_text(path: Path, limit: int) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            if not pdf.pages:
                return ""
            return (pdf.pages[0].extract_text() or "")[:limit]
    except Exception as exc:  # noqa: BLE001  壊れたPDFでも止めない
        log.warning("本文を読めませんでした（ファイル名だけで判定します）: %s（%s）", path.name, exc)
        return ""


def find(
    docs: list[SourceDoc],
    *,
    name: str,
    user_id: str,
    code: str,
    tax_pattern: str,
) -> Path | None:
    """関与先と税目の両方に当たるPDFを1つ探す.

    関与先の特定は 利用者識別番号 → 法人名の固有部分 → 関与先コード の順で試します。
    """
    # パターンは正規表現なので、記号を削る normalize() は通さない。
    # 全角・半角のゆれだけそろえる。
    rx = re.compile(unicodedata.normalize("NFKC", tax_pattern))
    keys = [k for k in (normalize(user_id), core_name(name)) if len(k) >= 2]
    # 関与先コードは短く誤当たりしやすいので、他が空のときだけ使う
    if not keys:
        keys = [normalize(code)]

    for doc in docs:
        hay = doc.haystack
        if not rx.search(hay):
            continue
        if any(key in hay for key in keys):
            log.info("取り込み: %s → %s", doc.path.name, name)
            return doc.path
    return None
