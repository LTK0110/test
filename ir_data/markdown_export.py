"""取得した全データを Markdown 形式でまとめて出力する.

数値だけでなく、EDINET のテキストブロック (事業の内容・経営方針等の叙述情報) も
含めて「まとめデータの全体」を 1 つの Markdown に書き出す。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .types import CompanyData, FinancialFact

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]*\n[ \t]*")


def _strip_html(text: str) -> str:
    text = _TAG_RE.sub("", text or "")
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return _WS_RE.sub("\n", text).strip()


def _fmt(v: Optional[float]) -> str:
    if v is None:
        return ""
    if v == int(v):
        return f"{int(v):,}"
    return f"{v:,.4g}"


def _md_table(headers: List[str], rows: List[List[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def _numeric_table(facts: List[FinancialFact]) -> str:
    """concept × 年度 の数値表 (連結合計)."""
    years = sorted({f.fy for f in facts if f.fy is not None})
    by_key: Dict[Tuple[str, str, str], Dict[int, float]] = {}
    for f in facts:
        if f.value is None or f.fy is None:
            continue
        k = (f.label, f.concept, f.unit or "")
        by_key.setdefault(k, {})[f.fy] = f.value
    if not by_key:
        return "_(数値データなし)_"
    headers = ["項目", "要素ID", "単位"] + [str(y) for y in years]
    rows = []
    for (label, concept, unit), vals in sorted(by_key.items()):
        rows.append([label, concept, unit] + [_fmt(vals.get(y)) for y in years])
    return _md_table(headers, rows)


def _segment_table(facts: List[FinancialFact]) -> str:
    """セグメント × 項目 の数値表 (事業別/地域別)."""
    seg = [f for f in facts if f.is_segment and f.value is not None]
    if not seg:
        return ""
    labels = sorted({f.label for f in seg})
    by_seg: Dict[Tuple[str, int], Dict[str, float]] = {}
    for f in seg:
        by_seg.setdefault((f.dimension, f.fy), {})[f.label] = f.value
    headers = ["セグメント", "年度"] + labels
    rows = []
    for (dim, fy), vals in sorted(by_seg.items(), key=lambda x: (x[0][0] or "", x[0][1] or 0)):
        rows.append([dim, fy if fy is not None else ""] + [_fmt(vals.get(l)) for l in labels])
    return "## 事業別/地域別セグメント\n\n" + _md_table(headers, rows)


def _text_blocks(facts: List[FinancialFact], max_len: int = 4000) -> str:
    blocks = [f for f in facts if f.is_text]
    if not blocks:
        return ""
    parts = ["## 叙述情報 (テキストブロック)\n"]
    for f in blocks:
        body = _strip_html(f.value_text or "")
        if not body:
            continue
        if len(body) > max_len:
            body = body[:max_len] + f"\n\n_… (省略: 全 {len(body):,} 文字)_"
        parts.append(f"### {f.label}\n\n{body}\n")
    return "\n".join(parts)


def _company_section(data: CompanyData) -> str:
    c = data.info
    meta = [
        f"# {c.name}",
        "",
        f"- ソース: `{c.source}` / 識別子: `{c.cik}`"
        + (f" / ティッカー・証券コード: `{c.ticker}`" if c.ticker else ""),
        f"- 国: {c.country or '-'} / 取引所: {c.exchange or '-'} / 業種(SIC): "
        f"{c.sic or '-'} {c.sic_description or ''}".rstrip(),
        f"- 決算期末: {c.fiscal_year_end or '-'}",
        f"- 取得データ点数: {len(data.facts):,} "
        f"(数値 {len(data.numeric_facts):,} / テキスト {len(data.text_facts):,})",
    ]
    if data.note:
        meta.append(f"- 備考: {data.note}")
    if data.error:
        meta.append(f"- エラー: {data.error}")
    # 連結合計のみ (セグメント内訳と個別は除外) で全社財務表を作る
    consolidated = [f for f in data.numeric_facts if not f.is_segment and f.consolidation != "個別"]
    sections = ["\n".join(meta), "## 財務数値 (連結合計)\n\n" + _numeric_table(consolidated)]
    seg = _segment_table(data.facts)
    if seg:
        sections.append(seg)
    txt = _text_blocks(data.facts)
    if txt:
        sections.append(txt)
    return "\n\n".join(sections)


def export_to_markdown(results: List[CompanyData], path: str) -> str:
    """全企業の全データを 1 つの Markdown にまとめて書き出す."""
    doc = ["# IR・財務データ まとめ", "", f"対象企業: {len(results)} 社", "", "---", ""]
    doc.append("\n\n---\n\n".join(_company_section(d) for d in results))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(doc))
    return path
