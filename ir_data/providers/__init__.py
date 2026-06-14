"""データプロバイダ群."""

from __future__ import annotations

from typing import Dict

from ..config import Config
from ..http_client import HttpClient
from .base import FinancialDataProvider
from .sec_edgar import SecEdgarProvider


def build_providers(config: Config, http: HttpClient) -> Dict[str, FinancialDataProvider]:
    """利用可能なプロバイダを名前→インスタンスで返す.

    現状は SEC EDGAR (無料・公式) を提供。EDINET 等を追加する際はここへ登録する。
    """
    providers: Dict[str, FinancialDataProvider] = {
        "sec_edgar": SecEdgarProvider(http),
    }
    return providers


__all__ = ["FinancialDataProvider", "SecEdgarProvider", "build_providers"]
