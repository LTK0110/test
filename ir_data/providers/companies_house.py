"""Companies House プロバイダ (英国・公式・無料キー必須).

英国法人の公的データを提供する公式 API。会社検索・会社プロファイル
(SIC 業種 / 所在国 / 会計年度) ・提出書類履歴を取得し、最新の会計報告
(iXBRL) を解析して **数値財務** を抽出する。

認証: API キーを Basic 認証のユーザ名 (パスワード空) として送る。
キー取得 (無料): https://developer.company-information.service.gov.uk/

数値財務は提出書類 (会計報告) 内の **iXBRL** に埋め込まれている。Document API
からその XHTML を取得し ``ir_data.ixbrl`` で全ファクトを構造化する。iXBRL が
取得・解析できない場合 (PDF のみ提出、egress 制限等) はメタデータと提出履歴に
フォールバックし note でその旨を伝える。
"""

from __future__ import annotations

import base64
import logging
from typing import Dict, List, Optional

from ..http_client import HttpClient
from ..ixbrl import parse_ixbrl
from ..types import CompanyData, CompanyInfo, FinancialFact
from .base import FinancialDataProvider

logger = logging.getLogger("ir_data")

BASE = "https://api.company-information.service.gov.uk"
SEARCH_URL = BASE + "/search/companies"
COMPANY_URL = BASE + "/company/{number}"
FILING_URL = BASE + "/company/{number}/filing-history"
IXBRL_CONTENT_TYPE = "application/xhtml+xml"


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
        # 会計報告の提出有無を「提出件数」として 1 ファクトに集約。
        accounts = [i for i in items if (i.get("type") or "").upper().startswith("AA")]
        if not accounts:
            result.note = "Companies House: 会計報告 (AA) の提出履歴が見つかりませんでした。"
            return result

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

        # 最新会計報告の iXBRL を解析して数値財務を取り込む。
        try:
            ixbrl_facts = self._fetch_ixbrl_facts(latest, years)
        except Exception as err:  # noqa: BLE001 - フォールバック (note) で継続
            logger.debug("iXBRL 取得失敗 [%s]: %s", company.cik, err)
            ixbrl_facts = []
            result.note = (
                "Companies House: メタデータと提出履歴を取得。iXBRL 取得に失敗したため "
                f"数値財務は未取得 ({err})。"
            )

        for f in ixbrl_facts:
            fy = int(f.period_end[:4]) if f.period_end and f.period_end[:4].isdigit() else None
            result.facts.append(
                FinancialFact(
                    cik=company.cik,
                    concept=f.concept,
                    label=f.label,
                    unit=f.unit,
                    value=f.value,
                    value_text=f.value_text,
                    fy=fy,
                    period_start=f.period_start,
                    period_end=f.period_end,
                    form=latest.get("type"),
                    filed=latest.get("date"),
                    dimension=f.dimension,
                    consolidation=f.consolidation,
                    context_id=f.context_id,
                    source=self.name,
                )
            )

        if ixbrl_facts:
            n_num = sum(1 for f in ixbrl_facts if f.value is not None)
            result.note = (
                f"Companies House: 最新会計報告の iXBRL から {len(ixbrl_facts)} 件 "
                f"(数値 {n_num} 件) を抽出。"
            )
        elif result.note is None:
            result.note = (
                "Companies House: メタデータと提出履歴を取得。最新会計報告に iXBRL "
                "(XHTML) が無いため数値財務は未取得 (PDF のみ等)。"
            )
        return result

    def _fetch_ixbrl_facts(self, filing: Dict, years: Optional[List[int]]):
        """提出書類の Document API から iXBRL を取得し解析する。

        会計報告のメタデータ → ``application/xhtml+xml`` リソースの content を取得。
        XHTML が提供されない (PDF のみ) 場合は空リストを返す。
        """
        meta_url = ((filing.get("links") or {}).get("document_metadata")) or ""
        if not meta_url:
            return []
        meta = self.http.get_json(meta_url, headers=self._auth_headers()) or {}
        resources = meta.get("resources") or {}
        if IXBRL_CONTENT_TYPE not in resources:
            return []
        raw = self.http.get_bytes(
            meta_url.rstrip("/") + "/content",
            headers={**self._auth_headers(), "Accept": IXBRL_CONTENT_TYPE},
        )
        if not raw:
            return []
        facts = parse_ixbrl(raw)
        if years:
            wanted = set(years)
            facts = [
                f for f in facts
                if not (f.period_end and f.period_end[:4].isdigit())
                or int(f.period_end[:4]) in wanted
            ]
        return facts
