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
    """単一のデータ点 (XBRL の 1 要素 × 1 コンテキスト)。数値・テキスト両対応。"""

    cik: str
    concept: str          # 要素ID (EDINET) / us-gaap タグ (SEC)
    label: str            # 項目名 / ラベル
    unit: str = ""        # 円, USD, 株, ...
    value: Optional[float] = None       # 数値 (数値でない場合 None)
    value_text: Optional[str] = None    # テキストブロック等の非数値 (叙述情報含む)
    fy: Optional[int] = None
    fp: Optional[str] = None            # FY, Q1, ... / 当期・前期
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    form: Optional[str] = None
    filed: Optional[str] = None
    # 事業別/地域別などのセグメント次元 (XBRL ディメンション member)。
    # None = 連結合計 (全社)、値あり = 当該セグメントの内訳。
    dimension: Optional[str] = None
    consolidation: Optional[str] = None  # 連結 / 個別 (EDINET)
    context_id: Optional[str] = None     # XBRL コンテキストID (一意性の元)
    source: str = "sec_edgar"

    def key(self) -> str:
        ctx = self.context_id or f"{self.fy}:{self.fp}:{self.period_end}:{self.dimension or ''}:{self.consolidation or ''}"
        return f"{self.source}:{self.cik}:{self.concept}:{self.unit}:{ctx}"

    @property
    def is_segment(self) -> bool:
        return self.dimension is not None

    @property
    def is_text(self) -> bool:
        return self.value is None and bool(self.value_text)


@dataclass
class CompanyData:
    """企業 1 社の取得結果 (基本情報 + 全データ点)."""

    info: CompanyInfo
    facts: List[FinancialFact] = field(default_factory=list)
    error: Optional[str] = None  # 取得失敗時のみ設定 (実エラー)
    note: Optional[str] = None   # 正常取得時の補足情報 (例: 数値財務は未対応)

    @property
    def numeric_facts(self) -> List["FinancialFact"]:
        return [f for f in self.facts if f.value is not None]

    @property
    def text_facts(self) -> List["FinancialFact"]:
        return [f for f in self.facts if f.is_text]
