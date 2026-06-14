"""設定の読み込み (環境変数 / .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

try:  # python-dotenv は任意。無ければ環境変数のみ使用。
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


# SEC EDGAR は User-Agent の明示を必須としている (会社名/用途 + 連絡先メール)。
DEFAULT_USER_AGENT = "ir-data-tool (contact: set IR_DATA_USER_AGENT)"

# 既定で取得する US-GAAP の主要概念。
DEFAULT_CONCEPTS: List[str] = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "GrossProfit",
    "OperatingIncomeLoss",
    "NetIncomeLoss",
    "ResearchAndDevelopmentExpense",
    "Assets",
    "Liabilities",
    "StockholdersEquity",
    "CashAndCashEquivalentsAtCarryingValue",
    "EarningsPerShareBasic",
    "EarningsPerShareDiluted",
]


@dataclass
class Config:
    """実行時設定."""

    user_agent: str = field(default_factory=lambda: os.getenv("IR_DATA_USER_AGENT", DEFAULT_USER_AGENT))
    database_url: str = field(default_factory=lambda: os.getenv("IR_DATA_DATABASE_URL", "sqlite:///ir_data.db"))
    rate_limit_per_sec: float = field(default_factory=lambda: float(os.getenv("IR_DATA_RATE_LIMIT", "8")))
    max_workers: int = field(default_factory=lambda: int(os.getenv("IR_DATA_MAX_WORKERS", "8")))
    request_timeout: float = field(default_factory=lambda: float(os.getenv("IR_DATA_TIMEOUT", "30")))
    max_retries: int = field(default_factory=lambda: int(os.getenv("IR_DATA_MAX_RETRIES", "3")))
    concepts: List[str] = field(default_factory=lambda: list(DEFAULT_CONCEPTS))

    # 補完用の商用 API キー (任意・無料枠想定)。未設定でも公式一次情報のみで動作。
    alpha_vantage_key: Optional[str] = field(default_factory=lambda: os.getenv("ALPHA_VANTAGE_API_KEY"))

    def validate(self) -> List[str]:
        """設定上の警告メッセージ一覧を返す (致命的でないもの)."""
        warnings: List[str] = []
        if "set IR_DATA_USER_AGENT" in self.user_agent:
            warnings.append(
                "IR_DATA_USER_AGENT が未設定です。SEC EDGAR は連絡先付き User-Agent を要求します "
                "(例: 'MyApp my-email@example.com')。"
            )
        return warnings
