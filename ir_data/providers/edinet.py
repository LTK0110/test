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
        result.facts = facts
        return result

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
                        consolidation=cons or None,
                        context_id=context or None,
                        source=self.name,
                    )
                )
        return facts

    @staticmethod
    def _segment_from_context(context: str) -> Optional[str]:
        """コンテキストID から事業別/地域別セグメントの member を抽出する.

        例: 'CurrentYearDuration_ImagingReportableSegmentsMember' -> その member。
        連結/個別の区分のみ、または member 無し (全社合計) は None を返す。
        """
        if not context or "_" not in context:
            return None
        member = context.split("_", 1)[1]
        if "Member" not in member:
            return None
        if member in ("ConsolidatedMember", "NonConsolidatedMember"):
            return None
        return member

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
