# CLAUDE.md — プロジェクト引き継ぎノート

> 次セッションの自分（および他の開発者）向けの状況把握用ドキュメント。
> まず本ファイルと `README.md` / `docs/DATA_SOURCES.md` を読むこと。

## このプロジェクトは何か

主要国企業の **IR・財務情報を公式な一次情報（規制当局/取引所の API）から取得** する
Python CLI ツール (`ir-data`)。要件:

- **企業 / 業界 / アプリケーション / 技術** で検索
- 複数クエリ・複数企業を **並列処理**
- 取得できる **全データを構造化** して保存（売上だけでなく全科目・全期間・連結/個別・
  事業別セグメント・テキストブロックの叙述情報まで）
- **Excel** 出力（4シート）と **Markdown** 出力（まとめ全体）
- **SQL DB**（既定 SQLite、SQLAlchemy で他 DB へ切替可）へ保存

開発ブランチ: `claude/quirky-hamilton-djscn5`（このブランチで作業・push）。

## 確定済みの方針（ユーザー合意事項）

- データ取得は **公式・無料 API を最優先**。スクレイピングは採用しない。
- 保存先 DB はまず **SQLite**（SQLAlchemy で将来 PostgreSQL 等へ）。
- 実装形態は **Python CLI**。
- **EU**: 統一 API (ESAP) は 2027–2028 稼働のため、当面 GLEIF でエンティティ情報のみ。
- **東南アジア**: 公式無料 API が存在せず現時点は対象外（商用許容なら追加可）。

## アーキテクチャ

```
ir_data/
├── cli.py            # CLI (argparse)。--provider/--mode/--excel/--markdown/--years 等
├── pipeline.py       # 検索→並列取得→DB保存→Excel/MD出力。複数プロバイダ同時対応
├── config.py         # 設定 (環境変数/.env)。concepts 既定 None = 全データ取得
├── http_client.py    # レート制限・リトライ・追加ヘッダ・bytes取得・transport差替(テスト用)
├── concurrency.py    # ThreadPoolExecutor ラッパ
├── excel_export.py   # Companies/Financials/Summary/Segments の4シート
├── markdown_export.py# 連結財務表+事業別+叙述情報(HTML除去) を1MDに
├── database.py       # エンジン生成 + upsert
├── models.py         # SQLAlchemy ORM (companies / financial_records / search_runs)
├── types.py          # CompanyInfo / FinancialFact / CompanyData
└── providers/
    ├── base.py            # 抽象基底 FinancialDataProvider
    ├── sec_edgar.py       # 米国 (無料・キー不要)
    ├── edinet.py          # 日本 EDINET v2 (無料キー必須)
    ├── companies_house.py # 英国 (無料キー)
    └── gleif.py           # EU/グローバル エンティティ (無料・キー不要)
tests/   … 全プロバイダ・パイプライン・出力のモックテスト (ネットワーク不要)
examples/edinet_canon_sony_demo.py … キヤノン/ソニーの実形式デモ (値はサンプル)
```

### データモデルの要点 (`financial_records`)
全データ点を 1 行 = 1 (要素 × コンテキスト) で保持:
`concept`(要素ID/us-gaapタグ), `label`, `unit`, `value`(数値), `value_text`(非数値/叙述),
`fy`, `fp`(当期/前期・FY/Q1…), `period_start/end`, `dimension`(セグメント, NULL=連結合計),
`consolidation`(連結/個別), `context_id`(XBRL), `form`, `filed`, `source`。
upsert キー = `(concept, unit, fy, period_end, dimension, consolidation, context_id)`。

## 重要: 実行環境のネットワーク制限

この Claude Code on the web のサンドボックスは **egress 許可リスト (Network access)** で
外部ホストを制限している。SEC/EDINET 等は既定で**ブロック** (`403 host_not_allowed`)。
ライブ取得には、環境設定 (claude.ai/code の雲アイコン→環境編集) で **Network access =
Custom** にし、以下を **Allowed domains** に追加 + 「Also include default list of common
package managers」にチェック (pip 必須):

```
api.edinet-fsa.go.jp
disclosure2dl.edinet-fsa.go.jp
www.sec.gov
data.sec.gov
efts.sec.gov
api.company-information.service.gov.uk
document-api.company-information.service.gov.uk
api.gleif.org
```

