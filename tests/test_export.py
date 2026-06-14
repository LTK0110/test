"""Excel / Markdown 出力のテスト (連結合計とセグメントの分離など)."""

from __future__ import annotations

import pandas as pd

from ir_data.excel_export import export_to_excel
from ir_data.markdown_export import export_to_markdown
from ir_data.types import CompanyData, CompanyInfo, FinancialFact


def _sample() -> CompanyData:
    info = CompanyInfo(cik="E00000", name="テスト株式会社", ticker="00000", country="Japan", source="edinet")
    facts = [
        FinancialFact("E00000", "NetSales", "売上高", "円", value=1000.0, fy=2024, consolidation="連結"),
        FinancialFact("E00000", "NetSales", "売上高", "円", value=600.0, fy=2024,
                      dimension="AReportableSegmentsMember", consolidation="連結"),
        FinancialFact("E00000", "NetSales", "売上高", "円", value=400.0, fy=2024,
                      dimension="BReportableSegmentsMember", consolidation="連結"),
        FinancialFact("E00000", "NetSales", "売上高", "円", value=9.0, fy=2024, consolidation="個別"),
        FinancialFact("E00000", "DescBlock", "事業の内容", value_text="<p>テスト事業</p>", fy=2024),
    ]
    return CompanyData(info=info, facts=facts)


def test_excel_segments_separate(tmp_path):
    path = str(tmp_path / "o.xlsx")
    export_to_excel([_sample()], path)
    xl = pd.ExcelFile(path)
    assert "Segments" in xl.sheet_names
    summary = pd.read_excel(path, "Summary")
    # Summary は連結合計のみ。セグメント値 (600/400) を含まない
    vals = set(summary[2024].dropna().tolist())
    assert 1000.0 in vals and 600.0 not in vals
    seg = pd.read_excel(path, "Segments")
    assert len(seg) == 2  # 2 セグメント


def test_markdown_full_dump(tmp_path):
    path = str(tmp_path / "o.md")
    export_to_markdown([_sample()], path)
    text = open(path, encoding="utf-8").read()
    # 連結合計表に総売上、セグメント表に内訳、テキスト節に叙述(HTML除去)
    assert "1,000" in text
    assert "AReportableSegmentsMember" in text
    assert "事業の内容" in text and "テスト事業" in text
    assert "<p>" not in text  # HTML タグは除去される
