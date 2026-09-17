"""ログ設定."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_CONFIGURED = False


def setup_logging(log_dir: Path | None = None, verbose: bool = False) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger("etax_auto")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    stream = logging.StreamHandler(sys.stdout)
    stream.setLevel(logging.DEBUG if verbose else logging.INFO)
    stream.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(stream)

    if log_dir:
        from datetime import datetime

        Path(log_dir).mkdir(parents=True, exist_ok=True)
        path = Path(log_dir) / f"{datetime.now():%Y%m%d_%H%M%S}.log"
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root.addHandler(fh)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name if name.startswith("etax_auto") else f"etax_auto.{name}")
