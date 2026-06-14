"""EDINET プロバイダの単体テスト (ネットワーク無し)."""

from __future__ import annotations

import io
import zipfile

import pytest

from ir_data.http_client import HttpClient
from ir_data.providers.edinet import EdinetProvider
from tests.conftest import FakeResponse

DOC_LIST = {
    "metadata": {"resultset": {"count": 1}},
    "results": [
        {
            "docID": "S100ABCD",
            "edinetCode": "E12345",
            "secCode": "72030",
            "filerName": "トヨタ自動車株式会社",
            "docTypeCode": "120",
            "docDescription": "有価証券報告書",
            "periodEnd": "2024-03-31",
            "JCN": "1180301018771",
        }
    ],
}


def _make_csv_zip() -> bytes:
    header = ["要素ID", "項目名", "コンテキストID", "相対年度", "連結・個別", "期間・時点", "ユニットID", "単位", "値"]
    rows = [
        header,
        ["jpcrp_cor:NetSales", "売上高", "CurrentYearDuration", "当期", "連結", "期間", "JPY", "円", "45095325000000"],
        ["jpcrp_cor:OperatingIncome", "営業利益", "CurrentYearDuration", "当期", "連結", "期間", "JPY", "円", "5352934000000"],
        ["jpcrp_cor:NetSalesPrior", "前期売上高", "PriorYearDuration", "前期", "連結", "期間", "JPY", "円", "37154298000000"],
    ]
    text = "\r\n".join("\t".join(r) for r in rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("XBRL_TO_CSV/jpcrp.csv", text.encode("utf-16"))
    return buf.getvalue()


CSV_ZIP = _make_csv_zip()


def edinet_transport(url, params, headers, timeout):
    assert params and params.get("Subscription-Key") == "k"
    if url.endswith("documents.json"):
        return FakeResponse(200, DOC_LIST)
    if "/documents/S100ABCD" in url:
        return FakeResponse(200, content=CSV_ZIP)
    return FakeResponse(404, None)


def make():
    http = HttpClient("ua", rate_limit_per_sec=0, transport=edinet_transport)
    return EdinetProvider(http, api_key="k", lookback_days=2)


def test_edinet_requires_key():
    http = HttpClient("ua", rate_limit_per_sec=0, transport=edinet_transport)
    with pytest.raises(RuntimeError):
        EdinetProvider(http, api_key=None).search("トヨタ")


def test_edinet_search_by_name():
    res = make().search("トヨタ", mode="company")
    assert len(res) == 1
    assert res[0].cik == "E12345"
    assert res[0].extra["doc_id"] == "S100ABCD"
    assert res[0].country == "Japan"


def test_edinet_search_by_code():
    res = make().search("7203", mode="ticker")
    assert res and res[0].cik == "E12345"


def test_edinet_fetch_parses_all_rows_and_periods():
    prov = make()
    company = prov.search("トヨタ")[0]
    data = prov.fetch_financials(company)
    labels = {f.label for f in data.facts}
    # 全行を取り込む (前期行も含む)
    assert {"売上高", "営業利益", "前期売上高"} <= labels
    rev = next(f for f in data.facts if f.label == "売上高")
    assert rev.value == 45095325000000.0
    assert rev.fy == 2024 and rev.fp == "当期"
    # 前期行は fy が 1 年前
    prior = next(f for f in data.facts if f.label == "前期売上高")
    assert prior.fp == "前期" and prior.fy == 2023
    assert all(f.dimension is None for f in data.facts)


def _segment_csv_zip() -> bytes:
    header = ["要素ID", "項目名", "コンテキストID", "相対年度", "連結・個別", "期間・時点", "ユニットID", "単位", "値"]
    rows = [
        header,
        # 連結合計
        ["jpcrp_cor:NetSales", "売上高", "CurrentYearDuration", "当期", "連結", "期間", "JPY", "円", "13000000000000"],
        # 事業別セグメント
        ["jpcrp_cor:NetSales", "売上高", "CurrentYearDuration_ImagingReportableSegmentsMember", "当期", "連結", "期間", "JPY", "円", "3000000000000"],
        ["jpcrp_cor:NetSales", "売上高", "CurrentYearDuration_MedicalReportableSegmentsMember", "当期", "連結", "期間", "JPY", "円", "5000000000000"],
        # 個別 (除外されるべき)
        ["jpcrp_cor:NetSales", "売上高", "CurrentYearDuration_NonConsolidatedMember", "当期", "個別", "期間", "JPY", "円", "999"],
    ]
    text = "\r\n".join("\t".join(r) for r in rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("XBRL_TO_CSV/seg.csv", text.encode("utf-16"))
    return buf.getvalue()


def test_edinet_segment_extraction():
    seg_zip = _segment_csv_zip()

    def transport(url, params, headers, timeout):
        if url.endswith("documents.json"):
            return FakeResponse(200, DOC_LIST)
        if "/documents/S100ABCD" in url:
            return FakeResponse(200, content=seg_zip)
        return FakeResponse(404, None)

    http = HttpClient("ua", rate_limit_per_sec=0, transport=transport)
    prov = EdinetProvider(http, api_key="k", lookback_days=1)
    company = prov.search("トヨタ")[0]
    data = prov.fetch_financials(company)

    # 全 4 行を取り込む (連結合計 + セグメント2 + 個別)
    assert len(data.facts) == 4
    segments = [f for f in data.facts if f.dimension]
    seg_names = {f.dimension for f in segments}
    assert seg_names == {"ImagingReportableSegmentsMember", "MedicalReportableSegmentsMember"}
    # 連結合計 (dimension None かつ 連結)
    consolidated = next(f for f in data.facts if f.dimension is None and f.consolidation == "連結")
    assert consolidated.value == 13000000000000.0
    # 個別行も構造化して保持し、連結区分で判別できる
    nonconsol = next(f for f in data.facts if f.consolidation == "個別")
    assert nonconsol.value == 999.0 and nonconsol.dimension is None
