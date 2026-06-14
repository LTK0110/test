"""概念ラベル整形の単体テスト."""

from __future__ import annotations

from ir_data.concept_labels import concept_label, humanize


def test_humanize_camel_case():
    assert humanize("NetCurrentAssetsLiabilities") == "Net Current Assets Liabilities"
    assert humanize("CashBankOnHand") == "Cash Bank On Hand"
    assert humanize("core:TotalAssetsLessCurrentLiabilities") == "Total Assets Less Current Liabilities"


def test_humanize_acronym_and_digits():
    assert humanize("UKTurnover") == "UK Turnover"
    assert humanize("FRS102") == "FRS 102"


def test_concept_label_known_japanese():
    assert concept_label("core:TurnoverRevenue") == "売上高"
    assert concept_label("CashBankOnHand") == "現金及び預金"
    assert concept_label("core:Equity") == "資本合計"


def test_concept_label_unknown_falls_back_to_english():
    # 辞書未収載は英文整形にフォールバック。
    assert concept_label("core:SomeNovelConceptName") == "Some Novel Concept Name"
