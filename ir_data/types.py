"""ドメインのデータ構造 (プロバイダ非依存)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 検索モード。company / ticker は直接解決、それ以外はキーワード全文検索。
SEARCH_MODES = ("company", "ticker", "industry", "application", "technology", "keyword")


@dataclass
class CompanyInfo:
    """企業の基本情報 (一次情報の発行体メタデータ)."""

    cik: str
    name: str
    ticker: Optional[str] = None
    exchange: Optional[str] = None
    sic: Optional[str] = None
    sic_description: Optional[str] = None
    country: Optional[str] = None
    fiscal_year_end: Optional[str] = None
    source: str = "sec_edgar"
    # プロバイダ固有のハンドル (例: EDINET の docID / edinetCode)。永続化対象外。
    extra: Dict[str, Any] = field(default_factory=dict)

    def key(self) -> str:
        """重複排除に使う一意キー."""
        return f"{self.source}:{self.cik}"


@dataclass
class FinancialFact:
    """単一の財務数値 (XBRL の 1 概念 1 期間)."""

    cik: str
    concept: str
    label: str
    unit: str
    value: float
    fy: Optional[int] = None
    fp: Optional[str] = None  # FY, Q1, Q2, ...
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    form: Optional[str] = None
    filed: Optional[str] = None
    source: str = "sec_edgar"

    def key(self) -> str:
        return f"{self.source}:{self.cik}:{self.concept}:{self.unit}:{self.fy}:{self.fp}:{self.period_end}"


@dataclass
class CompanyData:
    """企業 1 社の取得結果 (基本情報 + 財務数値群)."""

    info: CompanyInfo
    facts: List[FinancialFact] = field(default_factory=list)
    error: Optional[str] = None
