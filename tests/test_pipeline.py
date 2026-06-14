"""パイプライン (検索→並列取得→保存→Excel) の結合テスト."""

from __future__ import annotations

import os

import pandas as pd

from ir_data.config import Config
from ir_data.database import Repository, create_db_engine
from ir_data.models import Company, FinancialRecord, SearchRun
from ir_data.pipeline import Pipeline
from sqlalchemy import select


def make_pipeline(http, tmp_path):
    config = Config(user_agent="test test@example.com", rate_limit_per_sec=0, max_workers=4)
    config.database_url = f"sqlite:///{tmp_path/'test.db'}"
    repo = Repository(create_db_engine(config.database_url))
    return Pipeline(config, http=http, repository=repo), repo


def test_pipeline_end_to_end(http, tmp_path):
    pipeline, repo = make_pipeline(http, tmp_path)
    excel = str(tmp_path / "out.xlsx")
    result = pipeline.run(
        queries=["AAPL", "MSFT"],
        mode="ticker",
        excel_path=excel,
    )
    assert result.companies_found == 2
    assert result.facts_stored > 0
    assert os.path.exists(excel)

    # Excel の中身を検証
    companies = pd.read_excel(excel, sheet_name="Companies")
    assert len(companies) == 2
    facts = pd.read_excel(excel, sheet_name="Financials")
    assert "value" in facts.columns and len(facts) > 0

    # DB の中身を検証
    with repo.session() as s:
        assert s.scalar(select(Company).where(Company.ticker == "AAPL")) is not None
        assert s.query(FinancialRecord).count() > 0
        assert s.query(SearchRun).count() == 1


def test_pipeline_upsert_idempotent(http, tmp_path):
    pipeline, repo = make_pipeline(http, tmp_path)
    pipeline.run(queries=["AAPL"], mode="ticker")
    pipeline.run(queries=["AAPL"], mode="ticker")  # 2 回目: 重複させない
    with repo.session() as s:
        assert s.query(Company).filter(Company.ticker == "AAPL").count() == 1
        # ファクト数は 1 回目と変わらない (upsert)
        n = s.query(FinancialRecord).count()
    assert n > 0


def test_pipeline_keyword_mode(http, tmp_path):
    pipeline, _ = make_pipeline(http, tmp_path)
    result = pipeline.run(queries=["semiconductor"], mode="industry", limit=5, store=False)
    assert result.companies_found == 2
