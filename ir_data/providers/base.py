"""データプロバイダの抽象基底."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from ..types import CompanyData, CompanyInfo


class FinancialDataProvider(ABC):
    """財務・IR データ取得元の共通インタフェース.

    新しい取得元 (例: 日本の EDINET、欧州の各当局) を追加する場合は
    本クラスを継承し ``name`` / ``search`` / ``fetch_financials`` を実装する。
    """

    name: str = "base"

    @abstractmethod
    def search(self, query: str, mode: str = "company", limit: int = 20) -> List[CompanyInfo]:
        """検索条件にマッチする企業の基本情報一覧を返す."""

    @abstractmethod
    def fetch_financials(
        self,
        company: CompanyInfo,
        concepts: Optional[List[str]] = None,
        years: Optional[List[int]] = None,
    ) -> CompanyData:
        """指定企業の財務数値を取得して返す."""
