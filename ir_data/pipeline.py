"""検索 → 並列取得 → 保存 → Excel 出力 を束ねるパイプライン."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import List, Optional

from .concurrency import run_parallel
from .config import Config
from .database import Repository, create_db_engine
from .excel_export import export_to_excel
from .http_client import HttpClient
from .models import SearchRun
from .providers import build_providers
from .types import CompanyData, CompanyInfo

logger = logging.getLogger("ir_data")


@dataclass
class PipelineResult:
    companies: List[CompanyData]
    companies_found: int
    facts_stored: int
    excel_path: Optional[str]


class Pipeline:
    def __init__(self, config: Config, http: Optional[HttpClient] = None, repository: Optional[Repository] = None):
        self.config = config
        self.http = http or HttpClient(
            user_agent=config.user_agent,
            rate_limit_per_sec=config.rate_limit_per_sec,
            timeout=config.request_timeout,
            max_retries=config.max_retries,
        )
        self.providers = build_providers(config, self.http)
        self.repository = repository or Repository(create_db_engine(config.database_url))

    # ---------------------------------------------------------------- 実行
    def run(
        self,
        queries: List[str],
        mode: str = "company",
        provider: str = "sec_edgar",
        limit: int = 20,
        years: Optional[List[int]] = None,
        excel_path: Optional[str] = None,
        store: bool = True,
    ) -> PipelineResult:
        prov = self.providers.get(provider)
        if prov is None:
            raise ValueError(f"未知のプロバイダ: {provider} (利用可能: {list(self.providers)})")

        # 1) 複数クエリを並列で検索
        logger.info("検索開始: %d 件のクエリ (mode=%s)", len(queries), mode)
        search_outcomes = run_parallel(
            lambda q: prov.search(q, mode=mode, limit=limit),
            queries,
            max_workers=self.config.max_workers,
        )
        companies: dict[str, CompanyInfo] = {}
        for query, infos, err in search_outcomes:
            if err:
                logger.warning("検索失敗 '%s': %s", query, err)
                continue
            for info in infos or []:
                companies.setdefault(info.key(), info)
        logger.info("検索ヒット企業数 (重複排除後): %d", len(companies))

        # 2) 各企業の財務を並列取得
        fetch_outcomes = run_parallel(
            lambda info: prov.fetch_financials(info, concepts=self.config.concepts, years=years),
            list(companies.values()),
            max_workers=self.config.max_workers,
        )
        results: List[CompanyData] = []
        for info, data, err in fetch_outcomes:
            if err:
                logger.warning("取得失敗 '%s': %s", info.name, err)
                results.append(CompanyData(info=info, facts=[], error=str(err)))
            elif data is not None:
                results.append(data)
        results.sort(key=lambda d: d.info.name or "")

        # 3) DB 保存
        companies_found = len(results)
        facts_stored = 0
        if store:
            companies_found, facts_stored = self.repository.store(results)
            self._record_run(queries, mode, companies_found, facts_stored)
            logger.info("DB 保存: 企業 %d 社 / ファクト %d 件", companies_found, facts_stored)

        # 4) Excel 出力
        out_path = None
        if excel_path:
            out_path = export_to_excel(results, excel_path)
            logger.info("Excel 出力: %s", out_path)

        return PipelineResult(
            companies=results,
            companies_found=companies_found,
            facts_stored=facts_stored,
            excel_path=out_path,
        )

    def _record_run(self, queries, mode, companies_found, facts_stored) -> None:
        with self.repository.session() as session:
            session.add(SearchRun(
                queries=json.dumps(queries, ensure_ascii=False),
                mode=mode,
                companies_found=companies_found,
                facts_stored=facts_stored,
            ))
            session.commit()
