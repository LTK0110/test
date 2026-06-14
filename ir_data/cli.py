"""コマンドラインインタフェース.

例:
  # 企業名/ティッカーで検索し Excel と SQLite に保存
  ir-data --mode ticker --excel out.xlsx AAPL MSFT NVDA

  # 技術キーワードで全文検索し、ヒット企業の財務を取得
  ir-data --mode technology --limit 10 --excel ai.xlsx "artificial intelligence"

  # 業界・アプリケーションで複数同時検索
  ir-data --mode industry "semiconductor" "electric vehicle"
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from .config import Config
from .pipeline import Pipeline
from .types import SEARCH_MODES


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ir-data",
        description="主要国企業の IR・財務情報を公式一次情報から取得し Excel/SQL へ保存する",
    )
    p.add_argument("queries", nargs="+", help="検索語 (企業名/ティッカー/業界/技術キーワード等)。複数指定で並列処理")
    p.add_argument("--mode", choices=SEARCH_MODES, default="company", help="検索モード (既定: company)")
    p.add_argument(
        "--provider",
        default="sec_edgar",
        help="データプロバイダ。カンマ区切り or 'all' 可 "
        "(sec_edgar=米, edinet=日, companies_house=英, gleif=EU/グローバル)",
    )
    p.add_argument("--country", default=None, help="国コードで絞り込み (GLEIF 等。例: DE, FR)")
    p.add_argument("--limit", type=int, default=20, help="1 クエリあたりの最大企業数 (既定: 20)")
    p.add_argument("--years", type=str, default=None, help="対象会計年度 (例: 2021-2023 または 2021,2022)")
    p.add_argument("--excel", type=str, default=None, help="Excel 出力先パス (.xlsx)")
    p.add_argument("--database-url", type=str, default=None, help="保存先 SQL の接続 URL (既定: sqlite:///ir_data.db)")
    p.add_argument("--no-store", action="store_true", help="DB へ保存しない")
    p.add_argument("--max-workers", type=int, default=None, help="並列ワーカー数")
    p.add_argument("-v", "--verbose", action="store_true", help="詳細ログ")
    return p


def parse_years(spec: Optional[str]) -> Optional[List[int]]:
    if not spec:
        return None
    years: List[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            years.extend(range(int(a), int(b) + 1))
        elif part:
            years.append(int(part))
    return years or None


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = Config()
    if args.database_url:
        config.database_url = args.database_url
    if args.max_workers:
        config.max_workers = args.max_workers

    for w in config.validate():
        logging.warning(w)

    pipeline = Pipeline(config, country=args.country)
    try:
        result = pipeline.run(
            queries=args.queries,
            mode=args.mode,
            provider=args.provider,
            limit=args.limit,
            years=parse_years(args.years),
            excel_path=args.excel,
            store=not args.no_store,
        )
    except Exception as exc:  # noqa: BLE001
        logging.error("実行に失敗しました: %s", exc)
        return 1

    print(f"企業数: {len(result.companies)}  保存ファクト数: {result.facts_stored}")
    if result.excel_path:
        print(f"Excel: {result.excel_path}")
    if config.database_url:
        print(f"DB: {config.database_url}")
    n_err = sum(1 for d in result.companies if d.error)
    if n_err:
        print(f"警告: {n_err} 社で取得エラー (詳細は -v ログ)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
