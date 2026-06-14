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

# 抽出対象の主要勘定 (項目名の部分一致 → 正規化ラベル)。
TARGET_ITEMS = {
    "売上高": "Revenue",
    "営業収益": "Revenue",
    "営業利益": "OperatingIncome",
    "経常利益": "OrdinaryIncome",
    "当期純利益": "NetIncome",
    "親会社株主に帰属する当期純利益": "NetIncome",
    "純資産": "NetAssets",
    "資産合計": "TotalAssets",
    "研究開発費": "ResearchAndDevelopment",
}


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
        if years and fy is not None and fy not in set(years):
            return result
        result.facts = self._parse_csv_zip(raw, company.cik, fy, period_end)
        return result

    def _parse_csv_zip(self, raw: bytes, cik: str, fy, period_end) -> List[FinancialFact]:
        facts: List[FinancialFact] = []
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            return facts
        for name in zf.namelist():
            if not name.lower().endswith(".csv"):
                continue
            data = zf.read(name)
            text = self._decode(data)
            reader = csv.reader(io.StringIO(text), delimiter="\t")
            rows = list(reader)
            if not rows:
                continue
            header = rows[0]
            idx = {h: i for i, h in enumerate(header)}
            ci_item = idx.get("項目名", 1)
            ci_unit = idx.get("単位", 7)
            ci_val = idx.get("値", 8)
            ci_eid = idx.get("要素ID", 0)
            ci_period = idx.get("相対年度")
            ci_context = idx.get("コンテキストID")
            ci_cons = idx.get("連結・個別")
            for row in rows[1:]:
                if len(row) <= max(ci_item, ci_val):
                    continue
                item = row[ci_item].strip()
                label = self._match_item(item)
                if label is None:
                    continue
                if ci_period is not None and ci_period < len(row):
                    if row[ci_period].strip() not in ("当期", "当期末", ""):
                        continue
                # 個別 (非連結) は連結合計と衝突するため除外 (IR は連結が基本)。
                if ci_cons is not None and ci_cons < len(row) and row[ci_cons].strip() == "個別":
                    continue
                value = self._to_float(row[ci_val])
                if value is None:
                    continue
                context = row[ci_context].strip() if ci_context is not None and ci_context < len(row) else ""
                dimension = self._segment_from_context(context)
                facts.append(
                    FinancialFact(
                        cik=cik,
                        concept=row[ci_eid].strip() if ci_eid < len(row) else label,
                        label=item or label,
                        unit=row[ci_unit].strip() if ci_unit < len(row) else "JPY",
                        value=value,
                        fy=fy,
                        fp="FY",
                        period_end=period_end,
                        form="有価証券報告書",
                        dimension=dimension,
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
    def _match_item(item: str) -> Optional[str]:
        for key, label in TARGET_ITEMS.items():
            if key in item:
                return label
        return None

    @staticmethod
    def _to_float(raw: str) -> Optional[float]:
        s = (raw or "").strip().replace(",", "").replace("△", "-").replace("－", "")
        if not s or s in ("-",):
            return None
        try:
            return float(s)
        except ValueError:
            return None
