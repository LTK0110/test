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
    def __init__(
        self,
        config: Config,
        http: Optional[HttpClient] = None,
        repository: Optional[Repository] = None,
        country: Optional[str] = None,
    ):
        self.config = config
        self.http = http or HttpClient(
            user_agent=config.user_agent,
            rate_limit_per_sec=config.rate_limit_per_sec,
            timeout=config.request_timeout,
            max_retries=config.max_retries,
        )
        self.providers = build_providers(config, self.http, country=country)
        self.repository = repository or Repository(create_db_engine(config.database_url))

    def _resolve_providers(self, provider: str):
        """'sec_edgar,edinet' や 'all' を解決してプロバイダ一覧を返す."""
        if provider == "all":
            names = list(self.providers)
        else:
            names = [p.strip() for p in provider.split(",") if p.strip()]
        provs = []
        for n in names:
            if n not in self.providers:
                raise ValueError(f"未知のプロバイダ: {n} (利用可能: {list(self.providers)}, all)")
            provs.append(self.providers[n])
        return provs

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
        provs = self._resolve_providers(provider)

        # 1) 複数クエリ × 複数プロバイダを並列で検索
        logger.info("検索開始: %d クエリ × %d プロバイダ (mode=%s)", len(queries), len(provs), mode)
        tasks = [(p, q) for p in provs for q in queries]
        search_outcomes = run_parallel(
            lambda t: t[0].search(t[1], mode=mode, limit=limit),
            tasks,
            max_workers=self.config.max_workers,
        )
        companies: dict[str, CompanyInfo] = {}
        for (prov, query), infos, err in search_outcomes:
            if err:
                logger.warning("検索失敗 [%s] '%s': %s", prov.name, query, err)
                continue
            for info in infos or []:
                companies.setdefault(info.key(), info)
        logger.info("検索ヒット企業数 (重複排除後): %d", len(companies))

        # 2) 各企業の財務を並列取得 (発行元プロバイダで取得)
        by_name = {p.name: p for p in provs}
        fetch_outcomes = run_parallel(
            lambda info: by_name[info.source].fetch_financials(
                info, concepts=self.config.concepts, years=years
            ),
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
