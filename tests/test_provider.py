"""SEC EDGAR プロバイダの単体テスト (ネットワーク無し)."""

from __future__ import annotations

from ir_data.providers.sec_edgar import SecEdgarProvider, pad_cik


def test_pad_cik():
    assert pad_cik(320193) == "0000320193"
    assert pad_cik("CIK0000320193") == "0000320193"
    assert pad_cik("320193") == "0000320193"


def test_search_ticker(http):
    prov = SecEdgarProvider(http)
    res = prov.search("AAPL", mode="ticker")
    assert len(res) == 1
    assert res[0].cik == "0000320193"
    assert res[0].name == "Apple Inc."


def test_search_company_partial(http):
    prov = SecEdgarProvider(http)
    res = prov.search("microsoft", mode="company")
    assert any(r.ticker == "MSFT" for r in res)


def test_search_fulltext_keyword(http):
    prov = SecEdgarProvider(http)
    res = prov.search("artificial intelligence", mode="technology", limit=5)
    ciks = {r.cik for r in res}
    assert "0000320193" in ciks and "0000789019" in ciks


def test_fetch_financials_captures_all_periods(http):
    prov = SecEdgarProvider(http)
    company = prov.search("AAPL", mode="ticker")[0]
    data = prov.fetch_financials(company, concepts=["Revenues", "NetIncomeLoss"])
    # 全期間を取り込む (四半期 Q1 も含む)
    assert any(f.fp == "Q1" for f in data.facts)
    assert any(f.fp == "FY" for f in data.facts)
    # 概念はタクソノミ接頭辞付きで保持
    concepts = {f.concept for f in data.facts}
    assert concepts == {"us-gaap:Revenues", "us-gaap:NetIncomeLoss"}
    # メタデータが補完される
    assert data.info.sic_description == "Electronic Computers"
    assert data.info.exchange == "Nasdaq"


def test_fetch_financials_all_concepts_when_unfiltered(http):
    prov = SecEdgarProvider(http)
    company = prov.search("AAPL", mode="ticker")[0]
    data = prov.fetch_financials(company)  # concepts 未指定 = 全概念
    assert {"us-gaap:Revenues", "us-gaap:NetIncomeLoss"} <= {f.concept for f in data.facts}


def test_fetch_financials_year_filter(http):
    prov = SecEdgarProvider(http)
    company = prov.search("AAPL", mode="ticker")[0]
    data = prov.fetch_financials(company, concepts=["Revenues"], years=[2022])
    assert {f.fy for f in data.facts} == {2022}
