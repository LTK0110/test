"""Inline XBRL (iXBRL) パーサ (標準ライブラリのみ).

英国 Companies House の会計報告は XHTML に XBRL を埋め込んだ **iXBRL** 形式で
提出される。ここでは外部依存 (lxml 等) を増やさず ``xml.etree.ElementTree`` で
``ix:nonFraction`` (数値) / ``ix:nonNumeric`` (叙述) を全件抽出し、コンテキスト
(期間・セグメント次元) と単位を解決する。

iXBRL/XHTML は名前付き HTML 実体 (``&nbsp;`` 等) や DOCTYPE を含み、標準 XML
パーサは外部 DTD を読まず未定義実体で失敗する。そのため解析前に名前付き実体を
数値文字参照へ置換し、DOCTYPE を除去する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.entities import html5
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET

# 名前空間の差異 (2008/2013 版など) を吸収するため localname のみで判定する。
_XML_KEEP = {"amp", "lt", "gt", "quot", "apos"}
_ENTITY_RE = re.compile(r"&([a-zA-Z][a-zA-Z0-9]+);")
_DOCTYPE_RE = re.compile(r"<!DOCTYPE[^>]*>", re.IGNORECASE | re.DOTALL)
_NUM_CLEAN_RE = re.compile(r"[\s ,]")


@dataclass
class IxbrlFact:
    """iXBRL から抽出した 1 データ点 (1 要素 × 1 コンテキスト)。"""

    concept: str                      # 接頭辞付きの要素名 (例: uk-bus:TurnoverRevenue)
    label: str                        # 表示用ラベル (localname)
    value: Optional[float] = None     # 数値 (nonFraction)。非数値は None
    value_text: Optional[str] = None  # 叙述テキスト (nonNumeric)
    unit: str = ""                    # 通貨/単位 (例: GBP, shares, pure)
    context_id: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None  # 期間末 or 時点 (instant)
    dimension: Optional[str] = None       # セグメント member (連結/個別の別は除外)
    consolidation: Optional[str] = None   # 連結 / 個別


def _local(tag: str) -> str:
    """``{ns}local`` -> ``local``。名前空間プレフィックスも除去。"""
    if "}" in tag:
        tag = tag.rsplit("}", 1)[1]
    return tag


def _prefixless(qname: str) -> str:
    return qname.rsplit(":", 1)[-1]


def _substitute_entities(text: str) -> str:
    """名前付き HTML 実体を数値文字参照に置換 (XML の基本 5 実体は温存)。"""

    def repl(m: "re.Match[str]") -> str:
        name = m.group(1)
        if name in _XML_KEEP:
            return m.group(0)
        # html5 マップは 'nbsp;' のように末尾セミコロン付きキーも持つ。
        ch = html5.get(name + ";") or html5.get(name)
        if ch is None:
            return m.group(0)
        return "".join(f"&#{ord(c)};" for c in ch)

    return _ENTITY_RE.sub(repl, text)


def _to_number(text: str, scale: Optional[str], sign: Optional[str]) -> Optional[float]:
    """表示文字列を数値化。``scale`` (10 のべき) と ``sign`` を適用する。"""
    raw = (text or "").strip()
    if not raw:
        return None
    negative = False
    if raw.startswith("(") and raw.endswith(")"):  # 会計表記の負数
        negative = True
        raw = raw[1:-1]
    raw = _NUM_CLEAN_RE.sub("", raw)
    if raw in ("", "-", "—", "–"):
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if scale:
        try:
            value *= 10 ** int(scale)
        except ValueError:
            pass
    if sign == "-":
        negative = not negative
    return -value if negative else value


class _Parser:
    def __init__(self, root: ET.Element):
        self.root = root
        self.contexts: Dict[str, Dict[str, Optional[str]]] = {}
        self.units: Dict[str, str] = {}

    def parse(self) -> List[IxbrlFact]:
        for el in self.root.iter():
            local = _local(el.tag)
            if local == "context":
                self._read_context(el)
            elif local == "unit":
                self._read_unit(el)
        facts: List[IxbrlFact] = []
        for el in self.root.iter():
            local = _local(el.tag)
            if local == "nonFraction":
                fact = self._read_non_fraction(el)
                if fact is not None:
                    facts.append(fact)
            elif local == "nonNumeric":
                fact = self._read_non_numeric(el)
                if fact is not None:
                    facts.append(fact)
        return facts

    # ----------------------------------------------------------- contexts
    def _read_context(self, el: ET.Element) -> None:
        cid = el.get("id")
        if not cid:
            return
        start = end = None
        dimension = consolidation = None
        for sub in el.iter():
            sl = _local(sub.tag)
            if sl == "instant":
                end = (sub.text or "").strip() or None
            elif sl == "startDate":
                start = (sub.text or "").strip() or None
            elif sl == "endDate":
                end = (sub.text or "").strip() or None
            elif sl == "explicitMember":
                member = _prefixless((sub.text or "").strip())
                if member.endswith("ConsolidatedMember"):
                    consolidation = "個別" if member.startswith("NonConsolidated") else "連結"
                elif member:
                    dimension = member
        self.contexts[cid] = {
            "start": start,
            "end": end,
            "dimension": dimension,
            "consolidation": consolidation,
        }

    def _read_unit(self, el: ET.Element) -> None:
        uid = el.get("id")
        if not uid:
            return
        measures = [
            _prefixless((m.text or "").strip())
            for m in el.iter()
            if _local(m.tag) == "measure" and (m.text or "").strip()
        ]
        # 分子のみ採用 (iso4217:GBP -> GBP, xbrli:shares -> shares)。
        self.units[uid] = measures[0] if measures else ""

    # -------------------------------------------------------------- facts
    def _context_fields(self, ctx_ref: Optional[str]) -> Dict[str, Optional[str]]:
        return self.contexts.get(ctx_ref or "", {}) if ctx_ref else {}

    def _read_non_fraction(self, el: ET.Element) -> Optional[IxbrlFact]:
        name = el.get("name")
        if not name:
            return None
        if (el.get("{http://www.w3.org/2001/XMLSchema-instance}nil") or "").lower() == "true":
            return None
        text = "".join(el.itertext())
        value = _to_number(text, el.get("scale"), el.get("sign"))
        ctx = self._context_fields(el.get("contextRef"))
        return IxbrlFact(
            concept=name,
            label=_prefixless(name),
            value=value,
            unit=self.units.get(el.get("unitRef") or "", ""),
            context_id=el.get("contextRef"),
            period_start=ctx.get("start"),
            period_end=ctx.get("end"),
            dimension=ctx.get("dimension"),
            consolidation=ctx.get("consolidation"),
        )

    def _read_non_numeric(self, el: ET.Element) -> Optional[IxbrlFact]:
        name = el.get("name")
        if not name:
            return None
        text = " ".join("".join(el.itertext()).split()).strip()
        if not text:
            return None
        ctx = self._context_fields(el.get("contextRef"))
        return IxbrlFact(
            concept=name,
            label=_prefixless(name),
            value_text=text,
            context_id=el.get("contextRef"),
            period_start=ctx.get("start"),
            period_end=ctx.get("end"),
            dimension=ctx.get("dimension"),
            consolidation=ctx.get("consolidation"),
        )


def parse_ixbrl(content) -> List[IxbrlFact]:
    """iXBRL (XHTML) の bytes/str から全ファクトを抽出する。

    解析不能な場合は空リストを返す (呼び出し側でメタデータのみへフォールバック)。
    """
    if isinstance(content, bytes):
        text = content.decode("utf-8", errors="replace")
    else:
        text = content or ""
    if not text.strip():
        return []
    text = _DOCTYPE_RE.sub("", text)
    text = _substitute_entities(text)
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    return _Parser(root).parse()
