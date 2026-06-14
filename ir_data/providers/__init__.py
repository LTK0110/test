"""データプロバイダ群."""

from __future__ import annotations

from typing import Dict, Optional

from ..config import Config
from ..http_client import HttpClient
from .base import FinancialDataProvider
from .companies_house import CompaniesHouseProvider
from .edinet import EdinetProvider
from .gleif import GleifProvider
from .sec_edgar import SecEdgarProvider


def build_providers(
    config: Config, http: HttpClient, country: Optional[str] = None
) -> Dict[str, FinancialDataProvider]:
    """利用可能なプロバイダを名前→インスタンスで返す.

    - sec_edgar       米国 (無料・キー不要)
    - edinet          日本 (無料キー必須: EDINET_API_KEY)
    - companies_house 英国 (無料キー必須: COMPANIES_HOUSE_API_KEY)
    - gleif           EU/グローバルのエンティティ情報 (無料・キー不要)
    """
    return {
        "sec_edgar": SecEdgarProvider(http),
        "edinet": EdinetProvider(http, config.edinet_api_key, config.edinet_lookback_days),
        "companies_house": CompaniesHouseProvider(http, config.companies_house_api_key),
        "gleif": GleifProvider(http, country=country),
    }


# 地域 → 既定プロバイダの対応 (利便のため)。
REGION_PROVIDERS = {
    "us": "sec_edgar",
    "jp": "edinet",
    "uk": "companies_house",
    "eu": "gleif",
}


__all__ = [
    "FinancialDataProvider",
    "SecEdgarProvider",
    "EdinetProvider",
    "CompaniesHouseProvider",
    "GleifProvider",
    "build_providers",
    "REGION_PROVIDERS",
]
