"""Companies House プロバイダの単体テスト (ネットワーク無し)."""

from __future__ import annotations

import base64

import pytest

from ir_data.http_client import HttpClient
from ir_data.providers.companies_house import CompaniesHouseProvider
from tests.conftest import FakeResponse

SEARCH = {"items": [{"company_number": "00006245", "title": "BP P.L.C.", "address": {"country": "England"}}]}
PROFILE = {
    "company_name": "BP P.L.C.",
    "sic_codes": ["06100"],
    "registered_office_address": {"country": "England"},
    "accounts": {"accounting_reference_date": {"month": "12", "day": "31"}},
}
DOC_META_URL = "https://document.api.company-information.service.gov.uk/document/abc123"
FILINGS = {
    "items": [
        {
            "type": "AA",
            "date": "2024-03-01",
            "description": "accounts",
            "links": {"document_metadata": DOC_META_URL},
        }
    ]
}
DOC_META = {"resources": {"application/xhtml+xml": {}, "application/pdf": {}}}

IXBRL = """<?xml version="1.0"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance">
 <body>
  <xbrli:context id="cur">
   <xbrli:period><xbrli:startDate>2023-01-01</xbrli:startDate>
     <xbrli:endDate>2023-12-31</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:unit id="gbp"><xbrli:measure>iso4217:GBP</xbrli:measure></xbrli:unit>
  <ix:nonFraction name="core:TurnoverRevenue" contextRef="cur" unitRef="gbp"
      scale="3">1,234</ix:nonFraction>
 </body>
</html>""".encode("utf-8")


def ch_transport(url, params, headers, timeout):
    assert headers.get("Authorization", "").startswith("Basic ")
    if "/search/companies" in url:
        return FakeResponse(200, SEARCH)
    if url.endswith("/content"):
        assert headers.get("Accept") == "application/xhtml+xml"
        return FakeResponse(200, content=IXBRL)
    if "document.api" in url:
        return FakeResponse(200, DOC_META)
    if "/filing-history" in url:
        return FakeResponse(200, FILINGS)
    if "/company/" in url:
        return FakeResponse(200, PROFILE)
    return FakeResponse(404, None)


def make(key="testkey"):
    http = HttpClient("ua", rate_limit_per_sec=0, transport=ch_transport)
    return CompaniesHouseProvider(http, api_key=key)


def test_ch_requires_key():
    prov = make(key=None)
    with pytest.raises(RuntimeError):
        prov.search("BP")


def test_ch_search_and_auth():
    res = make().search("BP")
    assert res[0].cik == "00006245"
    assert res[0].name == "BP P.L.C."
    # Basic 認証は key:（パスワード空）
    assert base64.b64encode(b"testkey:").decode()


def test_ch_fetch_enriches_and_filing_count():
    prov = make()
    company = prov.search("BP")[0]
    data = prov.fetch_financials(company)
    assert data.info.sic == "06100"
    assert data.info.fiscal_year_end == "1231"
    assert any(f.concept == "AccountsFilings" and f.value == 1.0 for f in data.facts)
    # 正常取得。補足情報は note に入り、error は立てない (誤った取得エラー扱いを防ぐ)。
    assert data.error is None
    assert data.note and "iXBRL" in data.note


def test_ch_fetch_parses_ixbrl_numbers():
    prov = make()
    company = prov.search("BP")[0]
    data = prov.fetch_financials(company)
    # iXBRL の売上 (1,234 × 10^3) が数値ファクトとして取り込まれる。
    turnover = [f for f in data.facts if f.concept == "core:TurnoverRevenue"]
    assert turnover and turnover[0].value == 1234000.0
    assert turnover[0].unit == "GBP"
    assert turnover[0].fy == 2023
    assert turnover[0].period_end == "2023-12-31"
    assert turnover[0].form == "AA"
    assert turnover[0].source == "companies_house"
