"""Companies House プロバイダの単体テスト (ネットワーク無し)."""

from __future__ import annotations

import base64

import pytest

from ir_data.http_client import HttpClient
from ir_data.providers.companies_house import CompaniesHouseProvider, parse_ixbrl
from tests.conftest import FakeResponse

SEARCH = {"items": [{"company_number": "00006245", "title": "BP P.L.C.", "address": {"country": "England"}}]}
PROFILE = {
    "company_name": "BP P.L.C.",
    "sic_codes": ["06100"],
    "registered_office_address": {"country": "England"},
    "accounts": {"accounting_reference_date": {"month": "12", "day": "31"}},
}
FILINGS = {"items": [{"type": "AA", "date": "2024-03-01", "description": "accounts"}]}

DOC_META_URL = "https://document-api.company-information.service.gov.uk/document/AbC123"
FILINGS_WITH_DOC = {
    "items": [
        {"type": "AA", "date": "2024-03-01", "description": "accounts",
         "links": {"document_metadata": DOC_META_URL}}
    ]
}
DOC_META = {"resources": {"application/xhtml+xml": {"content_type": "application/xhtml+xml"}}}

IXBRL = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:core="http://uk/core">
<head><ix:header><ix:resources>
  <xbrli:context id="dur24"><xbrli:entity/><xbrli:period>
    <xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate>
  </xbrli:period></xbrli:context>
  <xbrli:context id="ins24"><xbrli:entity/><xbrli:period>
    <xbrli:instant>2024-12-31</xbrli:instant>
  </xbrli:period></xbrli:context>
  <xbrli:unit id="GBP"><xbrli:measure>iso4217:GBP</xbrli:measure></xbrli:unit>
</ix:resources></ix:header></head>
<body>
  <p>Turnover&nbsp;<ix:nonFraction name="core:TurnoverRevenue" contextRef="dur24"
       unitRef="GBP" scale="3" decimals="0">1,234</ix:nonFraction></p>
  <p>Loss <ix:nonFraction name="core:ProfitLoss" contextRef="dur24" unitRef="GBP"
       sign="-" decimals="0">567</ix:nonFraction></p>
  <p>Equity <ix:nonFraction name="core:Equity" contextRef="ins24" unitRef="GBP"
       decimals="0">8,900</ix:nonFraction></p>
  <p>Blank <ix:nonFraction name="core:Blank" contextRef="ins24" unitRef="GBP">-</ix:nonFraction></p>
</body></html>"""


def ch_transport(url, params, headers, timeout):
    assert headers.get("Authorization", "").startswith("Basic ")
    if "/search/companies" in url:
        return FakeResponse(200, SEARCH)
    if "/filing-history" in url:
        return FakeResponse(200, FILINGS)
    if "/company/" in url:
        return FakeResponse(200, PROFILE)
    return FakeResponse(404, None)


def ch_transport_with_ixbrl(url, params, headers, timeout):
    assert headers.get("Authorization", "").startswith("Basic ")
    if "/search/companies" in url:
        return FakeResponse(200, SEARCH)
    if "/filing-history" in url:
        return FakeResponse(200, FILINGS_WITH_DOC)
    if url.endswith("/content"):
        assert headers.get("Accept") == "application/xhtml+xml"
        return FakeResponse(200, content=IXBRL)
    if "/document/" in url:
        return FakeResponse(200, DOC_META)
    if "/company/" in url:
        return FakeResponse(200, PROFILE)
    return FakeResponse(404, None)


def make(key="testkey", transport=ch_transport):
    http = HttpClient("ua", rate_limit_per_sec=0, transport=transport)
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


def test_parse_ixbrl_values_units_periods():
    facts = parse_ixbrl(IXBRL, cik="00006245", source="companies_house")
    by_concept = {f.concept: f for f in facts}
    # 空白 (-) は数値化されず除外される
    assert "core:Blank" not in by_concept
    # scale=3 が反映される (1,234 × 10^3)
    rev = by_concept["core:TurnoverRevenue"]
    assert rev.value == 1234000.0 and rev.unit == "GBP"
    assert rev.period_start == "2024-01-01" and rev.period_end == "2024-12-31" and rev.fy == 2024
    assert rev.label == "TurnoverRevenue"
    # sign="-" で負数
    assert by_concept["core:ProfitLoss"].value == -567.0
    # instant 文脈は period_end のみ (period_start なし)
    eq = by_concept["core:Equity"]
    assert eq.value == 8900.0 and eq.period_end == "2024-12-31" and eq.period_start is None


def test_ch_fetch_extracts_ixbrl_numbers():
    prov = make(transport=ch_transport_with_ixbrl)
    company = prov.search("BP")[0]
    data = prov.fetch_financials(company)
    # 提出件数ファクト + iXBRL 由来の数値ファクト
    assert any(f.concept == "AccountsFilings" for f in data.facts)
    rev = next(f for f in data.facts if f.concept == "core:TurnoverRevenue")
    assert rev.value == 1234000.0 and rev.unit == "GBP" and rev.fy == 2024
    # 数値抽出に成功したのでエラーは無い
    assert data.error is None
    # filed は最新提出日が補完される
    assert rev.filed == "2024-03-01"


def test_ch_fetch_year_filter():
    prov = make(transport=ch_transport_with_ixbrl)
    company = prov.search("BP")[0]
    data = prov.fetch_financials(company, years=[2099])
    # 2099 は無いので iXBRL 数値は除外され、AccountsFilings のみ残る
    assert all(f.concept == "AccountsFilings" for f in data.facts if f.source == "companies_house" and f.fy)
    assert not any(f.concept == "core:TurnoverRevenue" for f in data.facts)
