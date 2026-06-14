# ir-data

主要国企業の **IR・財務情報** を **公式な一次情報** から取得する Python CLI ツールです。

- **企業 / 業界 / アプリケーション / 技術** で検索
- 複数クエリ・複数企業を **並列処理**
- 結果を **Excel** へ出力
- 任意の **SQL データベース** (既定: SQLite) へ保存

## データソース

**公式な一次情報 (規制当局/取引所の API)** を最優先します。スクレイピングは
安定性・規約の点で採用しません。詳細は [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md)。

| 地域 | プロバイダ名 | ソース | 無料 | キー |
| --- | --- | --- | --- | --- |
| 🇺🇸 米国 | `sec_edgar` | SEC EDGAR (XBRL 財務・全文検索) | ✅ | 不要 |
| 🇯🇵 日本 | `edinet` | EDINET API v2 (金融庁・有報 CSV/XBRL) | ✅ | 要(無料) |
| 🇬🇧 英国 | `companies_house` | Companies House Public Data API | ✅ | 要(無料) |
| 🇪🇺 EU | `gleif` | GLEIF LEI API (エンティティ情報) | ✅ | 不要 |

- **日本**: EDINET 以外に公式 API は存在しません (代替はスクレイピングか商用)。
  EDINET は名称検索 API が無いため、直近 N 日の書類一覧を遡って絞り込みます。
- **EU**: 統一 API (ESAP) は 2027〜2028 稼働予定。それまでは GLEIF で法人エンティティ
  情報を取得します (財務数値は ESAP 稼働後に対応)。
- **東南アジア**: 公式無料 API が存在しないため現時点では対象外です。

> プロバイダは差し替え可能です (`ir_data/providers/`)。新しい取得元は
> `FinancialDataProvider` を実装し `build_providers` に登録するだけで追加できます。

## セットアップ

```bash
pip install -r requirements.txt        # もしくは: pip install -e .
cp .env.example .env                    # User-Agent と DB 接続先を設定
```

SEC EDGAR は連絡先付きの `User-Agent` を要求します。`.env` に設定してください:

```
IR_DATA_USER_AGENT=MyCompany IR Research you@example.com
```

> ネットワーク制限のある環境では、`www.sec.gov` / `data.sec.gov` /
> `efts.sec.gov` への egress を許可リストに追加する必要があります。

## 使い方

```bash
# 企業/ティッカーで検索 → Excel と SQLite に保存
ir-data --mode ticker --excel out.xlsx AAPL MSFT NVDA

# 技術キーワードで全文検索 → ヒット企業の財務を取得
ir-data --mode technology --limit 10 --excel ai.xlsx "artificial intelligence"

# 業界・アプリケーションで複数同時検索
ir-data --mode industry "semiconductor" "electric vehicle"

# 会計年度で絞り込み
ir-data --mode ticker --years 2021-2023 AAPL

# 日本 (EDINET) で企業名/証券コード検索
ir-data --provider edinet --excel jp.xlsx "トヨタ" "ソニー"

# 英国 (Companies House) で検索
ir-data --provider companies_house --excel uk.xlsx "BP"

# EU 法人エンティティ情報 (GLEIF, ドイツに絞り込み)
ir-data --provider gleif --country DE "Allianz"

# 複数プロバイダ同時 (米+日+英を並列)
ir-data --provider sec_edgar,edinet,companies_house --excel multi.xlsx "AAPL" "トヨタ" "BP"
# あるいは全プロバイダ
ir-data --provider all "Apple"
```

### 主なオプション

| オプション | 説明 |
| --- | --- |
| `--mode` | `company` / `ticker` / `industry` / `application` / `technology` / `keyword` |
| `--limit` | 1 クエリあたりの最大企業数 (既定 20) |
| `--years` | 対象会計年度 (`2021-2023` または `2021,2022`) |
| `--excel` | Excel 出力先 (`.xlsx`) |
| `--markdown` | 全データのまとめ Markdown 出力先 (`.md`) |
| `--provider` | `sec_edgar`/`edinet`/`companies_house`/`gleif`。カンマ区切り or `all` |
| `--country` | 国コードで絞り込み (GLEIF 等。例 `DE`) |
| `--database-url` | 保存先 SQL 接続 URL |
| `--no-store` | DB へ保存しない |
| `--max-workers` | 並列ワーカー数 |
| `-v` | 詳細ログ |

