"""キヤノン・ソニーで EDINET 取得〜Excel/DB 保存を実演するデモ.

注意: 本デモの財務数値は **構造確認用のサンプル値** であり実データではない。
ネットワーク制限のためライブの EDINET には接続できないので、EDINET v2 の
実レスポンス形式 (書類一覧 JSON / 書類 CSV の ZIP) を模した fake transport を
注入し、本物のパイプライン (検索→並列取得→セグメント解析→Excel→SQLite) を
そのまま実行する。実データで動かすには egress 許可 + EDINET_API_KEY が必要。

実行: python examples/edinet_canon_sony_demo.py
"""

from __future__ import annotations

import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ir_data.config import Config
from ir_data.database import Repository, create_db_engine
from ir_data.http_client import HttpClient
from ir_data.pipeline import Pipeline


class _Resp:
    def __init__(self, status=200, payload=None, content=b""):
        self.status_code = status
        self._payload = payload
        self.content = content
        self.text = ""

    def json(self):
        return self._payload


# EDINET コード/証券コードは実在のものに合わせている (数値はサンプル)。
DOC_LIST = {
    "metadata": {"resultset": {"count": 2}},
    "results": [
        {"docID": "S100CANON", "edinetCode": "E01735", "secCode": "77510",
         "filerName": "キヤノン株式会社", "docTypeCode": "120",
         "docDescription": "有価証券報告書", "periodEnd": "2024-12-31", "JCN": "4010001008669"},
        {"docID": "S100SONYG", "edinetCode": "E01777", "secCode": "67580",
         "filerName": "ソニーグループ株式会社", "docTypeCode": "120",
         "docDescription": "有価証券報告書", "periodEnd": "2024-03-31", "JCN": "9010001035809"},
    ],
}

_HEADER = ["要素ID", "項目名", "コンテキストID", "相対年度", "連結・個別", "期間・時点", "ユニットID", "単位", "値"]


def _num(eid, item, val, rel="当期", seg=None, cons="連結", unit="円"):
    ctx = ("CurrentYearDuration" if rel == "当期" else "Prior1YearDuration") + (f"_{seg}" if seg else "")
    return [eid, item, ctx, rel, cons, "期間", "JPY" if unit == "円" else unit, unit, str(val)]


def _text(eid, item, body):
    return [eid, item, "FilingDateInstant", "当期", "", "時点", "", "－", body]


