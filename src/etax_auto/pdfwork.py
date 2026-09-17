"""PDF の加工.

* 必要なページだけ取り出す（消費税は1ページ目のみ、など）
* 税額に黄色のハイライトを付ける（蛍光ペンの代わり）
* ①②③(a)(b) の順に1本へ束ねる
"""

from __future__ import annotations

import re
from pathlib import Path

from .logs import get_logger

log = get_logger(__name__)

# 金額らしい文字列（3桁区切り・円つきどちらも）
AMOUNT_RX = re.compile(r"[0-9０-９][0-9０-９,，]{2,}")


def extract_pages(src: Path, pages: list[int], dest: Path) -> Path:
    """1始まりのページ番号で抜き出して別ファイルに保存する."""
    from pypdf import PdfReader, PdfWriter

    src, dest = Path(src), Path(dest)
    reader = PdfReader(str(src))
    writer = PdfWriter()
    total = len(reader.pages)
    for p in pages:
        if 1 <= p <= total:
            writer.add_page(reader.pages[p - 1])
        else:
            log.warning("%s には %d ページ目がありません（全%dページ）", src.name, p, total)
    if not writer.pages:  # 指定が全部外れたら全ページ残す
        log.warning("ページ指定が合わないので全ページを使います: %s", src.name)
        for page in reader.pages:
            writer.add_page(page)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as fh:
        writer.write(fh)
    return dest


def highlight_amounts(pdf_path: Path, keywords: list[str], dest: Path | None = None) -> Path:
    """キーワードの右側にある金額に黄色のハイライトを付ける.

    通知書の文言は税目や年によって違うので、キーワードは
    settings.toml の [highlight] keywords で調整してください。
    """
    import pdfplumber
    from pypdf import PdfReader, PdfWriter
    from pypdf.annotations import Highlight
    from pypdf.generic import ArrayObject, FloatObject

    pdf_path = Path(pdf_path)
    dest = Path(dest) if dest else pdf_path

    boxes: dict[int, list[tuple[float, float, float, float]]] = {}
    with pdfplumber.open(str(pdf_path)) as pdf:
        for pno, page in enumerate(pdf.pages):
            words = page.extract_words() or []
            hits: list[tuple[float, float, float, float]] = []
            for kw in keywords:
                for idx, w in enumerate(words):
                    if kw in w["text"]:
                        # キーワードより右にある最初の金額を対象にする
                        for nxt in words[idx + 1 : idx + 12]:
                            if AMOUNT_RX.fullmatch(nxt["text"].strip()):
                                hits.append(
                                    (nxt["x0"], page.height - nxt["bottom"],
                                     nxt["x1"], page.height - nxt["top"])
                                )
                                break
            if hits:
                boxes[pno] = hits

    if not boxes:
        log.info("ハイライト対象の税額が見つかりませんでした: %s", pdf_path.name)
        if dest != pdf_path:
            dest.write_bytes(pdf_path.read_bytes())
        return dest

    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    for pno, rects in boxes.items():
        for (x0, y0, x1, y1) in rects:
            pad = 1.5
            quad = ArrayObject(
                [FloatObject(v) for v in
                 (x0 - pad, y1 + pad, x1 + pad, y1 + pad, x0 - pad, y0 - pad, x1 + pad, y0 - pad)]
            )
            ann = Highlight(
                rect=(x0 - pad, y0 - pad, x1 + pad, y1 + pad),
                quad_points=quad,
                highlight_color="FFFF00",
            )
            writer.add_annotation(page_number=pno, annotation=ann)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as fh:
        writer.write(fh)
    log.info("税額に色を付けました: %s（%d箇所）", dest.name, sum(len(v) for v in boxes.values()))
    return dest


def merge(sources: list[Path], dest: Path) -> Path:
    """複数PDFを順番どおりに1本へ束ねる."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    used = 0
    for src in sources:
        src = Path(src)
        if not src.exists():
            log.warning("束ねから外します（ファイルがありません）: %s", src)
            continue
        writer.append(str(src))
        used += 1
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as fh:
        writer.write(fh)
    log.info("%d 件を束ねました → %s", used, dest.name)
    return dest


def page_count(path: Path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(str(path)).pages)