`company`/`ticker` は銘柄一覧で CIK を解決し、`industry`/`application`/`technology`/`keyword`
は提出書類 (10-K) の全文検索でキーワードを含む企業を抽出します。

## 保存先 SQL の切り替え

`SQLAlchemy` を採用しているため、接続 URL の変更だけで DB を切り替えられます
(`IR_DATA_DATABASE_URL` または `--database-url`)。

```
sqlite:///ir_data.db                                          # 既定
postgresql+psycopg2://user:pass@localhost:5432/irdata         # 要 psycopg2-binary
mysql+pymysql://user:pass@localhost:3306/irdata               # 要 PyMySQL
mssql+pyodbc://user:pass@host/irdata?driver=ODBC+Driver+18+for+SQL+Server  # 要 pyodbc
```

### テーブル

- `companies` — 企業の基本情報 (識別子 / ティッカー / 取引所 / SIC 業種 / 国 / 決算月)
- `financial_records` — **取得できる全データ点**を構造化して保存:
  - `concept`(要素ID/us-gaapタグ) / `label`(項目名) / `unit`
  - `value`(数値) / `value_text`(テキストブロック等の非数値・叙述情報)
  - `fy` / `fp`(当期・前期 / FY・Q1…) / `period_start` / `period_end`
  - `dimension`(事業別/地域別セグメント。NULL=連結合計) / `consolidation`(連結・個別)
  - `context_id`(XBRL コンテキスト) / `form` / `filed` / `source`
- `search_runs` — 検索実行の履歴 (監査・再現性)

**全科目・全期間・連結/個別・セグメント・テキストブロックまで漏れなく取り込みます**
(既定は特定科目への絞り込みをしません)。`(source, cik)` と
`(company, concept, unit, fy, period_end, dimension, consolidation, context_id)`
で **upsert** するため、再実行しても重複しません。

## 出力

### Excel (`--excel`)
1 ブックに 4 シート:

- **Companies** — 企業一覧 (メタデータ + 取得データ点数)
- **Financials** — 全データ点の明細 (long 形式。数値・テキスト・セグメント・連結区分を含む)
- **Summary** — 連結合計の主要指標 × 年度ピボット (セグメント・個別は除外)
- **Segments** — 事業別/地域別セグメント × 指標 × 年度

### Markdown (`--markdown`)
全企業の**全データをまとめた 1 ファイル**。連結財務表・事業別セグメント表に加え、
EDINET のテキストブロック (事業の内容・経営方針等の**叙述情報**) も HTML 除去のうえ
収録するため、「まとめデータの全体」を Markdown で取得できます。

## アーキテクチャ

```
ir_data/
├── cli.py            # コマンドライン
├── pipeline.py       # 検索→並列取得→保存→Excel の統括
├── config.py         # 設定 (環境変数/.env)
├── http_client.py    # レート制限・リトライ付き HTTP
├── concurrency.py    # ThreadPoolExecutor による並列処理
├── excel_export.py   # Excel 出力
├── database.py       # エンジン生成 + upsert
├── models.py         # SQLAlchemy ORM
├── types.py          # ドメインのデータ構造
└── providers/
    ├── base.py            # プロバイダ抽象基底
    ├── sec_edgar.py       # 米国 SEC EDGAR (無料・キー不要)
    ├── edinet.py          # 日本 EDINET v2 (無料キー)
    ├── companies_house.py # 英国 Companies House (無料キー)
    └── gleif.py           # EU/グローバル GLEIF (無料・キー不要)
```

レート制御は `HttpClient` 内でスレッド間共有されるため、ワーカー数を増やしても
SEC のレート上限 (約 10 req/s) を超えません。

## テスト

ネットワーク無しで動作します (SEC レスポンスを模擬)。

```bash
python -m pytest -q
```

## ライセンス / 注意

取得データの利用は各データソースの利用規約に従ってください。SEC EDGAR の
アクセスポリシー (User-Agent・レート制限) を遵守する設計になっています。
