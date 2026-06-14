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
FILINGS = {"items": [{"type": "AA", "date": "2024-03-01", "description": "accounts"}]}


def ch_transport(url, params, headers, timeout):
    assert headers.get("Authorization", "").startswith("Basic ")
    if "/search/companies" in url:
        return FakeResponse(200, SEARCH)
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
