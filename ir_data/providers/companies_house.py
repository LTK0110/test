"""Companies House プロバイダ (英国・公式・無料キー必須).

英国法人の公的データを提供する公式 API。会社検索・会社プロファイル
(SIC 業種 / 所在国 / 会計年度) ・提出書類履歴を取得する。

認証: API キーを Basic 認証のユーザ名 (パスワード空) として送る。
キー取得 (無料): https://developer.company-information.service.gov.uk/

注: 数値の財務データは提出書類 (会計報告) 内の **iXBRL** に含まれるため、
数値抽出は iXBRL 解析を要する (本フェーズではメタデータと提出履歴まで)。
"""

from __future__ import annotations

import base64
from typing import Dict, List, Optional

from ..http_client import HttpClient
from ..types import CompanyData, CompanyInfo, FinancialFact
from .base import FinancialDataProvider

BASE = "https://api.company-information.service.gov.uk"
SEARCH_URL = BASE + "/search/companies"
COMPANY_URL = BASE + "/company/{number}"
FILING_URL = BASE + "/company/{number}/filing-history"


class CompaniesHouseProvider(FinancialDataProvider):
    name = "companies_house"

    def __init__(self, http: HttpClient, api_key: Optional[str]):
        self.http = http
        self.api_key = api_key

    def _auth_headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise RuntimeError(
                "COMPANIES_HOUSE_API_KEY が未設定です。https://developer.company-information.service.gov.uk/ "
                "で無料キーを取得してください。"
            )
        token = base64.b64encode(f"{self.api_key}:".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def search(self, query: str, mode: str = "company", limit: int = 20) -> List[CompanyInfo]:
        query = (query or "").strip()
        if not query:
            return []
        data = self.http.get_json(
            SEARCH_URL,
            params={"q": query, "items_per_page": min(limit, 100)},
            headers=self._auth_headers(),
        ) or {}
        items = data.get("items", []) if isinstance(data, dict) else []
        results: List[CompanyInfo] = []
        for it in items[:limit]:
            addr = it.get("address", {}) or {}
            results.append(
                CompanyInfo(
                    cik=it.get("company_number", ""),  # 英国は company number を識別子に
                    name=it.get("title", ""),
                    country=addr.get("country"),
                    source=self.name,
                )
            )
        return results

    def enrich(self, company: CompanyInfo) -> CompanyInfo:
        data = self.http.get_json(
            COMPANY_URL.format(number=company.cik), headers=self._auth_headers()
        )
        if not data:
            return company
        company.name = data.get("company_name") or company.name
        sic_codes = data.get("sic_codes") or []
        if sic_codes:
            company.sic = sic_codes[0]
        addr = data.get("registered_office_address") or {}
        company.country = addr.get("country") or company.country
        accounts = (data.get("accounts") or {}).get("accounting_reference_date") or {}
        if accounts.get("month") and accounts.get("day"):
            company.fiscal_year_end = f"{int(accounts['month']):02d}{int(accounts['day']):02d}"
        return company

    def fetch_financials(
        self,
        company: CompanyInfo,
        concepts: Optional[List[str]] = None,
        years: Optional[List[int]] = None,
    ) -> CompanyData:
        self.enrich(company)
        result = CompanyData(info=company, facts=[])
        filings = self.http.get_json(
            FILING_URL.format(number=company.cik),
            params={"category": "accounts", "items_per_page": 100},
            headers=self._auth_headers(),
        ) or {}
        items = filings.get("items", []) if isinstance(filings, dict) else []
        # 会計報告の提出有無を「提出件数」として 1 ファクトに集約 (数値抽出は iXBRL 解析が次段階)。
        accounts = [i for i in items if (i.get("type") or "").upper().startswith("AA")]
        if accounts:
            latest = accounts[0]
            result.facts.append(
                FinancialFact(
                    cik=company.cik,
                    concept="AccountsFilings",
                    label="会計報告 提出件数 (最新提出日含む)",
                    unit="count",
                    value=float(len(accounts)),
                    filed=latest.get("date"),
                    form=latest.get("type"),
                    source=self.name,
                )
            )
        result.note = (
            "Companies House: メタデータと提出履歴を取得。数値財務は iXBRL 解析が必要 (次フェーズ)。"
        )
        return result
