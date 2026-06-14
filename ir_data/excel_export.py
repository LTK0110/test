"""取得結果の Excel 出力."""

from __future__ import annotations

from typing import List

import pandas as pd

from .types import CompanyData


def _companies_frame(results: List[CompanyData]) -> pd.DataFrame:
    rows = []
    for d in results:
        c = d.info
        rows.append({
            "source": c.source,
            "cik": c.cik,
            "ticker": c.ticker,
            "name": c.name,
            "exchange": c.exchange,
            "sic": c.sic,
            "sic_description": c.sic_description,
            "country": c.country,
            "fiscal_year_end": c.fiscal_year_end,
            "num_facts": len(d.facts),
            "error": d.error,
        })
    return pd.DataFrame(rows)


def _facts_frame(results: List[CompanyData]) -> pd.DataFrame:
    rows = []
    for d in results:
        for f in d.facts:
            rows.append({
                "cik": f.cik,
                "ticker": d.info.ticker,
                "name": d.info.name,
                "concept": f.concept,
                "label": f.label,
                "unit": f.unit,
                "value": f.value,
                "fy": f.fy,
                "fp": f.fp,
                "period_end": f.period_end,
                "form": f.form,
                "filed": f.filed,
                "source": f.source,
            })
    return pd.DataFrame(rows)


def _pivot_frame(facts: pd.DataFrame) -> pd.DataFrame:
    """主要指標 × 年度のピボット (概観用)."""
    if facts.empty:
        return pd.DataFrame()
    pivot = facts.pivot_table(
        index=["name", "concept", "unit"],
        columns="fy",
        values="value",
        aggfunc="last",
    )
    return pivot.reset_index()


def export_to_excel(results: List[CompanyData], path: str) -> str:
    """企業一覧・財務明細・ピボットの 3 シート構成で Excel を書き出す."""
    companies = _companies_frame(results)
    facts = _facts_frame(results)
    pivot = _pivot_frame(facts)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        (companies if not companies.empty else pd.DataFrame([{"info": "no companies"}])).to_excel(
            writer, sheet_name="Companies", index=False
        )
        (facts if not facts.empty else pd.DataFrame([{"info": "no facts"}])).to_excel(
            writer, sheet_name="Financials", index=False
        )
        if not pivot.empty:
            pivot.to_excel(writer, sheet_name="Summary", index=False)
    return path
