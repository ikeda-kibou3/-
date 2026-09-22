"""決算期の判定ロジックのテスト（ここが業務の心臓部）."""

from datetime import date

import pytest

from etax_auto.clients import (
    Client, add_months, fiscal_period, month_end, select_targets,
    shift_month, target_filing_month,
)


def make(code="0001", name="テスト株式会社", fiscal_month=3, **kw):
    base = dict(
        code=code, name=name, office="池田", user_id="1234567890123456",
        fiscal_month=fiscal_month, staff="山田",
    )
    base.update(kw)
    return Client(**base)


def test_shift_month_wraps():
    assert shift_month(3, 2) == 5
    assert shift_month(11, 2) == 1
    assert shift_month(12, 2) == 2
    assert shift_month(1, 0) == 1


def test_month_end():
    assert month_end(2026, 2) == date(2026, 2, 28)
    assert month_end(2024, 2) == date(2024, 2, 29)
    assert month_end(2026, 3) == date(2026, 3, 31)
    assert month_end(2026, 12) == date(2026, 12, 31)


def test_add_months_crosses_year():
    assert add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)
    assert add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)


def test_target_filing_month_is_next_month():
    assert target_filing_month(date(2026, 4, 15)) == date(2026, 5, 1)
    assert target_filing_month(date(2026, 12, 15)) == date(2027, 1, 1)


def test_march_close_is_picked_up_in_april():
    """3月決算 → 5月申告 → 4月に実行したとき対象になる."""
    targets = select_targets([make(fiscal_month=3)], date(2026, 4, 15))
    assert len(targets) == 1
    t = targets[0]
    assert t.need_corp and t.need_consumption
    assert t.filing_month == date(2026, 5, 1)
    assert t.period_end == date(2026, 3, 31)
    assert t.period_start == date(2025, 4, 1)


def test_march_close_not_picked_up_in_may():
    assert select_targets([make(fiscal_month=3)], date(2026, 5, 15)) == []


def test_extension_shifts_one_month():
    """申告期限延長ありの3月決算は6月申告 → 5月に実行したとき対象."""
    c = make(fiscal_month=3, corp_extension=1, consumption_extension=1)
    assert select_targets([c], date(2026, 4, 15)) == []
    targets = select_targets([c], date(2026, 5, 15))
    assert len(targets) == 1
    assert targets[0].filing_month == date(2026, 6, 1)
    assert targets[0].period_end == date(2026, 3, 31)


def test_corp_extension_only_splits_the_two_taxes():
    """法人税だけ延長。消費税は本来の月に、法人税は翌月に出てくる."""
    c = make(fiscal_month=3, corp_extension=1, consumption_extension=0)
    apr = select_targets([c], date(2026, 4, 15))
    assert len(apr) == 1 and apr[0].need_consumption and not apr[0].need_corp
    may = select_targets([c], date(2026, 5, 15))
    assert len(may) == 1 and may[0].need_corp and not may[0].need_consumption


def test_december_close_picked_up_in_january():
    targets = select_targets([make(fiscal_month=12)], date(2027, 1, 15))
    assert len(targets) == 1
    assert targets[0].filing_month == date(2027, 2, 1)
    assert targets[0].period_end == date(2026, 12, 31)


def test_tax_exempt_company_has_no_consumption_notice():
    c = make(fiscal_month=3, consumption_taxable=0)
    t = select_targets([c], date(2026, 4, 15))[0]
    assert t.need_corp and not t.need_consumption


def test_inactive_client_is_skipped():
    assert select_targets([make(fiscal_month=3, active=0)], date(2026, 4, 15)) == []


def test_fiscal_period_for_leap_february():
    start, end = fiscal_period(date(2024, 4, 1), months_after=2, extension=0)
    assert end == date(2024, 2, 29)
    assert start == date(2023, 3, 1)


def test_bad_fiscal_month_is_rejected():
    with pytest.raises(ValueError):
        make(fiscal_month=13)


def test_user_id_is_normalised():
    assert make(user_id="1234-5678-9012-3456").user_id == "1234567890123456"


def test_folder_name_is_windows_safe():
    assert "/" not in make(name="株式会社A/B").folder_name


@pytest.mark.parametrize("flag,expected", [("○", 1), ("有", 1), ("×", 0), ("なし", 0), ("", 0)])
def test_flag_parsing(flag, expected):
    assert make(corp_extension=flag).corp_extension == expected


# --- 紙から書き写すときの入力ミスを止められるか -----------------------

def test_user_id_must_be_16_digits():
    with pytest.raises(ValueError, match="16桁"):
        make(user_id="123456789012345")     # 15桁
    with pytest.raises(ValueError, match="16桁"):
        make(user_id="12345678901234567")   # 17桁


def test_full_width_digits_are_accepted():
    """Excelに貼ると全角数字が混ざることがある."""
    assert make(user_id="１２３４５６７８９０１２３４５６").user_id == "1234567890123456"


def test_user_id_with_spaces_and_hyphens():
    assert make(user_id=" 1234-5678 9012-3456 ").user_id == "1234567890123456"


def test_duplicate_client_code_is_rejected(tmp_path):
    from etax_auto.clients import load_clients

    csv_path = tmp_path / "c.csv"
    csv_path.write_text(
        "関与先コード,法人名,事務所,利用者識別番号,決算月,法人税延長,消費税延長,"
        "消費税課税,担当者,有効,備考\n"
        "0001,A社,池田,1111111111111111,3,0,0,1,山田,1,\n"
        "0001,B社,池田,2222222222222222,3,0,0,1,山田,1,\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="関与先コード.*重複"):
        load_clients(csv_path)


def test_duplicate_user_id_is_rejected(tmp_path):
    from etax_auto.clients import load_clients

    csv_path = tmp_path / "c.csv"
    csv_path.write_text(
        "関与先コード,法人名,事務所,利用者識別番号,決算月,法人税延長,消費税延長,"
        "消費税課税,担当者,有効,備考\n"
        "0001,A社,池田,1111111111111111,3,0,0,1,山田,1,\n"
        "0002,B社,池田,1111111111111111,9,0,0,1,佐藤,1,\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="利用者識別番号.*重複"):
        load_clients(csv_path)
