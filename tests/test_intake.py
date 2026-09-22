"""手元のPDFを取り込む口のテスト."""

from pathlib import Path

import pytest

from etax_auto.intake import SourceDoc, core_name, find, load_folder, normalize

reportlab = pytest.importorskip("reportlab")

CORP = "法人税及び地方法人税.*確定申告"
CONS = "消費税及び地方消費税.*確定申告"


def make_pdf(path: Path, text: str) -> Path:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    try:
        pdfmetrics.getFont("HeiseiKakuGo-W5")
    except Exception:
        pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=(595, 842))
    c.setFont("HeiseiKakuGo-W5", 12)
    for i, line in enumerate(text.split("\n")):
        c.drawString(60, 740 - i * 20, line)
    c.save()
    return path


def test_core_name_strips_corporate_form():
    assert core_name("株式会社サンプル商事") == "サンプル商事"
    assert core_name("サンプル商事株式会社") == "サンプル商事"
    assert core_name("有限会社テスト製作所") == "テスト製作所"
    assert core_name("（株）サンプル商事") == "サンプル商事"
    assert core_name("医療法人社団みらい会") == "みらい会"


def test_normalize_absorbs_width_and_symbols():
    assert normalize("１２３４ ５６７８") == normalize("1234-5678")


def test_find_by_user_id_in_filename(tmp_path):
    p = make_pdf(tmp_path / "1234567890123456_法人税.pdf", "本文")
    docs = [SourceDoc(path=p, head_text="法人税及び地方法人税の確定申告について")]
    got = find(docs, name="株式会社サンプル商事", user_id="1234567890123456",
               code="0001", tax_pattern=CORP)
    assert got == p


def test_find_by_company_name_in_body(tmp_path):
    p = make_pdf(tmp_path / "download_0001.pdf", "本文")
    docs = [SourceDoc(
        path=p,
        head_text="サンプル商事 御中\n法人税及び地方法人税の確定申告についてのお知らせ",
    )]
    got = find(docs, name="株式会社サンプル商事", user_id="9999999999999999",
               code="0001", tax_pattern=CORP)
    assert got == p


def test_corp_and_consumption_are_separated(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", "x")
    b = make_pdf(tmp_path / "b.pdf", "x")
    docs = [
        SourceDoc(path=a, head_text="サンプル商事 法人税及び地方法人税の確定申告について"),
        SourceDoc(path=b, head_text="サンプル商事 消費税及び地方消費税の確定申告について"),
    ]
    kw = dict(name="株式会社サンプル商事", user_id="1234567890123456", code="0001")
    assert find(docs, tax_pattern=CORP, **kw) == a
    assert find(docs, tax_pattern=CONS, **kw) == b


def test_other_company_is_not_matched(tmp_path):
    p = make_pdf(tmp_path / "a.pdf", "x")
    docs = [SourceDoc(path=p, head_text="テスト製作所 法人税及び地方法人税の確定申告について")]
    assert find(docs, name="株式会社サンプル商事", user_id="1234567890123456",
                code="0001", tax_pattern=CORP) is None


def test_corporate_form_alone_does_not_match():
    """「株式会社」だけで他社に当たらないこと."""
    docs = [SourceDoc(path=Path("x.pdf"),
                      head_text="株式会社べつの会社 法人税及び地方法人税の確定申告について")]
    assert find(docs, name="株式会社サンプル商事", user_id="1111111111111111",
                code="0001", tax_pattern=CORP) is None


def test_missing_notice_returns_none():
    docs = [SourceDoc(path=Path("x.pdf"), head_text="サンプル商事 相続税の申告について")]
    assert find(docs, name="株式会社サンプル商事", user_id="1111111111111111",
                code="0001", tax_pattern=CORP) is None


def test_load_folder_reads_body_text(tmp_path):
    make_pdf(tmp_path / "sub" / "x.pdf", "法人税及び地方法人税の確定申告について")
    docs = load_folder(tmp_path)
    assert len(docs) == 1
    assert "法人税及び地方法人税" in docs[0].head_text


def test_load_folder_missing_dir_is_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="取り込み元のフォルダ"):
        load_folder(tmp_path / "ない")


def test_broken_pdf_does_not_stop_the_scan(tmp_path):
    (tmp_path / "こわれ.pdf").write_bytes(b"not a pdf")
    make_pdf(tmp_path / "ok.pdf", "法人税及び地方法人税の確定申告について")
    docs = load_folder(tmp_path)
    assert len(docs) == 2  # 壊れたファイルも一覧には残る（ファイル名で判定できるため）
