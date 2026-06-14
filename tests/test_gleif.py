"""GLEIF プロバイダの単体テスト (ネットワーク無し)."""

from __future__ import annotations

from ir_data.http_client import HttpClient
from ir_data.providers.gleif import GleifProvider
from tests.conftest import FakeResponse

GLEIF_PAYLOAD = {
    "data": [
        {
            "type": "lei-records",
            "id": "529900T8BM49AURSDO55",
            "attributes": {
                "lei": "529900T8BM49AURSDO55",
                "entity": {
                    "legalName": {"name": "Allianz SE"},
                    "legalAddress": {"country": "DE"},
                    "status": "ACTIVE",
                },
            },
        }
    ]
}


def gleif_transport(url, params, headers, timeout):
    if "lei-records" in url:
        return FakeResponse(200, GLEIF_PAYLOAD)
    return FakeResponse(404, None)


def make():
    http = HttpClient("ua", rate_limit_per_sec=0, transport=gleif_transport)
    return GleifProvider(http, country="DE")


def test_gleif_search():
    res = make().search("Allianz", mode="company")
    assert len(res) == 1
    assert res[0].cik == "529900T8BM49AURSDO55"
    assert res[0].name == "Allianz SE"
    assert res[0].country == "DE"
    assert res[0].source == "gleif"


def test_gleif_no_financials():
    prov = make()
    company = prov.search("Allianz")[0]
    data = prov.fetch_financials(company)
    assert data.facts == []
    # GLEIF はエンティティ情報のみ。これは実エラーではなく補足情報 (note)。
    assert data.error is None
    assert "財務データなし" in data.note
