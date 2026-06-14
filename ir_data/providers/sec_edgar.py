"""SEC EDGAR プロバイダ (米国上場企業の無料・公式な一次情報).

利用する公開エンドポイント (いずれも無料・API キー不要):
  - 銘柄一覧:     https://www.sec.gov/files/company_tickers.json
  - 発行体メタ:   https://data.sec.gov/submissions/CIK##########.json
  - 財務 (XBRL):  https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
  - 全文検索:     https://efts.sec.gov/LATEST/search-index?q=...&forms=10-K

company / ticker モードは銘柄一覧で CIK を解決する。
industry / application / technology / keyword モードは提出書類の全文検索を用い、
キーワードを含む書類の発行体を企業候補として返す。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..http_client import HttpClient
from ..types import CompanyData, CompanyInfo, FinancialFact
from .base import FinancialDataProvider

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
FULLTEXT_URL = "https://efts.sec.gov/LATEST/search-index"

KEYWORD_MODES = {"industry", "application", "technology", "keyword"}


def pad_cik(cik) -> str:
    """CIK を 10 桁ゼロ埋め文字列へ正規化する."""
    return str(int(str(cik).lstrip("CIK").strip() or 0)).zfill(10)


class SecEdgarProvider(FinancialDataProvider):
    name = "sec_edgar"

    def __init__(self, http: HttpClient, default_forms: str = "10-K"):
        self.http = http
        self.default_forms = default_forms
        self._ticker_index: Optional[List[Dict]] = None

    # ------------------------------------------------------------------ 検索
    def search(self, query: str, mode: str = "company", limit: int = 20) -> List[CompanyInfo]:
        query = (query or "").strip()
        if not query:
            return []
        if mode in KEYWORD_MODES:
            return self._search_fulltext(query, limit)
        return self._search_company(query, mode, limit)

    def _load_tickers(self) -> List[Dict]:
        if self._ticker_index is None:
            data = self.http.get_json(TICKERS_URL) or {}
            # {"0": {"cik_str":320193,"ticker":"AAPL","title":"Apple Inc."}, ...}
            self._ticker_index = list(data.values()) if isinstance(data, dict) else list(data)
        return self._ticker_index

    def _search_company(self, query: str, mode: str, limit: int) -> List[CompanyInfo]:
        rows = self._load_tickers()
        q = query.upper()
        matches: List[Dict] = []
        for row in rows:
            ticker = str(row.get("ticker", "")).upper()
            title = str(row.get("title", "")).upper()
            if mode == "ticker":
                if ticker == q:
                    matches.append(row)
            else:  # company: 完全一致を優先しつつ部分一致も許容
                if q == ticker or q in title:
                    matches.append(row)
        # 完全一致を先頭へ
        matches.sort(key=lambda r: 0 if q in (str(r.get("ticker", "")).upper(), str(r.get("title", "")).upper()) else 1)
        results = []
        for row in matches[:limit]:
            results.append(
                CompanyInfo(
                    cik=pad_cik(row.get("cik_str")),
                    name=row.get("title", ""),
                    ticker=row.get("ticker"),
                    source=self.name,
                )
            )
        return results

    def _search_fulltext(self, query: str, limit: int) -> List[CompanyInfo]:
        data = self.http.get_json(FULLTEXT_URL, params={"q": query, "forms": self.default_forms}) or {}
        hits = (data.get("hits", {}) or {}).get("hits", []) if isinstance(data, dict) else []
        seen: Dict[str, CompanyInfo] = {}
        for hit in hits:
            src = hit.get("_source", {}) if isinstance(hit, dict) else {}
            ciks = src.get("ciks") or ([src.get("cik")] if src.get("cik") else [])
            names = src.get("display_names") or []
            for i, raw_cik in enumerate(ciks):
                if not raw_cik:
                    continue
                cik = pad_cik(raw_cik)
                if cik in seen:
                    continue
                name = names[i] if i < len(names) else (names[0] if names else "")
                # display_names は "Apple Inc. (AAPL) (CIK 0000320193)" 形式
                ticker = None
                if "(" in name and ")" in name:
                    inner = name.split("(")[1].split(")")[0].strip()
                    if inner and inner.upper() == inner and " " not in inner:
                        ticker = inner
                seen[cik] = CompanyInfo(cik=cik, name=name.split(" (")[0], ticker=ticker, source=self.name)
                if len(seen) >= limit:
                    return list(seen.values())
        return list(seen.values())

    # ------------------------------------------------------------ メタ + 財務
    def enrich(self, company: CompanyInfo) -> CompanyInfo:
        """submissions エンドポイントで発行体メタデータを補完する."""
        data = self.http.get_json(SUBMISSIONS_URL.format(cik=pad_cik(company.cik)))
        if not data:
            return company
        company.name = data.get("name") or company.name
        company.sic = str(data.get("sic")) if data.get("sic") else company.sic
        company.sic_description = data.get("sicDescription") or company.sic_description
        company.fiscal_year_end = data.get("fiscalYearEnd") or company.fiscal_year_end
        exchanges = data.get("exchanges") or []
        if exchanges:
            company.exchange = exchanges[0]
        tickers = data.get("tickers") or []
        if tickers and not company.ticker:
            company.ticker = tickers[0]
        addresses = data.get("addresses") or {}
        biz = addresses.get("business") or {}
        company.country = biz.get("stateOrCountryDescription") or company.country
        return company

    def fetch_financials(
        self,
        company: CompanyInfo,
        concepts: Optional[List[str]] = None,
        years: Optional[List[int]] = None,
    ) -> CompanyData:
        self.enrich(company)
        result = CompanyData(info=company, facts=[])
        data = self.http.get_json(COMPANYFACTS_URL.format(cik=pad_cik(company.cik)))
        if not data:
            result.error = "companyfacts が取得できませんでした"
            return result
        all_facts = (data.get("facts") or {}) if isinstance(data, dict) else {}
        wanted = set(concepts) if concepts else None  # None = 全概念を取得
        year_set = set(years) if years else None
        # us-gaap / dei / ifrs-full 等、全タクソノミを横断して全データを取り込む。
        for taxonomy, concepts_map in all_facts.items():
            for concept, payload in (concepts_map or {}).items():
                if wanted is not None and concept not in wanted:
                    continue
                label = payload.get("label") or concept
                for unit, entries in (payload.get("units") or {}).items():
                    for e in entries:
                        fy = e.get("fy")
                        if year_set is not None and fy not in year_set:
                            continue
                        result.facts.append(
                            FinancialFact(
                                cik=company.cik,
                                concept=f"{taxonomy}:{concept}",
                                label=label,
                                unit=unit,
                                value=float(e.get("val")) if e.get("val") is not None else None,
                                fy=fy,
                                fp=e.get("fp"),  # FY / Q1 / Q2 ... (全期間を保持)
                                period_start=e.get("start"),
                                period_end=e.get("end"),
                                form=e.get("form"),
                                filed=e.get("filed"),
                                context_id=e.get("frame"),
                                source=self.name,
                            )
                        )
        # 同一 (concept, unit, fy, fp, period) の重複を最新 filed で集約 (訂正報告対応)
        result.facts = _dedupe_latest(result.facts)
        return result


def _dedupe_latest(facts: List[FinancialFact]) -> List[FinancialFact]:
    best: Dict[str, FinancialFact] = {}
    for f in facts:
        k = f"{f.concept}:{f.unit}:{f.fy}:{f.fp}:{f.period_start}:{f.period_end}"
        cur = best.get(k)
        if cur is None or (f.filed or "") > (cur.filed or ""):
            best[k] = f
    return sorted(best.values(), key=lambda f: (f.concept, f.fy or 0, f.fp or ""))
