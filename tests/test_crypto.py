"""暗証番号の暗号化保管のテスト."""

import pytest

from etax_auto.crypto import CredentialStore

pytest.importorskip("cryptography")


def test_round_trip(tmp_path):
    path = tmp_path / "c.enc"
    s = CredentialStore(path, "master-pw")
    s.set("1234-5678-9012-3456", "暗証番号A")
    s.set("2345678901234567", "PW-B")
    s.save()

    again = CredentialStore(path, "master-pw").load()
    assert len(again) == 2
    assert again.get("1234567890123456") == "暗証番号A"   # ハイフンは無視される
    assert "2345-6789-0123-4567" in again


def test_wrong_master_password_is_rejected(tmp_path):
    path = tmp_path / "c.enc"
    s = CredentialStore(path, "right")
    s.set("1111111111111111", "x")
    s.save()
    with pytest.raises(ValueError, match="マスターパスワード"):
        CredentialStore(path, "wrong").load()


def test_file_is_not_plain_text(tmp_path):
    path = tmp_path / "c.enc"
    s = CredentialStore(path, "m")
    s.set("1111111111111111", "ひみつの暗証番号")
    s.save()
    blob = path.read_bytes()
    assert "ひみつの暗証番号".encode("utf-8") not in blob
    assert b"1111111111111111" not in blob


def test_delete(tmp_path):
    s = CredentialStore(tmp_path / "c.enc", "m")
    s.set("1111111111111111", "x")
    assert s.delete("1111-1111-1111-1111") is True
    assert s.delete("9999999999999999") is False
    assert len(s) == 0


def test_missing_file_starts_empty(tmp_path):
    s = CredentialStore(tmp_path / "none.enc", "m").load()
    assert len(s) == 0


def test_foreign_file_is_rejected(tmp_path):
    path = tmp_path / "c.enc"
    path.write_bytes(b"not ours")
    with pytest.raises(ValueError, match="認証情報ファイル"):
        CredentialStore(path, "m").load()
