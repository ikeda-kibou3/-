"""チェックリストへの差し込み印字.

紙の原本をスキャンした PDF に、法人名・決算期間・担当者名を重ねて印字します。
原本のレイアウトはそのまま使えるので、書式を作り直す必要がありません。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .logs import get_logger

log = get_logger(__name__)

JP_FONT = "HeiseiKakuGo-W5"  # reportlab 同梱の日本語フォント（追加インストール不要）


def _register_font() -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    try:
        pdfmetrics.getFont(JP_FONT)
    except Exception:  # noqa: BLE001  未登録なら登録する
        pdfmetrics.registerFont(UnicodeCIDFont(JP_FONT))
    return JP_FONT


def load_checklist_config(path: Path) -> list[dict[str, Any]]:
    import yaml

    path = Path(path)
    if not path.exists():
        log.warning("チェックリスト設定がありません: %s", path)
        return []
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("checklists", [])


@dataclass
class FillValues:
    法人名: str
    決算期間: str
    決算期首: str
    決算期末: str
    担当者: str
    関与先コード: str
    申告年月: str
    事務所: str
    作成日: str = ""

    def as_dict(self) -> dict[str, str]:
        d = {k: v for k, v in self.__dict__.items()}
        if not d.get("作成日"):
            d["作成日"] = f"{date.today():%Y年%-m月%-d日}" if _supports_dash() else f"{date.today():%Y年%m月%d日}"
        return d


def _supports_dash() -> bool:
    try:
        format(date.today(), "%-d")
        return True
    except ValueError:  # Windows
        return False


def _overlay(template: Path, fields: list[dict], values: dict[str, str], dest: Path) -> Path:
    """テンプレートPDFの上に文字を重ねて dest に保存する."""
    import io

    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas

    font = _register_font()
    writer = PdfWriter(clone_from=str(template))

    # ページごとに重ねる文字をまとめる
    by_page: dict[int, list[dict]] = {}
    for f in fields:
        by_page.setdefault(int(f.get("page", 1)) - 1, []).append(f)

    for pno, page in enumerate(writer.pages):
        items = by_page.get(pno)
        if not items:
            continue
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(width, height))
        for f in items:
            text = str(f.get("text", "")).format(**values)
            c.setFont(font, float(f.get("size", 10)))
            c.drawString(float(f["x"]), float(f["y"]), text)
        c.save()
        buf.seek(0)
        page.merge_page(PdfReader(buf).pages[0])

    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as fh:
        writer.write(fh)
    return dest


def build_checklists(
    specs: list[dict[str, Any]],
    values: FillValues,
    out_dir: Path,
    need_corp: bool,
    need_consumption: bool,
    project_root: Path,
) -> list[Path]:
    """対象の関与先に必要なチェックリストを作って、作ったファイルを返す."""
    made: list[Path] = []
    vals = values.as_dict()
    for spec in specs:
        when = spec.get("when", "always")
        if when == "corp" and not need_corp:
            continue
        if when == "consumption" and not need_consumption:
            continue

        template = project_root / spec["template"]
        dest = Path(out_dir) / spec["output"]
        if not template.exists():
            log.warning(
                "チェックリストの原本PDFがありません: %s（%s は飛ばします）",
                template, spec.get("name", spec.get("id")),
            )
            continue

        fields = list(spec.get("fields", []))
        for mark in spec.get("marks", []):
            mw = mark.get("when", "always")
            if mw == "consumption" and not need_consumption:
                continue
            if mw == "corp" and not need_corp:
                continue
            fields.append(mark)

        _overlay(template, fields, vals, dest)
        made.append(dest)
        log.info("チェックリストを作成: %s", dest.name)
    return made


def calibrate(template: Path, dest: Path, step: int = 50) -> Path:
    """座標合わせ用に、方眼と目盛りを重ねたPDFを作る."""
    import io

    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas

    font = _register_font()
    writer = PdfWriter(clone_from=str(template))
    for page in writer.pages:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(width, height))
        c.setFont(font, 6)
        c.setStrokeColorRGB(0.85, 0.2, 0.2)
        c.setFillColorRGB(0.85, 0.2, 0.2)
        c.setLineWidth(0.3)
        x = 0
        while x <= width:
            c.line(x, 0, x, height)
            c.drawString(x + 1, 3, str(x))
            x += step
        y = 0
        while y <= height:
            c.line(0, y, width, y)
            c.drawString(2, y + 2, str(y))
            y += step
        c.save()
        buf.seek(0)
        page.merge_page(PdfReader(buf).pages[0])
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as fh:
        writer.write(fh)
    log.info("座標確認用PDFを作りました: %s", dest)
    return dest