加えて環境変数: `EDINET_API_KEY`(無料登録), `COMPANIES_HOUSE_API_KEY`(無料),
`IR_DATA_USER_AGENT`(SEC 用, 連絡先メール付き)。
**設定は新セッションからのみ有効**（稼働中セッションには反映されない）。

> **Companies House の注意**: 数値財務 (iXBRL) は **Document API**
> (`document-api.company-information.service.gov.uk`) から本文を取得するため、
> 上記ドメインの **両方** を許可する必要がある (公式データ API のドメインだけでは
> 提出履歴までしか取れない)。API キーは Developer Hub
> (https://developer.company-information.service.gov.uk/) でアプリ登録 → **REST**
> キーを発行して取得。認証は Basic のユーザ名にキー (パスワード空)。キー登録時の
> Restricted IPs は空欄推奨 (本サンドボックスの egress IP は固定でないため)。

## 動作確認

```bash
pip install -r requirements.txt
python -m pytest -q          # 29 件パス (ネットワーク不要)
python examples/edinet_canon_sony_demo.py   # デモ: Excel/MD/SQLite 生成
```

実データ実行 (egress 許可 + キー設定済みの環境で):
```bash
ir-data --provider edinet --excel jp.xlsx --markdown jp.md "キヤノン" "ソニー"
ir-data --provider sec_edgar --markdown us.md AAPL MSFT
# 英国 Companies House: 会社名で検索 → 最新 accounts の iXBRL から数値財務を抽出。
# 要 COMPANIES_HOUSE_API_KEY + 上記 2 ドメインの egress 許可。会社番号でも可。
ir-data --provider companies_house --excel uk.xlsx --markdown uk.md "BP"
ir-data --provider all "Apple"     # 米+日+英+EU 同時
```

> Companies House は PDF のみ提出の会社だと iXBRL 数値が取れず、提出件数ファクト
> + 説明的エラーにデグレードする (致命的でない)。large company の方が iXBRL 提出率が高い。

## 進捗 / TODO

### 完了済み（2026-06-14 セッション, branch `claude/quirky-hamilton-djscn5`）
- ✅ **EDINET 公式直結の疎通確認** — `EDINET_API_KEY` + egress 許可済みの新セッションで
  documents.json / 書類CSV(type=5) を取得できることを実証。当初検討した EDINET DB
  (edinetdb.jp) の **MCP 代替案は不要になった**（直結が動くため）。
- ✅ **EDINET の連結/個別・セグメント抽出のバグ修正** — `_consolidation` で
  `NonConsolidatedMember` から個別を判定、`_segment_from_context` で期間・連結区分軸・
  namespace 接頭辞を除去して純粋な member を抽出。
- ✅ **TODO(旧#2) セグメント名の日本語化** — 書類同梱のラベルリンクベース(`_lab.xml`)を
  解析し member の和名を `dimension_label` に付与（英語IDは安定キーとして保持）。
  Excel(`segment_jp`列)/Markdown に和名表示。例: 調味料・食品 / 冷凍食品。
- ✅ **TODO(旧#3) 英国 Companies House の数値財務** — 最新 accounts の `document_metadata`
  → Document API で iXBRL 本文取得 → `parse_ixbrl` で `ix:nonFraction` を文脈(期間)・
  単位(通貨)・scale/sign 反映で抽出。**※ライブ未検証**（要 `COMPANIES_HOUSE_API_KEY`
  + `document-api...` ドメイン egress）。オフラインのモックテストは通過。

### 残り
1. **実データでキヤノン・ソニー取得** — egress 許可済み環境で公式直結（6月下旬に有報提出）。
   EDINET コード: キヤノン=E01735(証券7751), ソニーグループ=E01777(証券6758)。
2. **Companies House のライブ検証** — キー設定済みの新セッションで `"BP"` 等を実取得し、
   iXBRL 数値が正しく出るか確認（PDF のみ提出の会社はデグレードする点に注意）。
3. (任意) 標準タクソノミ member の和名化（基底タクソノミ取得が必要）、和名の
   ` [メンバー]` サフィックス除去などの微調整。
4. (任意) 地域別セグメント、EDINET の四半期/半期 (docTypeCode 140/160) 対応。

## 作業ルール

- 変更は必ずテストを通す (`python -m pytest -q`)。
- コミットは説明的に。push は `git push -u origin claude/quirky-hamilton-djscn5`。
- PR はユーザーが明示的に依頼した場合のみ作成。
- 生成物 (`*.db`, `*.xlsx`) は `.gitignore` 済み。`examples/canon_sony_demo.md` はコミット対象。
