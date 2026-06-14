"""SQLAlchemy ORM モデル.

SQLAlchemy を用いることで SQLite / PostgreSQL / MySQL / SQL Server を
接続 URL の差し替えだけで切り替えられる (IR_DATA_DATABASE_URL)。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("source", "cik", name="uq_company_source_cik"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    cik: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(512))
    ticker: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    exchange: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sic: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sic_description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    country: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fiscal_year_end: Mapped[str | None] = mapped_column(String(8), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    facts: Mapped[list["FinancialRecord"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class FinancialRecord(Base):
    __tablename__ = "financial_records"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "concept", "unit", "fy", "period_end",
            "dimension", "consolidation", "context_id",
            name="uq_fact",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    concept: Mapped[str] = mapped_column(String(256), index=True)
    label: Mapped[str] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    fy: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    fp: Mapped[str | None] = mapped_column(String(16), nullable=True)
    period_start: Mapped[str | None] = mapped_column(String(16), nullable=True)
    period_end: Mapped[str | None] = mapped_column(String(16), nullable=True)
    form: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filed: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 事業別/地域別セグメント (XBRL ディメンション)。NULL = 連結合計。
    dimension: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    consolidation: Mapped[str | None] = mapped_column(String(16), nullable=True)
    context_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source: Mapped[str] = mapped_column(String(32))

    company: Mapped["Company"] = relationship(back_populates="facts")


class SearchRun(Base):
    """検索実行の記録 (監査・再現性のため)."""

    __tablename__ = "search_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    queries: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(32))
    companies_found: Mapped[int] = mapped_column(Integer, default=0)
    facts_stored: Mapped[int] = mapped_column(Integer, default=0)
