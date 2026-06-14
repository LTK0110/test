"""Companies House プロバイダ (英国・公式・無料キー必須).

英国法人の公的データを提供する公式 API。会社検索・会社プロファイル
(SIC 業種 / 所在国 / 会計年度) ・提出書類履歴を取得し、会計報告 (accounts) の
**iXBRL** (XHTML 埋め込み XBRL) を解析して数値財務を抽出する。

認証: API キーを Basic 認証のユーザ名 (パスワード空) として送る。
キー取得 (無料): https://developer.company-information.service.gov.uk/

数値財務は Document API 経由で会計報告本文 (application/xhtml+xml) を取得し、
``ix:nonFraction`` 要素を文脈 (期間) ・単位 (通貨) とともに構造化する。
"""

from __future__ import annotations

import base64
from html.parser import HTMLParser
from typing import Dict, List, Optional

from ..http_client import HttpClient
from ..types import CompanyData, CompanyInfo, FinancialFact
from .base import FinancialDataProvider

BASE = "https://api.company-information.service.gov.uk"
SEARCH_URL = BASE + "/search/companies"
COMPANY_URL = BASE + "/company/{number}"
FILING_URL = BASE + "/company/{number}/filing-history"

# iXBRL 本文の MIME (会計報告の数値が埋め込まれた XHTML)。
IXBRL_MIME = "application/xhtml+xml"


