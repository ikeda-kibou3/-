"""PDF加工とチェックリスト差し込みのテスト."""

from datetime import date
from pathlib import Path

import pytest

from etax_auto import pdfwork
from etax_auto.checklist import FillValues, build_checklists, calibrate

reportlab = pytest.importorskip("reportlab")


def make_pdf(path: Path, pages: list[str], pagesize=(595, 842)) -> Path:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    try:
        pdfmetrics.getFont("HeiseiKakuGo-W5")
    except Exception:
        pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=pagesize)
    for text in pages:
        c.setFont("HeiseiKakuGo-W5", 12)
        for i, line in enumerate(text.split("\n")):
            c.drawString(60, pagesize[1] - 100 - i * 20, line)
        c.showPage()
    c.save()
    return path


def test_extract_pages_keeps_only_first(tmp_path):
    src = make_pdf(tmp_path / "src.pdf", ["1ページ目", "2ページ目"])
    dest = pdfwork.extract_pages(src, [1], tmp_path / "out.pdf")
    assert pdfwork.page_count(dest) == 1


def test_extract_pages_falls_back_when_range_is_wrong(tmp_path):
    src = make_pdf(tmp_path / "src.pdf", ["のみ"])
    dest = pdfwork.extract_pages(src, [5], tmp_path / "out.pdf")
    assert pdfwork.page_count(dest) == 1  # 全ページ残す


def test_merge_preserves_order_and_skips_missing(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", ["A"])
    b = make_pdf(tmp_path / "b.pdf", ["B1", "B2"])
    missing = tmp_path / "none.pdf"
    dest = pdfwork.merge([a, missing, b], tmp_path / "m.pdf")
    assert pdfwork.page_count(dest) == 3


def test_highlight_amounts_adds_annotation(tmp_path):
    src = make_pdf(tmp_path / "n.pdf", ["納付すべき税額 1,234,500 円"])
    dest = pdfwork.highlight_amounts(src, ["納付すべき税額"], tmp_path / "h.pdf")
    from pypdf import PdfReader

    annots = PdfReader(str(dest)).pages[0].get("/Annots")
    assert annots and len(annots) >= 1


def test_highlight_without_match_still_writes_file(tmp_path):
    src = make_pdf(tmp_path / "n.pdf", ["本文のみ"])
    dest = pdfwork.highlight_amounts(src, ["存在しない見出し"], tmp_path / "h.pdf")
    assert dest.exists()


def test_build_checklists_fills_name_and_period(tmp_path):
    tpl = make_pdf(tmp_path / "tpl.pdf", ["チェックリスト原本"])
    specs = [{
        "id": "01", "name": "テスト", "template": tpl.name,
        "output": "01.pdf", "when": "always",
        "fields": [{"page": 1, "x": 100, "y": 700, "size": 12, "text": "{法人名}"}],
        "marks": [{"page": 1, "x": 300, "y": 650, "size": 14, "text": "○", "when": "consumption"}],
    }]
    values = FillValues(
        法人名="株式会社テスト", 決算期間="2025年4月1日〜2026年3月31日",
        決算期首="2025年04月01日", 決算期末="2026年03月31日",
        担当者="山田", 関与先コード="0001", 申告年月="2026年05月", 事務所="池田税理士事務所",
    )
    made = build_checklists(specs, values, tmp_path / "out", True, True, project_root=tmp_path)
    assert len(made) == 1 and made[0].exists()

    import pdfplumber

    with pdfplumber.open(str(made[0])) as pdf:
        text = pdf.pages[0].extract_text()
    assert "株式会社テスト" in text


def test_checklist_skipped_when_not_applicable(tmp_path):
    tpl = make_pdf(tmp_path / "tpl.pdf", ["消費税用"])
    specs = [{"id": "03", "template": tpl.name, "output": "03.pdf",
              "when": "consumption", "fields": []}]
    made = build_checklists(specs, FillValues("A", "B", "C", "D", "E", "F", "G", "H"),
                            tmp_path / "out", True, False, project_root=tmp_path)
    assert made == []


def test_missing_template_is_skipped_not_fatal(tmp_path):
    specs = [{"id": "01", "template": "ない.pdf", "output": "01.pdf",
              "when": "always", "fields": []}]
    made = build_checklists(specs, FillValues("A", "B", "C", "D", "E", "F", "G", "H"),
                            tmp_path / "out", True, True, project_root=tmp_path)
    assert made == []


def test_calibrate_produces_grid(tmp_path):
    tpl = make_pdf(tmp_path / "tpl.pdf", ["原本"])
    dest = calibrate(tpl, tmp_path / "grid.pdf")
    assert dest.exists() and pdfwork.page_count(dest) == 1


# --- 未照合の記録 -----------------------------------------------------

def test_report_writes_unmatched_csv(tmp_path):
    from etax_auto.report import Report

    r = Report()
    r.add_unmatched("msg_001.pdf", "法人税及び地方法人税の確定申告について")
    dest = r.write_unmatched_csv(tmp_path / "_未照合PDF一覧.csv")
    assert dest and dest.exists()
    text = dest.read_text(encoding="utf-8-sig")
    assert "msg_001.pdf" in text
    assert "未照合" in r.summary()


def test_report_skips_unmatched_csv_when_none(tmp_path):
    from etax_auto.report import Report

    assert Report().write_unmatched_csv(tmp_path / "none.csv") is None
    assert not (tmp_path / "none.csv").exists()
