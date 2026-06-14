"""GLEIF プロバイダ (Global Legal Entity Identifier Foundation).

EU には統一的な財務開示 API (ESAP) が 2027〜2028 まで存在しないため、当面は
GLEIF の無料・キー不要の公式 API で **法人エンティティ情報** (LEI / 正式名称 /
国 / 法人状態) を取得し、企業の名寄せ・国判定に用いる。財務数値は提供されない。

エンドポイント (無料・キー不要):
  https://api.gleif.org/api/v1/lei-records?filter[entity.legalName]=...
"""

from __future__ import annotations

from typing import List, Optional

from ..http_client import HttpClient
from ..types import CompanyData, CompanyInfo
from .base import FinancialDataProvider

LEI_RECORDS_URL = "https://api.gleif.org/api/v1/lei-records"


class GleifProvider(FinancialDataProvider):
    name = "gleif"

    def __init__(self, http: HttpClient, country: Optional[str] = None):
        self.http = http
        self.country = country  # 例: "DE", "FR" で EU 各国に絞り込み

    def search(self, query: str, mode: str = "company", limit: int = 20) -> List[CompanyInfo]:
        query = (query or "").strip()
        if not query:
            return []
        params = {"filter[entity.legalName]": query, "page[size]": min(limit, 200)}
        if self.country:
            params["filter[entity.legalAddress.country]"] = self.country
        data = self.http.get_json(LEI_RECORDS_URL, params=params) or {}
        records = data.get("data", []) if isinstance(data, dict) else []
        results: List[CompanyInfo] = []
        for rec in records[:limit]:
            attrs = rec.get("attributes", {}) if isinstance(rec, dict) else {}
            entity = attrs.get("entity", {}) or {}
            name = (entity.get("legalName") or {}).get("name", "")
            addr = entity.get("legalAddress") or {}
            results.append(
                CompanyInfo(
                    cik=attrs.get("lei") or rec.get("id", ""),  # LEI を識別子に用いる
                    name=name,
                    country=addr.get("country"),
                    source=self.name,
                )
            )
        return results

    def fetch_financials(
        self,
        company: CompanyInfo,
        concepts: Optional[List[str]] = None,
        years: Optional[List[int]] = None,
    ) -> CompanyData:
        # GLEIF は財務数値を提供しない。エンティティ情報のみ返す。
        return CompanyData(
            info=company,
            facts=[],
            error="GLEIF はエンティティ情報のみ提供 (財務データなし)。EU 財務は ESAP 稼働後 (2027-2028) に対応予定。",
        )
