"""テスト共通: ネットワーク無しで SEC EDGAR を模擬する fake transport."""

from __future__ import annotations

import json

import pytest


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", content=b""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.content = content

    def json(self):
        return self._payload


# CIK 320193 = Apple を模した固定レスポンス
COMPANY_TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
}

SUBMISSIONS = {
    "name": "Apple Inc.",
    "sic": "3571",
    "sicDescription": "Electronic Computers",
    "fiscalYearEnd": "0930",
    "exchanges": ["Nasdaq"],
    "tickers": ["AAPL"],
    "addresses": {"business": {"stateOrCountryDescription": "California"}},
}

COMPANYFACTS = {
    "cik": 320193,
    "entityName": "Apple Inc.",
    "facts": {
        "us-gaap": {
            "Revenues": {
                "label": "Revenues",
                "units": {
                    "USD": [
                        {"val": 365817000000, "fy": 2021, "fp": "FY", "end": "2021-09-25",
                         "form": "10-K", "filed": "2021-10-29"},
                        {"val": 394328000000, "fy": 2022, "fp": "FY", "end": "2022-09-24",
                         "form": "10-K", "filed": "2022-10-28"},
                        {"val": 90000000000, "fy": 2022, "fp": "Q1", "end": "2021-12-25",
                         "form": "10-Q", "filed": "2022-01-28"},
                    ]
                },
            },
            "NetIncomeLoss": {
                "label": "Net Income (Loss)",
                "units": {
                    "USD": [
                        {"val": 94680000000, "fy": 2021, "fp": "FY", "end": "2021-09-25",
                         "form": "10-K", "filed": "2021-10-29"},
                        {"val": 99803000000, "fy": 2022, "fp": "FY", "end": "2022-09-24",
                         "form": "10-K", "filed": "2022-10-28"},
                    ]
                },
            },
        }
    },
}

FULLTEXT = {
    "hits": {
        "hits": [
            {"_source": {"ciks": ["0000320193"], "display_names": ["Apple Inc. (AAPL) (CIK 0000320193)"]}},
            {"_source": {"ciks": ["0000789019"], "display_names": ["Microsoft Corp (MSFT) (CIK 0000789019)"]}},
        ]
    }
}


def fake_transport(url, params, headers, timeout):
    if "company_tickers.json" in url:
        return FakeResponse(200, COMPANY_TICKERS)
    if "submissions/CIK" in url:
        return FakeResponse(200, SUBMISSIONS)
    if "companyfacts/CIK" in url:
        return FakeResponse(200, COMPANYFACTS)
    if "search-index" in url:
        return FakeResponse(200, FULLTEXT)
    return FakeResponse(404, None, "not found")


@pytest.fixture
def http():
    from ir_data.http_client import HttpClient

    return HttpClient(user_agent="test test@example.com", rate_limit_per_sec=0, transport=fake_transport)
