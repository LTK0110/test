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

開発ブランチ: `claude/ir-financial-data-api-kjjxo4`（このブランチで作業・push）。

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
api.gleif.org
```

加えて環境変数: `EDINET_API_KEY`(無料登録), `COMPANIES_HOUSE_API_KEY`(無料),
`IR_DATA_USER_AGENT`(SEC 用, 連絡先メール付き)。
**設定は新セッションからのみ有効**（稼働中セッションには反映されない）。

## 動作確認

```bash
pip install -r requirements.txt
python -m pytest -q          # 22 件パス (ネットワーク不要)
python examples/edinet_canon_sony_demo.py   # デモ: Excel/MD/SQLite 生成
```

実データ実行 (egress 許可 + キー設定済みの環境で):
```bash
ir-data --provider edinet --excel jp.xlsx --markdown jp.md "キヤノン" "ソニー"
ir-data --provider sec_edgar --markdown us.md AAPL MSFT
ir-data --provider all "Apple"     # 米+日+英+EU 同時
```

## 次の TODO（未着手・ユーザーと相談中）

0. **【決定・最優先】EDINET DB の MCP 接続で日本データ取得**（2026-06-14 合意）
   - 方針: 公式 EDINET 直結に苦戦中（egress 許可が新セッションからしか効かない）。
     代替として **EDINET DB (edinetdb.jp)** の **MCP コネクタ**を使う。
   - EDINET DB は金融庁 EDINET を名寄せ・構造化した**第三者アグリゲータ**（一次情報そのもの
     ではない点に留意）。無料 API/MCP、無料枠は 1 日上限あり。
   - **MCP コネクタ通信は Anthropic 経由 → egress 許可リスト不要**（これが採用理由＝最速）。
   - ユーザー作業: edinetdb.jp で API キー取得 → MCP コネクタを Claude に登録 → 有効化した
     新セッション開始。コネクタ登録はコンテナ内からは不可。
   - 接続後の自分の作業: `mcp__*edinet*` ツールでキヤノン(7203でなく証券7751=キヤノン,
     ソニーG=6758)等を取得 → **取得結果を既存パイプラインへ流し込むアダプタ**を書き、
     `export_to_excel` / `export_to_markdown` / `Repository.store` で構造化出力する。
     （MCP の戻り値 → `CompanyInfo`/`FinancialFact` へ変換する薄い変換層を追加）
1. **実データでキヤノン・ソニー取得** — 上記 MCP 経由、または egress 許可済み環境で公式直結。
   EDINET コード: キヤノン=E01735(証券7751), ソニーグループ=E01777(証券6758)。
2. **セグメント名の日本語化** — 現状 `dimension` は生の XBRL member 名
   (`ImagingReportableSegmentsMember` 等)。書類のラベルリンク (定義) を解析して
   「イメージング」等の和名に変換する。
3. **英国 Companies House の数値財務** — 現状はメタ＋提出履歴のみ。会計報告の
   **iXBRL を解析**して数値を抽出する (companies_house.py の fetch_financials 拡張)。
4. (任意) 地域別セグメント、EDINET の四半期/半期 (docTypeCode 140/160) 対応。

## 作業ルール

- 変更は必ずテストを通す (`python -m pytest -q`)。
- コミットは説明的に。push は `git push -u origin claude/ir-financial-data-api-kjjxo4`。
- PR はユーザーが明示的に依頼した場合のみ作成。
- 生成物 (`*.db`, `*.xlsx`) は `.gitignore` 済み。`examples/canon_sony_demo.md` はコミット対象。
