"""EDINET v2 プロバイダ (日本・金融庁の公式・無料キー必須).

日本の有価証券報告書等の公式な一次情報。スクレイピング不要の唯一の公式手段。

エンドポイント (キーは ``Subscription-Key`` クエリ or ``Ocp-Apim-Subscription-Key`` ヘッダ):
  - 書類一覧: https://api.edinet-fsa.go.jp/api/v2/documents.json?date=YYYY-MM-DD&type=2
  - 書類取得: https://api.edinet-fsa.go.jp/api/v2/documents/{docID}?type=5   (CSV の ZIP)

注意: EDINET は名称検索 API を持たないため、直近 N 日分の書類一覧を収集し
``filerName`` / ``secCode`` / ``edinetCode`` で絞り込む。財務数値は書類の CSV
(type=5, XBRL 由来) を解析して抽出する。
"""

from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, timedelta
from typing import Dict, List, Optional

from ..http_client import HttpClient
from ..types import CompanyData, CompanyInfo, FinancialFact
from .base import FinancialDataProvider

DOC_LIST_URL = "https://api.edinet-fsa.go.jp/api/v2/documents.json"
DOC_GET_URL = "https://api.edinet-fsa.go.jp/api/v2/documents/{doc_id}"

# 有価証券報告書 (120) / 四半期 (140) / 半期 (160)。年次のみ既定で対象。
ANNUAL_DOC_TYPES = {"120"}


