"""設定ファイル（settings.toml / selectors.yaml）の読み込み."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS = ROOT / "config" / "settings.toml"
DEFAULT_SELECTORS = ROOT / "config" / "selectors.yaml"
DEFAULT_CHECKLISTS = ROOT / "config" / "checklists.yaml"


@dataclass
class Settings:
    """settings.toml の内容。属性ではなく辞書アクセスで持つ."""

    path: Path
    raw: dict[str, Any] = field(default_factory=dict)

    # --- よく使う値のショートカット ---------------------------------
    @property
    def office_name(self) -> str:
        return self.raw["general"]["office_name"]

    @property
    def output_dir(self) -> Path:
        return _resolve(self.path, self.raw["general"]["output_dir"])

    @property
    def log_dir(self) -> Path:
        return _resolve(self.path, self.raw["general"]["log_dir"])

    @property
    def months_ahead(self) -> int:
        return int(self.raw["schedule"]["months_ahead"])

    @property
    def corp_months_after(self) -> int:
        return int(self.raw["schedule"]["corp_tax_months_after_close"])

    @property
    def consumption_months_after(self) -> int:
        return int(self.raw["schedule"]["consumption_tax_months_after_close"])

    def section(self, name: str) -> dict[str, Any]:
        return self.raw.get(name, {})


def _resolve(settings_path: Path, value: str) -> Path:
    """settings.toml から見た相対パスをプロジェクトルート基準に直す."""
    p = Path(value)
    if p.is_absolute():
        return p
    # config/settings.toml の1つ上＝プロジェクトルート
    return (settings_path.resolve().parent.parent / p).resolve()


def load_settings(path: Path | None = None) -> Settings:
    path = Path(path) if path else DEFAULT_SETTINGS
    if not path.exists():
        raise FileNotFoundError(
            f"設定ファイルが見つかりません: {path}\n"
            "config/settings.toml を用意してください。"
        )
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    return Settings(path=path, raw=raw)


def load_selectors(path: Path | None = None) -> dict[str, list[dict[str, str]]]:
    import yaml

    path = Path(path) if path else DEFAULT_SELECTORS
    if not path.exists():
        raise FileNotFoundError(f"セレクタ定義が見つかりません: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    # 値は必ずリストにそろえる
    return {k: (v if isinstance(v, list) else [v]) for k, v in data.items()}
