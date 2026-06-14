"""iXBRL パーサの単体テスト (ネットワーク無し)."""

from __future__ import annotations

from ir_data.ixbrl import parse_ixbrl

# DOCTYPE / 名前付き実体 (&nbsp;) / 期間・時点・セグメントの各コンテキスト /
# scale・括弧負数・符号を含む現実的な最小 iXBRL。
SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0//EN" "xhtml.dtd">
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
 <head><title>Accounts</title></head>
 <body>
  <ix:header>
   <ix:resources>
    <xbrli:context id="cur">
     <xbrli:entity><xbrli:identifier>00006245</xbrli:identifier></xbrli:entity>
     <xbrli:period><xbrli:startDate>2023-01-01</xbrli:startDate>
       <xbrli:endDate>2023-12-31</xbrli:endDate></xbrli:period>
    </xbrli:context>
    <xbrli:context id="prior">
     <xbrli:entity><xbrli:identifier>00006245</xbrli:identifier></xbrli:entity>
     <xbrli:period><xbrli:instant>2022-12-31</xbrli:instant></xbrli:period>
    </xbrli:context>
    <xbrli:context id="seg">
     <xbrli:entity><xbrli:identifier>00006245</xbrli:identifier>
      <xbrli:segment>
       <xbrldi:explicitMember dimension="core:SegmentsDimension">core:Segment1Member</xbrldi:explicitMember>
      </xbrli:segment>
     </xbrli:entity>
     <xbrli:period><xbrli:startDate>2023-01-01</xbrli:startDate>
       <xbrli:endDate>2023-12-31</xbrli:endDate></xbrli:period>
    </xbrli:context>
    <xbrli:unit id="gbp"><xbrli:measure>iso4217:GBP</xbrli:measure></xbrli:unit>
    <xbrli:unit id="shares"><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit>
   </ix:resources>
  </ix:header>
  <p>Turnover:
    <ix:nonFraction name="core:TurnoverRevenue" contextRef="cur" unitRef="gbp"
        decimals="0" scale="3">1,234&nbsp;</ix:nonFraction></p>
  <p>Profit/(loss):
    <ix:nonFraction name="core:ProfitLoss" contextRef="cur" unitRef="gbp"
        decimals="0" scale="3">(56)</ix:nonFraction></p>
  <p>Segment turnover:
    <ix:nonFraction name="core:TurnoverRevenue" contextRef="seg" unitRef="gbp"
        decimals="0" scale="3">800</ix:nonFraction></p>
  <p>Shares:
    <ix:nonFraction name="core:ShareCount" contextRef="prior" unitRef="shares"
        decimals="0">1000</ix:nonFraction></p>
  <p>Activity:
    <ix:nonNumeric name="uk-bus:PrincipalActivities" contextRef="cur">Oil &amp; gas
        exploration</ix:nonNumeric></p>
 </body>
</html>"""


def _by_concept(facts):
    out = {}
    for f in facts:
        out.setdefault(f.concept, []).append(f)
    return out


def test_parse_scale_and_units():
    facts = parse_ixbrl(SAMPLE)
    by = _by_concept(facts)
    # 連結 (セグメント無し) の売上: 1,234 × 10^3
    turnover = [f for f in by["core:TurnoverRevenue"] if f.dimension is None]
    assert len(turnover) == 1
    assert turnover[0].value == 1234000.0
    assert turnover[0].unit == "GBP"
    assert turnover[0].period_start == "2023-01-01"
    assert turnover[0].period_end == "2023-12-31"


def test_parse_negative_parentheses():
    facts = parse_ixbrl(SAMPLE)
    pl = _by_concept(facts)["core:ProfitLoss"][0]
    assert pl.value == -56000.0


def test_parse_segment_dimension():
    facts = parse_ixbrl(SAMPLE)
    seg = [f for f in facts if f.concept == "core:TurnoverRevenue" and f.dimension]
    assert len(seg) == 1
    assert seg[0].dimension == "Segment1Member"
    assert seg[0].value == 800000.0


def test_parse_instant_and_shares():
    facts = parse_ixbrl(SAMPLE)
    sh = _by_concept(facts)["core:ShareCount"][0]
    assert sh.value == 1000.0
    assert sh.unit == "shares"
    assert sh.period_end == "2022-12-31"  # instant
    assert sh.period_start is None


def test_parse_non_numeric_and_entities():
    facts = parse_ixbrl(SAMPLE)
    narrative = _by_concept(facts)["uk-bus:PrincipalActivities"][0]
    assert narrative.value is None
    assert "Oil & gas exploration" in narrative.value_text


def test_parse_invalid_returns_empty():
    assert parse_ixbrl("not xml <<<") == []
    assert parse_ixbrl(b"") == []
