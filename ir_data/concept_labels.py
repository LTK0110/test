"""XBRL 概念 (要素) の表示ラベル整形.

iXBRL から得られる概念名は ``core:CashBankOnHand`` のような接頭辞付き camelCase
で、そのままでは読みにくい。ここでは

1. 既知の主要概念 (英国 FRC / core タクソノミ) には **和名** を割り当て、
2. 未知の概念は camelCase を英文として **語区切り整形** する。

公式のラベルリンクベースは外部タクソノミにあり iXBRL 本体には埋め込まれない
ため、頻出概念を辞書で補う方針 (網羅でなく実用範囲)。
"""

from __future__ import annotations

import re

# camelCase / 連続大文字 (頭字語) の境界で区切る。
#  "NetCurrentAssetsLiabilities" -> "Net Current Assets Liabilities"
#  "UKTurnover" -> "UK Turnover" / "FRS102" -> "FRS 102"
_SPLIT_RE = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])"          # 小文字/数字 → 大文字
    r"|(?<=[A-Z])(?=[A-Z][a-z])"        # 頭字語 → 通常語 (e.g. UKTurnover)
    r"|(?<=[A-Za-z])(?=[0-9])"          # 文字 → 数字 (e.g. FRS102)
)


def _prefixless(name: str) -> str:
    return (name or "").rsplit(":", 1)[-1]


def humanize(name: str) -> str:
    """接頭辞を除いた localname を英文ラベルへ整形する."""
    local = _prefixless(name)
    if not local:
        return ""
    return _SPLIT_RE.sub(" ", local).strip()


# 主要概念の和名 (localname -> 和名)。英国小規模/マイクロ法人の会計報告で頻出する
# FRC core/bus 概念を中心に整備。未収載は humanize() で英文整形にフォールバック。
CONCEPT_LABELS_JA = {
    # 損益計算書
    "TurnoverRevenue": "売上高",
    "Turnover": "売上高",
    "Revenue": "売上高",
    "CostSales": "売上原価",
    "GrossProfitLoss": "売上総損益",
    "AdministrativeExpenses": "一般管理費",
    "DistributionCosts": "販売費",
    "OperatingProfitLoss": "営業損益",
    "ProfitLossBeforeTax": "税引前損益",
    "ProfitLossOnOrdinaryActivitiesBeforeTax": "税引前損益",
    "TaxTaxCreditOnProfitOrLossOnOrdinaryActivities": "法人税等",
    "TaxExpenseCreditOnProfitOrLossFromOrdinaryActivities": "法人税等",
    "ProfitLoss": "当期純損益",
    "OtherOperatingIncomeFormat1": "その他営業収益",
    "InterestPayableSimilarChargesFinanceCosts": "支払利息等",
    # 貸借対照表 — 資産
    "FixedAssets": "固定資産",
    "IntangibleAssets": "無形固定資産",
    "PropertyPlantEquipment": "有形固定資産",
    "TangibleFixedAssets": "有形固定資産",
    "Investments": "投資",
    "CurrentAssets": "流動資産",
    "Stocks": "棚卸資産",
    "Debtors": "債権 (売掛金等)",
    "TradeDebtorsTradeReceivables": "売上債権",
    "CashBankOnHand": "現金及び預金",
    "CashBankInHand": "現金及び預金",
    "TotalAssetsLessCurrentLiabilities": "総資産 − 流動負債",
    "NetCurrentAssetsLiabilities": "正味流動資産",
    # 貸借対照表 — 負債・資本
    "Creditors": "債務 (買掛金等)",
    "TradeCreditorsTradePayables": "仕入債務",
    "OtherCreditors": "その他債務",
    "TaxationSocialSecurityPayable": "未払税金・社会保険料",
    "AccrualsDeferredIncome": "未払費用・前受収益",
    "Provisions": "引当金",
    "ProvisionsForLiabilitiesCharges": "引当金",
    "NetAssetsLiabilities": "純資産",
    "Equity": "資本合計",
    "ShareCapital": "資本金",
    "SharePremium": "資本準備金",
    "RetainedEarningsAccumulatedLosses": "利益剰余金",
    "CalledUpShareCapital": "払込資本金",
    # その他
    "AverageNumberEmployeesDuringPeriod": "期中平均従業員数",
    "NumberShares": "株式数",
    "DividendsPaid": "配当金",
    "Depreciation": "減価償却費",
}


def concept_label(name: str) -> str:
    """概念名 (接頭辞付き可) から表示ラベルを返す。

    既知概念は和名、未知概念は英文整形 (camelCase 分割) を返す。
    """
    local = _prefixless(name)
    ja = CONCEPT_LABELS_JA.get(local)
    if ja:
        return ja
    return humanize(local)
