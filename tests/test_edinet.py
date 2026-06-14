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


def test_segment_from_context_real_patterns():
    """実データのコンテキスト形 (namespace 接頭辞付き・連結区分軸混在) を正しく解す."""
    f = EdinetProvider._segment_from_context
    # namespace 接頭辞付き member -> 接頭辞を除去
    assert (
        f("CurrentYearDuration_jpcrp030000-asr_E00436-000SeasoningsAndFoodsReportableSegmentMember")
        == "SeasoningsAndFoodsReportableSegmentMember"
    )
    # 裸 member
    assert f("CurrentYearDuration_OtherReportableSegmentsMember") == "OtherReportableSegmentsMember"
    # 個別軸 + namespace 接頭辞付き member -> 連結区分軸も接頭辞も除去
    assert (
        f("CurrentYearInstant_NonConsolidatedMember_jpcrp030000-asr_E00436-000FrozenFoodsReportableSegmentMember")
        == "FrozenFoodsReportableSegmentMember"
    )
    # 連結区分軸のみ (member 無し) -> None
    assert f("CurrentYearInstant_NonConsolidatedMember") is None
    # member 無し (全社合計) -> None
    assert f("CurrentYearDuration") is None


LAB_XML = """<?xml version="1.0" encoding="utf-8"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink">
  <link:labelLink>
    <link:loc xlink:type="locator"
        xlink:href="doc.xsd#jpcrp030000-asr_E00436-000_SeasoningsAndFoodsReportableSegmentMember"
        xlink:label="seg1"/>
    <link:labelArc xlink:type="arc" xlink:from="seg1" xlink:to="lab_seg1_std"/>
    <link:labelArc xlink:type="arc" xlink:from="seg1" xlink:to="lab_seg1_en"/>
    <link:label xlink:type="resource" xlink:label="lab_seg1_en" xml:lang="en"
        xlink:role="http://www.xbrl.org/2003/role/label">Seasonings and Foods</link:label>
    <link:label xlink:type="resource" xlink:label="lab_seg1_std" xml:lang="ja"
        xlink:role="http://www.xbrl.org/2003/role/label">調味料・食品</link:label>
    <!-- member ではない通常要素は対象外 -->
    <link:loc xlink:type="locator" xlink:href="doc.xsd#jpcrp_cor_NetSales" xlink:label="ns"/>
    <link:labelArc xlink:type="arc" xlink:from="ns" xlink:to="lab_ns"/>
    <link:label xlink:type="resource" xlink:label="lab_ns" xml:lang="ja"
        xlink:role="http://www.xbrl.org/2003/role/label">売上高</link:label>
  </link:labelLink>
</link:linkbase>
"""


def test_parse_label_linkbase():
    m = EdinetProvider._parse_label_linkbase(LAB_XML.encode("utf-8"))
    # member のみ・日本語の標準ラベルを採用 (英語より優先)
    assert m == {"SeasoningsAndFoodsReportableSegmentMember": "調味料・食品"}


def _seasonings_csv_zip() -> bytes:
    header = ["要素ID", "項目名", "コンテキストID", "相対年度", "連結・個別", "期間・時点", "ユニットID", "単位", "値"]
    rows = [
        header,
        ["jpcrp_cor:NetSales", "売上高", "CurrentYearDuration", "当期", "連結", "期間", "JPY", "円", "13000000000000"],
        # 接頭辞付き member のセグメント行 (実データ形)
        ["jpcrp_cor:NetSales", "売上高",
         "CurrentYearDuration_jpcrp030000-asr_E00436-000SeasoningsAndFoodsReportableSegmentMember",
         "当期", "連結", "期間", "JPY", "円", "5000000000000"],
        # ラベルに無い member (和名フォールバック確認用)
        ["jpcrp_cor:NetSales", "売上高", "CurrentYearDuration_OtherReportableSegmentsMember",
         "当期", "連結", "期間", "JPY", "円", "2000000000000"],
    ]
    text = "\r\n".join("\t".join(r) for r in rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("XBRL_TO_CSV/seg.csv", text.encode("utf-16"))
    return buf.getvalue()


def test_fetch_financials_applies_segment_labels():
    """セグメント行に和名 (dimension_label) が付与される (type=1 を解析)."""
    seg_zip = _seasonings_csv_zip()
    lab_zip_buf = io.BytesIO()
    with zipfile.ZipFile(lab_zip_buf, "w") as zf:
        zf.writestr("XBRL/PublicDoc/doc_lab.xml", LAB_XML.encode("utf-8"))
    lab_zip = lab_zip_buf.getvalue()

    def transport(url, params, headers, timeout):
        if url.endswith("documents.json"):
            return FakeResponse(200, DOC_LIST)
        if "/documents/S100ABCD" in url:
            return FakeResponse(200, content=lab_zip if params.get("type") == "1" else seg_zip)
        return FakeResponse(404, None)

    http = HttpClient("ua", rate_limit_per_sec=0, transport=transport)
    prov = EdinetProvider(http, api_key="k", lookback_days=1)
    company = prov.search("トヨタ")[0]
    data = prov.fetch_financials(company)
    # 接頭辞付き member -> クリーンな dimension + 和名
    seasonings = next(f for f in data.facts if f.dimension == "SeasoningsAndFoodsReportableSegmentMember")
    assert seasonings.dimension_label == "調味料・食品"
    # ラベルに無い member は和名なし (英語 ID フォールバック)
    other = next(f for f in data.facts if f.dimension == "OtherReportableSegmentsMember")
    assert other.dimension_label is None


def test_consolidation_derivation():
    """連結・個別列が 'その他' でもコンテキストの NonConsolidatedMember から個別を判定する."""
    d = EdinetProvider._consolidation
    # 列が 'その他' でも NonConsolidatedMember があれば個別
    assert d("その他", "CurrentYearInstant_NonConsolidatedMember_FooSegmentMember") == "個別"
    # 列値を尊重 (連結合計はマーカー無し)
    assert d("連結", "CurrentYearDuration") == "連結"
    assert d("個別", "CurrentYearDuration") == "個別"
    # IFRS 連結や DEI は 'その他' のまま保持
    assert d("その他", "CurrentYearDuration") == "その他"
    assert d("", "CurrentYearDuration") is None
