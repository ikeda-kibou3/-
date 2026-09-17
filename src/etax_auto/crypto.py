"""関与先の暗証番号（e-Tax パスワード）の暗号化保管.

紙ファイル（ピンク／黄色ファイル）を見ながら手入力していた暗証番号を、
1つの暗号化ファイル data/credentials.enc にまとめて持ちます。

* マスターパスワードを知らないと復号できません（scrypt + AES）。
* マスターパスワードはファイルに書かず、実行時に入力するか
  環境変数 ETAX_AUTO_MASTER で渡します。
* 平文の暗証番号をディスクに書き出す機能は用意していません。
"""

from __future__ import annotations

import base64
import getpass
import json
import os
import secrets
from pathlib import Path

MAGIC = b"ETAXAUTO1"


def _derive_key(master: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    kdf = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(master.encode("utf-8")))


def get_master(prompt: str = "マスターパスワード: ") -> str:
    master = os.environ.get("ETAX_AUTO_MASTER")
    if master:
        return master
    return getpass.getpass(prompt)


class CredentialStore:
    """{利用者識別番号: 暗証番号} を暗号化して保存する."""

    def __init__(self, path: Path, master: str) -> None:
        self.path = Path(path)
        self.master = master
        self._data: dict[str, str] = {}

    # --- 読み書き ---------------------------------------------------
    def load(self) -> "CredentialStore":
        from cryptography.fernet import Fernet, InvalidToken

        if not self.path.exists():
            self._data = {}
            return self
        blob = self.path.read_bytes()
        if not blob.startswith(MAGIC):
            raise ValueError(f"{self.path} は etax-auto の認証情報ファイルではありません。")
        salt = blob[len(MAGIC) : len(MAGIC) + 16]
        token = blob[len(MAGIC) + 16 :]
        try:
            plain = Fernet(_derive_key(self.master, salt)).decrypt(token)
        except InvalidToken as exc:
            raise ValueError("マスターパスワードが違います。") from exc
        self._data = json.loads(plain.decode("utf-8"))
        return self

    def save(self) -> None:
        from cryptography.fernet import Fernet

        salt = secrets.token_bytes(16)
        token = Fernet(_derive_key(self.master, salt)).encrypt(
            json.dumps(self._data, ensure_ascii=False).encode("utf-8")
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(MAGIC + salt + token)
        tmp.replace(self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass  # Windows では無視

    # --- 操作 -------------------------------------------------------
    def set(self, user_id: str, password: str) -> None:
        self._data[_norm(user_id)] = password

    def get(self, user_id: str) -> str | None:
        return self._data.get(_norm(user_id))

    def delete(self, user_id: str) -> bool:
        return self._data.pop(_norm(user_id), None) is not None

    def user_ids(self) -> list[str]:
        return sorted(self._data)

    def __contains__(self, user_id: str) -> bool:
        return _norm(user_id) in self._data

    def __len__(self) -> int:
        return len(self._data)


def _norm(user_id: str) -> str:
    return str(user_id).replace("-", "").replace(" ", "").strip()
