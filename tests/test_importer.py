"""会計・税務ソフトのCSVから関与先マスタを起こす処理のテスト."""

import csv

import pytest

from etax_auto.clients import load_clients
from etax_auto.importer import build_mapping, convert, extract_month, read_table, write_clients_csv


def write(path, rows, headers, encoding="cp932"):
    """ソフトが書き出したCSVを模す（既定は会計ソフトに多いShift_JIS）."""
    lines = [",".join(headers)]
    lines += [",".join(str(r.get(h, "")) for h in headers) for r in rows]
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode(encoding))
    return path


# --- 文字コード -------------------------------------------------------

@pytest.mark.parametrize("enc", ["cp932", "utf-8-sig", "utf-8"])
def test_reads_common_encodings(tmp_path, enc):
    p = write(tmp_path / "s.csv", [{"法人名": "株式会社あいう"}], ["法人名"], encoding=enc)
    headers, rows = read_table(p)
    assert headers == ["法人名"]
    assert rows[0]["法人名"] == "株式会社あいう"


# --- 列の突き合わせ ---------------------------------------------------

def test_mapping_matches_common_names():
    headers = ["顧問先コード", "顧問先名", "利用者識別番号", "決算月", "担当者名", "備考欄"]
    mapping, unmapped = build_mapping(headers)
    assert mapping["code"] == "顧問先コード"
    assert mapping["name"] == "顧問先名"
    assert mapping["user_id"] == "利用者識別番号"
    assert mapping["fiscal_month"] == "決算月"
    assert mapping["staff"] == "担当者名"
    assert "備考欄" in unmapped


def test_mapping_absorbs_width_and_symbols():
    mapping, _ = build_mapping(["ｅ－Ｔａｘ利用者識別番号", "会 社 名"])
    assert mapping["user_id"] == "ｅ－Ｔａｘ利用者識別番号"
    assert mapping["name"] == "会 社 名"


def test_extra_aliases_take_priority():
    mapping, _ = build_mapping(["取扱担当", "名称"], extra={"staff": ["取扱担当"]})
    assert mapping["staff"] == "取扱担当"


def test_one_column_is_not_used_twice():
    mapping, _ = build_mapping(["コード", "名称", "利用者識別番号"])
    assert len(set(mapping.values())) == len(mapping)


# --- 決算月の取り出し -------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("3", "3"), ("3月", "3"), ("２０２６/０３/３１", "3"),
    ("2026-03", "3"), ("令和8年3月31日", "3"), ("12月31日", "12"),
    ("", ""), ("13", ""), ("決算期", ""),
])
def test_extract_month(value, expected):
    assert extract_month(value) == expected


# --- 変換全体 ---------------------------------------------------------

SRC_HEADERS = ["顧問先コード", "顧問先名", "利用者識別番号", "事業年度終了日",
               "担当者名", "消費税区分", "部門名"]


def sample_rows():
    return [
        {"顧問先コード": "0001", "顧問先名": "株式会社サンプル商事",
         "利用者識別番号": "1234-5678-9012-3456", "事業年度終了日": "2026/03/31",
         "担当者名": "山田", "消費税区分": "課税", "部門名": "池田"},
        {"顧問先コード": "0003", "顧問先名": "サンプル合同会社",
         "利用者識別番号": "3456789012345678", "事業年度終了日": "2026/09/30",
         "担当者名": "鈴木", "消費税区分": "免税", "部門名": "阿部"},
    ]


def test_convert_produces_loadable_master(tmp_path):
    src = write(tmp_path / "tatsuzin.csv", sample_rows(), SRC_HEADERS)
    result = convert(src)
    dest = write_clients_csv(result.rows, tmp_path / "clients.csv")

    clients = load_clients(dest)      # 本番と同じ読み込みが通ること
    assert len(clients) == 2
    a, b = clients
    assert a.name == "株式会社サンプル商事"
    assert a.user_id == "1234567890123456"   # ハイフンが落ちている
    assert a.fiscal_month == 3
    assert a.office == "池田"
    assert a.consumption_taxable == 1
    assert b.fiscal_month == 9
    assert b.consumption_taxable == 0        # 「免税」を読み取る


def test_manual_fields_default_to_safe_values(tmp_path):
    src = write(tmp_path / "s.csv", sample_rows(), SRC_HEADERS)
    rows = convert(src).rows
    assert rows[0]["法人税延長"] == "0"
    assert rows[0]["消費税延長"] == "0"
    assert rows[0]["有効"] == "1"


def test_existing_manual_entries_are_carried_over(tmp_path):
    """2回目の取り込みで、手で入れた延長フラグを消さないこと."""
    existing = tmp_path / "clients.csv"
    write_clients_csv([{
        "関与先コード": "0001", "法人名": "株式会社サンプル商事", "事務所": "池田",
        "利用者識別番号": "1234567890123456", "決算月": "3",
        "法人税延長": "1", "消費税延長": "1", "消費税課税": "1",
        "担当者": "山田", "有効": "1", "備考": "延長あり",
    }], existing)

    src = write(tmp_path / "s.csv", sample_rows(), SRC_HEADERS)
    result = convert(src, existing=existing)
    assert result.carried_over == 1
    row = next(r for r in result.rows if r["関与先コード"] == "0001")
    assert row["法人税延長"] == "1"
    assert row["消費税延長"] == "1"
    assert row["備考"] == "延長あり"
    # 引き継ぎ対象でない関与先は既定のまま
    other = next(r for r in result.rows if r["関与先コード"] == "0003")
    assert other["法人税延長"] == "0"


def test_missing_columns_are_reported(tmp_path):
    src = write(tmp_path / "s.csv", [{"顧問先名": "株式会社あ"}], ["顧問先名"])
    result = convert(src)
    assert "利用者識別番号" in result.missing_fields
    assert "決算月" in result.missing_fields
    assert result.rows[0]["法人名"] == "株式会社あ"


def test_default_office_is_applied(tmp_path):
    src = write(tmp_path / "s.csv", [{"顧問先名": "株式会社あ"}], ["顧問先名"])
    result = convert(src, default_office="池田")
    assert result.rows[0]["事務所"] == "池田"


def test_rows_without_name_are_skipped(tmp_path):
    src = write(tmp_path / "s.csv",
                [{"顧問先名": "株式会社あ"}, {"顧問先名": ""}, {"顧問先名": "  "}],
                ["顧問先名"])
    assert len(convert(src).rows) == 1


def test_output_is_utf8_bom_for_excel(tmp_path):
    src = write(tmp_path / "s.csv", sample_rows(), SRC_HEADERS)
    dest = write_clients_csv(convert(src).rows, tmp_path / "out.csv")
    assert dest.read_bytes().startswith(b"\xef\xbb\xbf")
    with dest.open(encoding="utf-8-sig") as fh:
        assert list(csv.DictReader(fh))[0]["法人名"] == "株式会社サンプル商事"