class EdinetProvider(FinancialDataProvider):
    name = "edinet"

    def __init__(self, http: HttpClient, api_key: Optional[str], lookback_days: int = 60):
        self.http = http
        self.api_key = api_key
        self.lookback_days = lookback_days

    def _params(self, extra: Optional[Dict] = None) -> Dict:
        if not self.api_key:
            raise RuntimeError(
                "EDINET_API_KEY が未設定です。EDINET の API キー (無料登録) を設定してください。"
            )
        params = {"Subscription-Key": self.api_key}
        if extra:
            params.update(extra)
        return params

    # ------------------------------------------------------------------ 検索
    def search(self, query: str, mode: str = "company", limit: int = 20) -> List[CompanyInfo]:
        query = (query or "").strip()
        if not query:
            return []
        q = query
        is_code = mode == "ticker" or query.isdigit()
        found: Dict[str, CompanyInfo] = {}
        today = date.today()
        for offset in range(self.lookback_days):
            day = (today - timedelta(days=offset)).isoformat()
            data = self.http.get_json(DOC_LIST_URL, params=self._params({"date": day, "type": "2"}))
            for doc in (data or {}).get("results", []) or []:
                if str(doc.get("docTypeCode")) not in ANNUAL_DOC_TYPES:
                    continue
                edinet_code = doc.get("edinetCode") or ""
                if edinet_code in found:
                    continue
                sec_code = (doc.get("secCode") or "").rstrip("0") or doc.get("secCode") or ""
                filer = doc.get("filerName") or ""
                desc = doc.get("docDescription") or ""
                if is_code:
                    matched = q in (doc.get("secCode") or "") or q == edinet_code
                else:
                    matched = q in filer or q in desc
                if not matched:
                    continue
                info = CompanyInfo(
                    cik=edinet_code,  # EDINET コードを識別子に
                    name=filer,
                    ticker=(doc.get("secCode") or None),
                    country="Japan",
                    source=self.name,
                )
                info.extra = {
                    "doc_id": doc.get("docID"),
                    "period_end": doc.get("periodEnd"),
                    "jcn": doc.get("JCN"),
                }
                found[edinet_code] = info
                if len(found) >= limit:
                    return list(found.values())
        return list(found.values())

    # ------------------------------------------------------------------ 取得
    def fetch_financials(
        self,
        company: CompanyInfo,
        concepts: Optional[List[str]] = None,
        years: Optional[List[int]] = None,
    ) -> CompanyData:
        result = CompanyData(info=company, facts=[])
        doc_id = (company.extra or {}).get("doc_id")
        if not doc_id:
            result.error = "docID 不明 (search 経由で取得してください)"
            return result
        raw = self.http.get_bytes(DOC_GET_URL.format(doc_id=doc_id), params=self._params({"type": "5"}))
        if not raw:
            result.error = "EDINET 書類 (CSV) を取得できませんでした"
            return result
        period_end = (company.extra or {}).get("period_end")
        fy = int(period_end[:4]) if period_end and period_end[:4].isdigit() else None
        facts = self._parse_csv_zip(raw, company.cik, fy, period_end)
        if years:
            yset = set(years)
            facts = [f for f in facts if f.fy is None or f.fy in yset]
        # セグメント member の和名をラベルリンクベース (書類の XBRL 定義) から付与する。
        if any(f.dimension for f in facts):
            label_map = self._fetch_segment_labels(doc_id)
            if label_map:
                for f in facts:
                    if f.dimension and f.dimension in label_map:
                        f.dimension_label = label_map[f.dimension]
        result.facts = facts
        return result

    # ------------------------------------------------------ ラベルリンクベース
    def _fetch_segment_labels(self, doc_id: str) -> Dict[str, str]:
        """書類本体 (type=1) の ``_lab.xml`` を解析し {member ローカル名: 和名} を返す.

        セグメント等の member 要素は会社拡張タクソノミで定義され、その和名は書類同梱の
        ラベルリンクベースにある。取得・解析に失敗しても致命的でないため空辞書を返す。
        """
        try:
            raw = self.http.get_bytes(
                DOC_GET_URL.format(doc_id=doc_id), params=self._params({"type": "1"})
            )
            if not raw:
                return {}
            zf = zipfile.ZipFile(io.BytesIO(raw))
            labels: Dict[str, str] = {}
            for name in zf.namelist():
                if name.lower().endswith("_lab.xml"):
                    labels.update(self._parse_label_linkbase(zf.read(name)))
            return labels
        except (zipfile.BadZipFile, ET.ParseError, OSError):
            return {}

    # 標準ラベル role を優先 (verboseLabel/totalLabel より素の名称を選ぶ)。
    _STD_LABEL_ROLE = "http://www.xbrl.org/2003/role/label"
    _XLINK = "http://www.w3.org/1999/xlink"
    _XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

    @classmethod
    def _parse_label_linkbase(cls, xml_bytes: bytes) -> Dict[str, str]:
        """``_lab.xml`` を解析し member ローカル名 → 和名 の対応を作る.

        構造: loc(要素→ラベルキー) / labelArc(ラベルキー→リソースキー) /
        label(リソースキー→和名)。member (末尾 ``Member``) のみ対象とする。
        ローカル名は要素IDの最後の ``_`` 以降 (例
        ``...E00436-000_SeasoningsAndFoodsReportableSegmentMember`` →
        ``SeasoningsAndFoodsReportableSegmentMember``) で、``_segment_from_context``
        の出力と一致する。
        """
        root = ET.fromstring(xml_bytes)
        loc: Dict[str, str] = {}        # ラベルキー -> member ローカル名
        arcs: List[tuple] = []          # (from, to)
        res: Dict[str, List[tuple]] = {}  # リソースキー -> [(role, lang, text)]
        href_a = f"{{{cls._XLINK}}}href"
        label_a = f"{{{cls._XLINK}}}label"
        from_a = f"{{{cls._XLINK}}}from"
        to_a = f"{{{cls._XLINK}}}to"
        role_a = f"{{{cls._XLINK}}}role"
        for el in root.iter():
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "loc":
                frag = (el.get(href_a) or "").split("#", 1)
                if len(frag) != 2:
                    continue
                local = frag[1].rsplit("_", 1)[-1]
                if local.endswith("Member"):
                    loc[el.get(label_a)] = local
            elif tag == "labelArc":
                arcs.append((el.get(from_a), el.get(to_a)))
            elif tag == "label":
                res.setdefault(el.get(label_a), []).append(
                    (el.get(role_a) or "", el.get(cls._XML_LANG) or "", (el.text or "").strip())
                )
        result: Dict[str, str] = {}
        for frm, to in arcs:
            local = loc.get(frm)
            if not local:
                continue
            best = cls._pick_label(res.get(to, []))
            if best and local not in result:
                result[local] = best
        return result

    @classmethod
    def _pick_label(cls, candidates: List[tuple]) -> Optional[str]:
        """ラベル候補から和名を選ぶ (日本語・標準 role を優先)."""
        def score(c) -> tuple:
            role, lang, text = c
            return (lang == "ja", role == cls._STD_LABEL_ROLE, bool(text))
        usable = [c for c in candidates if c[2]]
        if not usable:
            return None
        return max(usable, key=score)[2]

    # 相対年度 → 当期からの年差 (fy 算出用)。
    _REL_OFFSET = {"当期": 0, "当期末": 0, "前期": 1, "前期末": 1, "前々期": 2, "前々期末": 2,
                   "前々々期": 3, "1期前": 1, "2期前": 2, "3期前": 3}

    def _parse_csv_zip(self, raw: bytes, cik: str, base_fy, period_end) -> List[FinancialFact]:
        """書類 CSV の **全行** を構造化して取り込む (数値・テキスト・全期間・連結/個別)。"""
        facts: List[FinancialFact] = []
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            return facts
        for name in zf.namelist():
            if not name.lower().endswith(".csv"):
                continue
            text = self._decode(zf.read(name))
            reader = csv.reader(io.StringIO(text), delimiter="\t")
            rows = list(reader)
            if not rows:
                continue
            idx = {h: i for i, h in enumerate(rows[0])}
            ci_eid = idx.get("要素ID", 0)
            ci_item = idx.get("項目名", 1)
            ci_context = idx.get("コンテキストID", 2)
            ci_period = idx.get("相対年度")
            ci_cons = idx.get("連結・個別")
            ci_unit = idx.get("単位", 7)
            ci_val = idx.get("値", 8)
            for row in rows[1:]:
                if len(row) <= ci_val:
                    continue
                concept = row[ci_eid].strip() if ci_eid < len(row) else ""
                item = row[ci_item].strip() if ci_item < len(row) else ""
                if not concept and not item:
                    continue
                context = row[ci_context].strip() if ci_context < len(row) else ""
                rel = row[ci_period].strip() if ci_period is not None and ci_period < len(row) else ""
                cons = row[ci_cons].strip() if ci_cons is not None and ci_cons < len(row) else None
                consolidation = self._consolidation(cons, context)
                unit = row[ci_unit].strip() if ci_unit < len(row) else ""
                raw_val = row[ci_val] if ci_val < len(row) else ""
                value = self._to_float(raw_val)
                fy = base_fy - self._REL_OFFSET.get(rel, 0) if base_fy is not None else None
                facts.append(
                    FinancialFact(
                        cik=cik,
                        concept=concept or item,
                        label=item or concept,
                        unit=unit,
                        value=value,
                        value_text=None if value is not None else (raw_val.strip() or None),
                        fy=fy,
                        fp=rel or None,
                        period_end=period_end if rel in ("当期", "当期末", "") else None,
                        form="有価証券報告書",
                        dimension=self._segment_from_context(context),
                        consolidation=consolidation,
                        context_id=context or None,
                        source=self.name,
                    )
                )
        return facts

    # 要素 namespace 接頭辞 (例: 'jpcrp030000-asr_E00436-000') を除去するための正規表現。
    _NS_PREFIX = re.compile(r"^jp[\w-]+?_E\d+-\d+")

    @staticmethod
    def _consolidation(raw_col: Optional[str], context: str) -> Optional[str]:
        """連結/個別 の区分を決定する.

        EDINET CSV の「連結・個別」列は連結財務諸表(特に IFRS)や DEI/叙述要素では
        ``その他`` になり ``連結`` が付かないことがある。一方、個別(親会社単独)の値は
        列が ``個別`` か、コンテキストに ``NonConsolidatedMember`` 軸を持つ。
        後者を優先して個別を確実に判定し、それ以外は列値を尊重する。
        """
        if context and "NonConsolidatedMember" in context:
            return "個別"
        col = (raw_col or "").strip()
        return col or None

    @classmethod
    def _segment_from_context(cls, context: str) -> Optional[str]:
        """コンテキストID から事業別/地域別セグメントの member を抽出する.

        実データのコンテキストは ``{期間}_[{連結区分軸}_]{member}`` の形を取り、member は
        ``OtherReportableSegmentsMember`` のような裸名のほか
        ``jpcrp030000-asr_E00436-000SeasoningsAndFoodsReportableSegmentMember`` のように
        namespace 接頭辞付きの場合がある。期間トークンと連結区分軸を除き、namespace 接頭辞も
        取り除いた純粋な member を返す。連結/個別の区分のみ、または member 無し
        (全社合計) は None を返す。
        """
        if not context or "_" not in context:
            return None
        body = context.split("_", 1)[1]  # 先頭の期間トークンを除去
        for axis in ("NonConsolidatedMember_", "ConsolidatedMember_"):
            if body.startswith(axis):
                body = body[len(axis):]
                break
        if body in ("NonConsolidatedMember", "ConsolidatedMember"):
            return None
        body = cls._NS_PREFIX.sub("", body)  # namespace 接頭辞を除去
        if "Member" not in body:
            return None
        return body or None

    @staticmethod
    def _decode(data: bytes) -> str:
        for enc in ("utf-16", "utf-16-le", "cp932", "utf-8"):
            try:
                return data.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return data.decode("utf-8", errors="ignore")

    @staticmethod
    def _to_float(raw: str) -> Optional[float]:
        s = (raw or "").strip().replace(",", "").replace("△", "-").replace("－", "")
        if not s or s in ("-",):
            return None
        try:
            return float(s)
        except ValueError:
            return None
