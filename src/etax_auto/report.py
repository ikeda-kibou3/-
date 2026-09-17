"""実行結果の記録."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .logs import get_logger

log = get_logger(__name__)


@dataclass
class Row:
    関与先コード: str
    法人名: str
    事務所: str
    担当者: str
    決算期間: str
    法人税通知: str = "-"      # 取得 / 該当なし / 失敗 / -
    消費税通知: str = "-"
    チェックリスト: str = "-"
    束ねPDF: str = "-"
    メモ: str = ""


@dataclass
class Report:
    rows: list[Row] = field(default_factory=list)

    def add(self, row: Row) -> None:
        self.rows.append(row)

    @property
    def failures(self) -> list[Row]:
        return [r for r in self.rows if "失敗" in (r.法人税通知, r.消費税通知, r.チェックリスト)]

    def write_csv(self, dest: Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(Row.__annotations__))
            writer.writeheader()
            for row in self.rows:
                writer.writerow(asdict(row))
        log.info("結果一覧を書き出しました: %s", dest)
        return dest

    def summary(self) -> str:
        ok = len(self.rows) - len(self.failures)
        lines = [
            "",
            "=" * 58,
            f" 処理結果  {datetime.now():%Y年%m月%d日 %H:%M}",
            f"   対象 {len(self.rows)} 社 / 完了 {ok} 社 / 要確認 {len(self.failures)} 社",
        ]
        if self.failures:
            lines.append("")
            lines.append(" 【手作業で確認が必要な関与先】")
            for r in self.failures:
                lines.append(f"   ・{r.法人名}（{r.担当者}） {r.メモ}")
        lines.append("=" * 58)
        return "\n".join(lines)