class _IxbrlParser(HTMLParser):
    """iXBRL (XHTML 埋め込み XBRL) から数値ファクト・文脈・単位を抽出する.

    厳密 XML 解析は DOCTYPE や HTML エンティティで失敗しやすいため、寛容な
    ``HTMLParser`` を用いる (タグ名・属性は小文字化される)。
    ``ix:nonFraction`` の数値を、``xbrli:context`` の期間と ``xbrli:unit`` の通貨に
    紐付けて取り出す。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.contexts: Dict[str, Dict[str, str]] = {}
        self.units: Dict[str, str] = {}
        self.facts: List[Dict[str, Optional[str]]] = []
        self._fact: Optional[Dict[str, Optional[str]]] = None
        self._fact_text: List[str] = []
        self._ctx_id: Optional[str] = None
        self._ctx: Optional[Dict[str, str]] = None
        self._unit_id: Optional[str] = None
        self._field: Optional[str] = None  # start / end / instant / measure
        self._field_text: List[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "ix:nonfraction":
            self._fact = {
                "name": a.get("name"),
                "context": a.get("contextref"),
                "unit": a.get("unitref"),
                "scale": a.get("scale"),
                "sign": a.get("sign"),
            }
            self._fact_text = []
        elif tag in ("xbrli:context", "context"):
            self._ctx_id = a.get("id")
            self._ctx = {}
        elif tag in ("xbrli:startdate", "startdate"):
            self._field, self._field_text = "start", []
        elif tag in ("xbrli:enddate", "enddate"):
            self._field, self._field_text = "end", []
        elif tag in ("xbrli:instant", "instant"):
            self._field, self._field_text = "instant", []
        elif tag in ("xbrli:unit", "unit"):
            self._unit_id = a.get("id")
        elif tag in ("xbrli:measure", "measure"):
            self._field, self._field_text = "measure", []

    def handle_data(self, data):
        if self._fact is not None:
            self._fact_text.append(data)
        if self._field is not None:
            self._field_text.append(data)

    def handle_endtag(self, tag):
        if tag == "ix:nonfraction" and self._fact is not None:
            self._fact["text"] = "".join(self._fact_text)
            self.facts.append(self._fact)
            self._fact = None
        elif tag in ("xbrli:startdate", "startdate", "xbrli:enddate", "enddate",
                     "xbrli:instant", "instant") and self._ctx is not None and self._field:
            self._ctx[self._field] = "".join(self._field_text).strip()
            self._field = None
        elif tag in ("xbrli:context", "context") and self._ctx_id is not None:
            self.contexts[self._ctx_id] = self._ctx or {}
            self._ctx_id, self._ctx = None, None
        elif tag in ("xbrli:measure", "measure") and self._field == "measure":
            if self._unit_id:
                self.units[self._unit_id] = "".join(self._field_text).strip()
            self._field = None
        elif tag in ("xbrli:unit", "unit"):
            self._unit_id = None


def _ixbrl_number(text: str, scale: Optional[str], sign: Optional[str]) -> Optional[float]:
    """iXBRL の表示テキストを scale (10^n 倍) と符号を反映した数値に変換する."""
    s = (text or "").strip().replace(",", "").replace("\xa0", "").replace(" ", "")
    neg_paren = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if not s or s in ("-", "—", "–"):
        return None
    try:
        value = float(s)
    except ValueError:
        return None
    if scale:
        try:
            value *= 10 ** int(scale)
        except ValueError:
            pass
    if sign == "-" or neg_paren:
        value = -abs(value)
    return value


def parse_ixbrl(content: bytes, cik: str, source: str) -> List[FinancialFact]:
    """iXBRL 本文 (バイト列) を解析して FinancialFact 群を返す."""
    parser = _IxbrlParser()
    parser.feed(content.decode("utf-8", errors="ignore"))
    facts: List[FinancialFact] = []
    for raw in parser.facts:
        value = _ixbrl_number(raw.get("text") or "", raw.get("scale"), raw.get("sign"))
        if value is None:
            continue
        ctx = parser.contexts.get(raw.get("context") or "", {})
        period_end = ctx.get("end") or ctx.get("instant")
        period_start = ctx.get("start")
        fy = int(period_end[:4]) if period_end and period_end[:4].isdigit() else None
        measure = parser.units.get(raw.get("unit") or "", "")
        unit = measure.split(":")[-1] if measure else ""  # iso4217:GBP -> GBP
        concept = raw.get("name") or ""
        facts.append(
            FinancialFact(
                cik=cik,
                concept=concept,
                label=concept.split(":")[-1] if concept else concept,
                unit=unit,
                value=value,
                fy=fy,
                period_start=period_start,
                period_end=period_end,
                form="accounts",
                context_id=raw.get("context"),
                source=source,
            )
        )
    return facts


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
        accounts = [i for i in items if (i.get("type") or "").upper().startswith("AA")]
        if not accounts:
            result.error = "Companies House: 会計報告 (accounts) の提出が見つかりませんでした。"
            return result
        latest = accounts[0]
        # 会計報告の提出件数を 1 ファクトとして残す (概観用)。
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
        # 最新の会計報告 iXBRL を取得・解析して数値財務を抽出する。
        numeric = self._fetch_account_facts(company.cik, latest)
        if numeric:
            if years:
                yset = set(years)
                numeric = [f for f in numeric if f.fy is None or f.fy in yset]
            for f in numeric:
                f.filed = f.filed or latest.get("date")
            result.facts.extend(numeric)
        else:
            result.error = (
                "Companies House: 提出履歴は取得したが、会計報告の iXBRL 数値を取得できませんでした "
                "(PDF のみ提出 / 本文非公開の可能性)。"
            )
        return result

    def _fetch_account_facts(self, cik: str, filing: Dict) -> List[FinancialFact]:
        """会計報告の Document API から iXBRL 本文を取得し数値ファクトを抽出する."""
        meta_url = ((filing.get("links") or {}).get("document_metadata")) or ""
        if not meta_url:
            return []
        try:
            meta = self.http.get_json(meta_url, headers=self._auth_headers()) or {}
            resources = meta.get("resources") or {}
            if IXBRL_MIME not in resources:
                return []  # iXBRL 本文が無い (PDF のみ等)
            content = self.http.get_bytes(
                meta_url.rstrip("/") + "/content",
                headers={**self._auth_headers(), "Accept": IXBRL_MIME},
            )
            if not content:
                return []
            return parse_ixbrl(content, cik, self.name)
        except Exception:  # noqa: BLE001 - 数値抽出失敗は致命的でない
            return []