def _zip(rows):
    text = "\r\n".join("\t".join(r) for r in [_HEADER] + rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("XBRL_TO_CSV/jpcrp.csv", text.encode("utf-16"))
    return buf.getvalue()


# --- サンプル値 (実データではない。構造確認用) --------------------------------
CANON_CSV = _zip([
    # 連結 主要財務 (当期 + 前期)
    _num("jpcrp_cor:NetSales", "売上高", 4180000000000),
    _num("jpcrp_cor:NetSales", "売上高", 4031414000000, rel="前期"),
    _num("jpcrp_cor:OperatingIncome", "営業利益", 366000000000),
    _num("jpcrp_cor:OperatingIncome", "営業利益", 353278000000, rel="前期"),
    _num("jpcrp_cor:OrdinaryIncome", "経常利益", 372000000000),
    _num("jpcrp_cor:ProfitLoss", "親会社株主に帰属する当期純利益", 290000000000),
    _num("jpcrp_cor:NetAssets", "純資産額", 3650000000000),
    _num("jpcrp_cor:TotalAssets", "総資産額", 5700000000000),
    _num("jpcrp_cor:ResearchAndDevelopmentExpenses", "研究開発費", 330000000000),
    _num("jpcrp_cor:NumberOfEmployees", "従業員数", 178000, unit="名"),
    # 事業別セグメント (売上高)
    _num("jpcrp_cor:NetSales", "売上高", 2380000000000, seg="PrintingReportableSegmentsMember"),
    _num("jpcrp_cor:NetSales", "売上高", 720000000000, seg="ImagingReportableSegmentsMember"),
    _num("jpcrp_cor:NetSales", "売上高", 560000000000, seg="MedicalReportableSegmentsMember"),
    _num("jpcrp_cor:NetSales", "売上高", 350000000000, seg="IndustrialReportableSegmentsMember"),
    # 事業別セグメント (営業利益)
    _num("jpcrp_cor:OperatingIncome", "営業利益", 250000000000, seg="PrintingReportableSegmentsMember"),
    _num("jpcrp_cor:OperatingIncome", "営業利益", 60000000000, seg="ImagingReportableSegmentsMember"),
    # 叙述情報 (テキストブロック)
    _text("jpcrp_cor:DescriptionOfBusinessTextBlock", "事業の内容",
          "<p>当社グループは、キヤノン株式会社および関係会社により構成され、"
          "プリンティング、イメージング、メディカル、インダストリアルの4事業を"
          "報告セグメントとしている。</p>"),
    _text("jpcrp_cor:BusinessPolicyTextBlock", "経営方針・経営環境",
          "<p>長期経営構想のもと、既存事業の強化と新規事業の育成を進める。</p>"),
])

SONY_CSV = _zip([
    _num("jpcrp_cor:NetSales", "売上高", 13000000000000),
    _num("jpcrp_cor:NetSales", "売上高", 11539837000000, rel="前期"),
    _num("jpcrp_cor:OperatingIncome", "営業利益", 1200000000000),
    _num("jpcrp_cor:ProfitLoss", "親会社株主に帰属する当期純利益", 970000000000),
    _num("jpcrp_cor:NetAssets", "純資産額", 7300000000000),
    _num("jpcrp_cor:TotalAssets", "総資産額", 34000000000000),
    _num("jpcrp_cor:NumberOfEmployees", "従業員数", 113000, unit="名"),
    _num("jpcrp_cor:NetSales", "売上高", 4260000000000, seg="GameAndNetworkServicesReportableSegmentsMember"),
    _num("jpcrp_cor:NetSales", "売上高", 1620000000000, seg="MusicReportableSegmentsMember"),
    _num("jpcrp_cor:NetSales", "売上高", 1490000000000, seg="PicturesReportableSegmentsMember"),
    _num("jpcrp_cor:NetSales", "売上高", 1660000000000, seg="ImageAndSensingSolutionsReportableSegmentsMember"),
    _num("jpcrp_cor:OperatingIncome", "営業利益", 290000000000, seg="GameAndNetworkServicesReportableSegmentsMember"),
    _num("jpcrp_cor:OperatingIncome", "営業利益", 260000000000, seg="ImageAndSensingSolutionsReportableSegmentsMember"),
    _text("jpcrp_cor:DescriptionOfBusinessTextBlock", "事業の内容",
          "<p>当社グループはゲーム＆ネットワークサービス、音楽、映画、ET&amp;S、"
          "イメージング＆センシング・ソリューション、金融の各分野で事業を展開している。</p>"),
])


def transport(url, params, headers, timeout):
    if url.endswith("documents.json"):
        return _Resp(200, DOC_LIST)
    if "/documents/S100CANON" in url:
        return _Resp(200, content=CANON_CSV)
    if "/documents/S100SONYG" in url:
        return _Resp(200, content=SONY_CSV)
    return _Resp(404, None)


def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    xlsx = os.path.join(out_dir, "canon_sony_demo.xlsx")
    md = os.path.join(out_dir, "canon_sony_demo.md")
    db = f"sqlite:///{os.path.join(out_dir, 'canon_sony_demo.db')}"

    config = Config(user_agent="demo demo@example.com", rate_limit_per_sec=0)
    config.edinet_api_key = "DEMO_KEY"
    config.edinet_lookback_days = 1
    config.database_url = db

    http = HttpClient("demo", rate_limit_per_sec=0, transport=transport)
    repo = Repository(create_db_engine(db))
    pipeline = Pipeline(config, http=http, repository=repo)

    result = pipeline.run(
        queries=["キヤノン", "ソニー"],
        mode="company",
        provider="edinet",
        excel_path=xlsx,
        markdown_path=md,
    )
    print(f"企業数: {result.companies_found}  保存ファクト数: {result.facts_stored}")
    for d in result.companies:
        seg = sum(1 for f in d.facts if f.is_segment)
        txt = len(d.text_facts)
        print(f"  - {d.info.name} (EDINET {d.info.cik}, 証券 {d.info.ticker}): "
              f"全 {len(d.facts)} 点 (数値 {len(d.numeric_facts)} / 事業別 {seg} / テキスト {txt})")
    print(f"Excel:    {xlsx}")
    print(f"Markdown: {md}")
    print(f"DB:       {db}")


if __name__ == "__main__":
    main()
