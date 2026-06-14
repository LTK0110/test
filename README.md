# ir-data

主要国企業の **IR・財務情報** を **公式な一次情報** から取得する Python CLI ツールです。

- **企業 / 業界 / アプリケーション / 技術** で検索
- 複数クエリ・複数企業を **並列処理**
- 結果を **Excel** へ出力
- 任意の **SQL データベース** (既定: SQLite) へ保存

## データソース

無料・API キー不要の **公式一次情報** を優先しています。

| ソース | 内容 | 備考 |
| --- | --- | --- |
| [SEC EDGAR](https://www.sec.gov/edgar) | 米国上場企業の提出書類・XBRL 財務データ・全文検索 | 無料・キー不要 (User-Agent 必須) |

> プロバイダは差し替え可能な設計です (`ir_data/providers/`)。日本の EDINET や
> 欧州各当局、商用 API (Alpha Vantage の無料枠など) を `FinancialDataProvider`
> を実装して追加できます。

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
```

### 主なオプション

| オプション | 説明 |
| --- | --- |
| `--mode` | `company` / `ticker` / `industry` / `application` / `technology` / `keyword` |
| `--limit` | 1 クエリあたりの最大企業数 (既定 20) |
| `--years` | 対象会計年度 (`2021-2023` または `2021,2022`) |
| `--excel` | Excel 出力先 (`.xlsx`) |
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

- `companies` — 企業の基本情報 (CIK / ティッカー / 取引所 / SIC 業種 / 国 / 決算月)
- `financial_records` — 財務数値 (概念 × 会計年度、単位付き)。年次 (10-K) を保存
- `search_runs` — 検索実行の履歴 (監査・再現性)

`(source, cik)` と `(company, concept, unit, fy, period_end)` で **upsert** するため、
再実行しても重複しません。

## Excel 出力

1 ブックに 3 シート:

- **Companies** — 企業一覧 (メタデータ + 取得ファクト数)
- **Financials** — 財務数値の明細 (long 形式)
- **Summary** — 主要指標 × 年度のピボット

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
    ├── base.py       # プロバイダ抽象基底
    └── sec_edgar.py  # SEC EDGAR (無料・公式)
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
