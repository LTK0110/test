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
                "value_text": f.value_text,
                "fy": f.fy,
                "fp": f.fp,
                "period_end": f.period_end,
                "segment": f.dimension,  # None=連結合計、値あり=事業別/地域別 (英語ID)
                "segment_label": f.dimension_label,  # セグメントの和名 (あれば)
                "consolidation": f.consolidation,
                "context_id": f.context_id,
                "form": f.form,
                "filed": f.filed,
                "source": f.source,
            })
    return pd.DataFrame(rows)


def _pivot_frame(facts: pd.DataFrame) -> pd.DataFrame:
    """主要指標 × 年度のピボット (連結合計のみ、概観用)."""
    if facts.empty or "value" not in facts:
        return pd.DataFrame()
    # 連結合計のみ: セグメント内訳と個別 (非連結) と非数値を除外
    consolidated = facts[facts["segment"].isna() & (facts["consolidation"] != "個別") & facts["value"].notna()]
    if consolidated.empty:
        return pd.DataFrame()
    pivot = consolidated.pivot_table(
        index=["name", "label", "unit"],
        columns="fy",
        values="value",
        aggfunc="last",
    )
    return pivot.reset_index()


def _segments_frame(facts: pd.DataFrame) -> pd.DataFrame:
    """事業別/地域別セグメント × 指標のピボット (セグメント行のみ)."""
    if facts.empty:
        return pd.DataFrame()
    seg = facts[facts["segment"].notna() & facts["value"].notna()].copy()
    if seg.empty:
        return pd.DataFrame()
    # 和名があれば表示に使う (無い member は英語 ID をそのまま)。
    label_col = seg["segment_label"] if "segment_label" in seg else None
    seg["segment_jp"] = label_col.fillna(seg["segment"]) if label_col is not None else seg["segment"]
    pivot = seg.pivot_table(
        index=["name", "fy", "segment_jp", "segment"],
        columns="label",
        values="value",
        aggfunc="last",
    )
    return pivot.reset_index()


def export_to_excel(results: List[CompanyData], path: str) -> str:
    """企業一覧・財務明細・連結サマリ・事業別の 4 シート構成で Excel を書き出す."""
    companies = _companies_frame(results)
    facts = _facts_frame(results)
    pivot = _pivot_frame(facts)
    segments = _segments_frame(facts)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        (companies if not companies.empty else pd.DataFrame([{"info": "no companies"}])).to_excel(
            writer, sheet_name="Companies", index=False
        )
        (facts if not facts.empty else pd.DataFrame([{"info": "no facts"}])).to_excel(
            writer, sheet_name="Financials", index=False
        )
        if not pivot.empty:
            pivot.to_excel(writer, sheet_name="Summary", index=False)
        if not segments.empty:
            segments.to_excel(writer, sheet_name="Segments", index=False)
    return path
