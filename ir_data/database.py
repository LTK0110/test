"""DB エンジン生成と保存 (upsert) ロジック."""

from __future__ import annotations

from typing import Iterable, List, Tuple

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, Company, FinancialRecord
from .types import CompanyData


def create_db_engine(database_url: str) -> Engine:
    """接続 URL からエンジンを生成しテーブルを作成する."""
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    engine = create_engine(database_url, future=True, connect_args=connect_args)
    Base.metadata.create_all(engine)
    return engine


class Repository:
    """企業・財務データの永続化を担う."""

    def __init__(self, engine: Engine):
        self._engine = engine
        self._Session = sessionmaker(bind=engine, future=True)

    def session(self) -> Session:
        return self._Session()

    def upsert_company(self, session: Session, info) -> Company:
        stmt = select(Company).where(Company.source == info.source, Company.cik == info.cik)
        company = session.scalar(stmt)
        if company is None:
            company = Company(source=info.source, cik=info.cik, name=info.name)
            session.add(company)
        company.name = info.name or company.name
        company.ticker = info.ticker or company.ticker
        company.exchange = info.exchange or company.exchange
        company.sic = info.sic or company.sic
        company.sic_description = info.sic_description or company.sic_description
        company.country = info.country or company.country
        company.fiscal_year_end = info.fiscal_year_end or company.fiscal_year_end
        session.flush()
        return company

    def upsert_facts(self, session: Session, company: Company, facts) -> int:
        def kf(concept, unit, fy, period_end, dimension, consolidation, context_id):
            return (concept, unit, fy, period_end, dimension, consolidation, context_id)

        # 既存ファクトを一意キーで索引化 (期間・セグメント・連結区分・コンテキスト込み)
        existing = {
            kf(f.concept, f.unit, f.fy, f.period_end, f.dimension, f.consolidation, f.context_id): f
            for f in session.scalars(
                select(FinancialRecord).where(FinancialRecord.company_id == company.id)
            )
        }
        count = 0
        for fact in facts:
            k = kf(fact.concept, fact.unit, fact.fy, fact.period_end,
                   fact.dimension, fact.consolidation, fact.context_id)
            rec = existing.get(k)
            if rec is None:
                rec = FinancialRecord(
                    company_id=company.id, concept=fact.concept, unit=fact.unit,
                    fy=fact.fy, period_end=fact.period_end, dimension=fact.dimension,
                    consolidation=fact.consolidation, context_id=fact.context_id,
                )
                session.add(rec)
                existing[k] = rec
            rec.label = fact.label
            rec.value = fact.value
            rec.value_text = fact.value_text
            rec.fp = fact.fp
            rec.period_start = fact.period_start
            rec.form = fact.form
            rec.filed = fact.filed
            rec.source = fact.source
            count += 1
        return count

    def store(self, results: Iterable[CompanyData]) -> Tuple[int, int]:
        """取得結果群を保存し (企業数, ファクト数) を返す."""
        companies = 0
        facts = 0
        with self.session() as session:
            for data in results:
                company = self.upsert_company(session, data.info)
                companies += 1
                facts += self.upsert_facts(session, company, data.facts)
            session.commit()
        return companies, facts
