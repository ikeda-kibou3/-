"""e-Tax を模したモック画面を相手に、ブラウザ操作の流れ全体を確かめる.

本物の e-Tax につながなくても、
「ログイン → お知らせを探す → PDFにする → 戻る → ログアウト」
の配線が壊れていないことをここで検出できます。
"""

from pathlib import Path

import pytest

pytest.importorskip("playwright")

from etax_auto import pdfwork  # noqa: E402
from etax_auto.config import load_selectors  # noqa: E402
from etax_auto.etax import EtaxOptions, EtaxSession, StepNotFound  # noqa: E402

MOCK = Path(__file__).parent / "mock_etax" / "index.html"
GOOD_ID = "1234567890123456"
GOOD_PW = "正しい暗証番号"


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(
    not _chromium_available(), reason="Chromium が入っていません（playwright install chromium）"
)


def make_opts(tmp_path: Path, **kw) -> EtaxOptions:
    base = dict(
        login_url=MOCK.as_uri(),
        timeout_sec=15,
        headful=False,
        manual_assist=False,      # テストでは人を待たせない
        capture_dir=tmp_path / "capture",
        selectors=load_selectors(),
    )
    base.update(kw)
    return EtaxOptions(**base)


def test_login_reaches_menu(tmp_path):
    with EtaxSession(make_opts(tmp_path)) as s:
        s.login(GOOD_ID, GOOD_PW)
        assert "メインメニュー" in s.page.inner_text("body")


def test_wrong_password_is_detected(tmp_path):
    with EtaxSession(make_opts(tmp_path)) as s:
        with pytest.raises(RuntimeError, match="ログインに失敗"):
            s.login(GOOD_ID, "ちがう暗証番号")


def test_notice_list_and_both_taxes(tmp_path):
    with EtaxSession(make_opts(tmp_path)) as s:
        s.login(GOOD_ID, GOOD_PW)
        s.open_notice_list()
        titles = " ".join(s.list_notice_titles())
        assert "法人税及び地方法人税の確定申告についてのお知らせ" in titles
        assert "消費税及び地方消費税の確定申告について" in titles


def test_open_notice_and_save_pdf(tmp_path):
    with EtaxSession(make_opts(tmp_path)) as s:
        s.login(GOOD_ID, GOOD_PW)
        s.open_notice_list()

        assert s.open_notice("法人税及び地方法人税.*確定申告") is True
        corp = tmp_path / "a_法人税通知.pdf"
        s.save_current_as_pdf(corp)
        assert corp.exists() and pdfwork.page_count(corp) >= 1

        s.back()
        assert s.open_notice("消費税及び地方消費税.*確定申告") is True
        cons = tmp_path / "b_消費税通知.pdf"
        s.save_current_as_pdf(cons)
        assert cons.exists()

        import pdfplumber

        with pdfplumber.open(str(corp)) as pdf:
            assert "法人税及び地方法人税" in (pdf.pages[0].extract_text() or "")
        with pdfplumber.open(str(cons)) as pdf:
            assert "消費税及び地方消費税" in (pdf.pages[0].extract_text() or "")


def test_highlight_runs_on_saved_notice(tmp_path):
    """保存した通知書の税額に、実際に色が付くところまで通す."""
    with EtaxSession(make_opts(tmp_path)) as s:
        s.login(GOOD_ID, GOOD_PW)
        s.open_notice_list()
        s.open_notice("法人税及び地方法人税.*確定申告")
        raw = tmp_path / "raw.pdf"
        s.save_current_as_pdf(raw)

    out = pdfwork.extract_pages(raw, [1], tmp_path / "out.pdf")
    pdfwork.highlight_amounts(out, ["納付すべき税額"])
    from pypdf import PdfReader

    assert PdfReader(str(out)).pages[0].get("/Annots")


def test_missing_notice_returns_false(tmp_path):
    with EtaxSession(make_opts(tmp_path)) as s:
        s.login(GOOD_ID, GOOD_PW)
        s.open_notice_list()
        assert s.open_notice("相続税の申告について") is False


def test_unknown_step_raises_when_manual_assist_off(tmp_path):
    opts = make_opts(tmp_path)
    opts.selectors["message_box"] = [{"text": "存在しないボタン"}]
    with EtaxSession(opts) as s:
        s.login(GOOD_ID, GOOD_PW)
        with pytest.raises(StepNotFound):
            s.open_notice_list()
    # 失敗した画面が調査用に保存されていること
    assert list((tmp_path / "capture").glob("*.png"))


def test_logout_is_optional_and_never_raises(tmp_path):
    with EtaxSession(make_opts(tmp_path)) as s:
        s.login(GOOD_ID, GOOD_PW)
        s.logout()
        assert "国税電子申告" in s.page.inner_text("body")
