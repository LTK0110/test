# データソース方針 (主要国の公式一次情報)

本ツールは **公式な一次情報 (規制当局/取引所の API)** を最優先する。スクレイピングは
構造変化・規約・安定性の点で一次情報の継続取得に不適なため採用しない。以下は
2026 年 6 月時点での各地域の公式 API 状況と、本ツールでの対応方針。

## 対応マトリクス

| 地域 | プロバイダ | 公式 API | 無料 | キー | 本ツール対応 |
| --- | --- | --- | --- | --- | --- |
| 🇺🇸 米国 | `sec_edgar` | SEC EDGAR (data.sec.gov / efts) | ✅ | 不要 | ✅ 財務(XBRL)・全文検索 |
| 🇯🇵 日本 | `edinet` | EDINET API v2 (金融庁) | ✅ | **要(無料)** | ✅ 有報の CSV(XBRL)解析 |
| 🇬🇧 英国 | `companies_house` | Companies House Public Data API | ✅ | **要(無料)** | ✅ メタ・提出履歴 / ⏳ iXBRL 数値 |
| 🇪🇺 EU | `gleif` | GLEIF LEI API (+各国レジスタ) | ✅ | 不要 | ✅ エンティティ情報 / ⏳ 財務は ESAP 待ち |
| 🌏 東南アジア | — | **公式無料 API なし** | — | — | ❌ 対象外 (下記参照) |

凡例: ✅=対応済 / ⏳=次フェーズ / ❌=非対応

## 各地域の詳細

### 米国 — SEC EDGAR
完全無料・キー不要。`data.sec.gov` の XBRL companyfacts で標準化された財務数値、
`efts.sec.gov` の全文検索で技術・アプリ・業界キーワード検索が可能。連絡先付き
`User-Agent` とレート上限 (約 10 req/s) の遵守が必要。

### 日本 — EDINET API v2 (金融庁)
**EDINET 以外に公式 API は存在しない。** 代替は TDnet 等のスクレイピング(非推奨)か
商用ベンダーのみ。よって EDINET API v2 が事実上唯一の公式手段。無料だが API キー
(サブスクリプションキー) の登録が必要。
- 書類一覧 API は **日付指定** で当日提出分を返す (名称検索は無い) → 本ツールは
  直近 `EDINET_LOOKBACK_DAYS` 日を遡って収集し、`filerName`/`secCode`/`edinetCode`
  で絞り込む。
- 財務数値は書類取得 API (`type=5`, CSV) を解析して抽出する。

### 英国 — Companies House
公式・無料。API キー (無料) を Basic 認証で使用。会社検索・プロファイル(SIC 業種/
所在国/会計基準日)・提出書類履歴を取得。数値財務は会計報告内の **iXBRL** にあり、
数値抽出には iXBRL 解析が必要 (本フェーズはメタデータ+提出履歴まで。一括の
Accounts Data Product による補完も将来検討)。

### EU — 統一 API は未稼働 (ESAP)
EU 統一の **ESAP (European Single Access Point)** は 2027/7 稼働予定、財務データの
公開は 2028/1 から段階的。したがって現時点で EU 横断の公式財務 API は存在しない。
当面の方針:
- `gleif`: GLEIF の無料・キー不要 API で **法人エンティティ情報** (LEI/正式名称/国/
  状態) を取得し、名寄せ・国判定に利用 (財務数値は無し)。
- 各国レジスタ (独 Bundesanzeiger、仏 INPI 等) は API が断片的。需要に応じて
  個別プロバイダとして追加可能 (`FinancialDataProvider` を実装)。
- ESAP 稼働後に統一プロバイダを追加予定。

### 東南アジア — 公式無料 API なし
SGX / IDX / Bursa Malaysia / SET / PSE の各取引所・規制当局には、財務開示を提供する
**公式の公開開発者 API は確認できない** (ASEAN 取引所の連携は ESG データ基盤が中心)。
ACRA(シンガポール) の BizFile は Web 検索のみ。実用的な API 取得は商用ベンダー
(例: Sectors.app=ID/SG/MY、Quantillium=広域) に限られる。本ツールは公式・無料の
方針に基づき、現時点では東南アジアを **対象外** とする。商用 API を許容する場合は
プロバイダ追加で対応可能。

## 新しいプロバイダの追加方法
`ir_data/providers/base.py` の `FinancialDataProvider` を継承し、`name` / `search` /
`fetch_financials` を実装、`ir_data/providers/__init__.py` の `build_providers` に登録
するだけで CLI から利用できる (`--provider <name>`)。

## 出典
- SEC EDGAR: https://www.sec.gov/edgar/sec-api-documentation
- EDINET: https://disclosure2dl.edinet-fsa.go.jp/ (API 仕様書)
- Companies House: https://developer.company-information.service.gov.uk/
- GLEIF API: https://www.gleif.org/en/lei-data/gleif-api
- EU ESAP (2027/7 稼働, 財務 2028/1〜): https://esma.europa.eu/esmas-activities/data/european-single-access-point-esap
