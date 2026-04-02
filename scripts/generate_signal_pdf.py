#!/usr/bin/env python3
"""Generate the Signal Interpretation Methodology PDF."""
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable,
)

OUTPUT = "docs/signal_methodology.pdf"

# Colors
DARK = HexColor("#1a1a2e")
ACCENT = HexColor("#e94560")
BLUE = HexColor("#0f3460")
GREEN = HexColor("#2d5a2d")
RED = HexColor("#5a2d2d")
GOLD = HexColor("#5a4a2d")
GREY = HexColor("#888888")
LIGHT_BG = HexColor("#f4f4f8")

styles = getSampleStyleSheet()

# Custom styles
styles.add(ParagraphStyle("DocTitle", parent=styles["Title"], fontSize=22,
    spaceAfter=6, textColor=DARK, alignment=TA_CENTER))
styles.add(ParagraphStyle("Subtitle", parent=styles["Normal"], fontSize=11,
    textColor=GREY, alignment=TA_CENTER, spaceAfter=20))
styles.add(ParagraphStyle("SectionHead", parent=styles["Heading1"], fontSize=15,
    textColor=BLUE, spaceBefore=18, spaceAfter=8))
styles.add(ParagraphStyle("SubHead", parent=styles["Heading2"], fontSize=12,
    textColor=DARK, spaceBefore=12, spaceAfter=4))
styles.add(ParagraphStyle("Body", parent=styles["Normal"], fontSize=10,
    leading=14, spaceAfter=6))
styles.add(ParagraphStyle("BulletCustom", parent=styles["Normal"], fontSize=10,
    leading=14, leftIndent=20, bulletIndent=8, spaceAfter=3))
styles.add(ParagraphStyle("CodeBlock", parent=styles["Normal"], fontSize=9,
    fontName="Courier", leading=12, leftIndent=20, textColor=DARK,
    backColor=LIGHT_BG, spaceAfter=6, spaceBefore=4))
styles.add(ParagraphStyle("SmallNote", parent=styles["Normal"], fontSize=8,
    textColor=GREY, spaceAfter=4))
styles.add(ParagraphStyle("Example", parent=styles["Normal"], fontSize=9.5,
    leading=13, leftIndent=15, textColor=HexColor("#333333"),
    backColor=HexColor("#f0f7f0"), spaceBefore=4, spaceAfter=8,
    borderWidth=1, borderColor=GREEN, borderPadding=6))


def hr():
    return HRFlowable(width="100%", thickness=0.5, color=GREY, spaceAfter=8, spaceBefore=4)


def build():
    doc = SimpleDocTemplate(OUTPUT, pagesize=letter,
        leftMargin=0.8*inch, rightMargin=0.8*inch,
        topMargin=0.7*inch, bottomMargin=0.7*inch)
    story = []

    # ── Title ──
    story.append(Spacer(1, 30))
    story.append(Paragraph("Signal Interpretation Methodology", styles["DocTitle"]))
    story.append(Paragraph("HyperLiquid Trading Bot &mdash; render_signal_summary()", styles["Subtitle"]))
    story.append(Paragraph("Version 1.0 &bull; April 2026 &bull; common/market_snapshot.py", styles["SmallNote"]))
    story.append(hr())

    # ── 1. Overview ──
    story.append(Paragraph("1. Overview", styles["SectionHead"]))
    story.append(Paragraph(
        "The signal interpreter is a <b>pre-computation layer</b> that transforms raw technical "
        "indicators (RSI, Bollinger Bands, VWAP, candle patterns, trend analysis) into "
        "<b>plain-English market assessments</b> that any AI model &mdash; including small, free "
        "models on OpenRouter &mdash; can quote directly in responses.", styles["Body"]))
    story.append(Paragraph(
        "Instead of giving a model raw numbers like <font face='Courier'>RSI=69, BB=above_upper, "
        "pattern=doji</font> and hoping it interprets correctly, the signal interpreter outputs:", styles["Body"]))
    story.append(Paragraph(
        '<font face="Courier" color="#2d5a2d">SIGNAL: EXHAUSTION &mdash; RSI 69 + above upper BB + doji. '
        'Pullback likely.<br/>SHORTS: near-term opportunity if momentum fades. LONGS: wait for pullback.</font>',
        styles["Example"]))
    story.append(Paragraph(
        "This eliminates the most common failure mode: the AI seeing bullish trend data and saying "
        '"bullish, you\'re screwed" without noticing the exhaustion signals that actually favour '
        "a contrarian position.", styles["Body"]))

    # ── 2. Bias Scoring ──
    story.append(Paragraph("2. Bias Scoring System", styles["SectionHead"]))
    story.append(Paragraph(
        "The interpreter computes a <b>bias score</b> from &minus;4 (strongly bearish) to +4 "
        "(strongly bullish) by accumulating weighted signals from multiple independent sources. "
        "Each source contributes independently &mdash; the score is additive, not averaged.", styles["Body"]))

    score_data = [
        ["Signal Source", "Bullish", "Bearish", "Weight"],
        ["Trend direction (up/down)", "+1 or +2", "-1 or -2", "Strength > 50 = double"],
        ["Multi-TF confluence", "+1", "-1", "All 1h/4h/1d aligned"],
        ["RSI zone", "+1 (< 30)", "-1 (> 70)", "Overbought / oversold"],
        ["BB position", "+1 (below lower)", "-1 (above upper)", "Bollinger Band extremes"],
        ["RSI divergence", "+2 (bullish div)", "-2 (bearish div)", "Price vs momentum disagreement"],
        ["Near key level", "+1 (near support)", "-1 (near resistance)", "Within 2% of level"],
        ["Exhaustion pattern", "+2 (capitulation)", "-2 (exhaustion)", "RSI extreme + BB + candle"],
    ]
    t = Table(score_data, colWidths=[1.6*inch, 1.3*inch, 1.3*inch, 2.0*inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, LIGHT_BG]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Score Interpretation", styles["SubHead"]))
    map_data = [
        ["Score Range", "Label", "Emoji", "Meaning"],
        ["+3 to +4", "STRONGLY BULLISH", "&&", "Multiple independent signals aligned bullish"],
        ["+1 to +2", "BULLISH", "&", "Net bullish bias from indicators"],
        ["0", "NEUTRAL", "-", "Conflicting or insufficient signals"],
        ["-1 to -2", "BEARISH", "v", "Net bearish bias from indicators"],
        ["-3 to -4", "STRONGLY BEARISH", "vv", "Multiple independent signals aligned bearish"],
    ]
    t2 = Table(map_data, colWidths=[1.2*inch, 1.6*inch, 0.8*inch, 2.6*inch])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, LIGHT_BG]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t2)

    # ── 3. Pattern Detection ──
    story.append(PageBreak())
    story.append(Paragraph("3. Pattern Detection", styles["SectionHead"]))

    story.append(Paragraph("3.1 Exhaustion", styles["SubHead"]))
    story.append(Paragraph(
        "<b>Trigger:</b> RSI &gt; 65 AND price above upper Bollinger Band AND reversal candle "
        "pattern detected (doji, hammer, shooting star, or engulfing).", styles["Body"]))
    story.append(Paragraph(
        "<b>Interpretation:</b> The trend has pushed price to an extreme. Momentum is still positive "
        "but the combination of overbought RSI, BB overextension, and indecision candle suggests "
        "the move is running out of steam. A pullback toward the BB midline (20-period SMA) is "
        "the highest-probability next move.", styles["Body"]))
    story.append(Paragraph(
        "<b>Bias impact:</b> &minus;2 (overrides the bullish trend signal)", styles["Body"]))

    story.append(Paragraph("3.2 Capitulation", styles["SubHead"]))
    story.append(Paragraph(
        "<b>Trigger:</b> RSI &lt; 35 AND price below lower Bollinger Band AND reversal candle.", styles["Body"]))
    story.append(Paragraph(
        "<b>Interpretation:</b> Aggressive selling has pushed price below statistical norms. "
        "When combined with a reversal candle, this signals panic selling may be exhausted. "
        "A bounce toward the BB midline is likely. Not a trend reversal call &mdash; just a "
        "tactical bounce opportunity.", styles["Body"]))
    story.append(Paragraph("<b>Bias impact:</b> +2", styles["Body"]))

    story.append(Paragraph("3.3 Bollinger Band Squeeze", styles["SubHead"]))
    story.append(Paragraph(
        "<b>Trigger:</b> BB bandwidth falls below its 20-period average (bands are contracting).", styles["Body"]))
    story.append(Paragraph(
        "<b>Interpretation:</b> Volatility is compressed. Historical tendency is for low-volatility "
        "regimes to resolve into high-volatility breakouts. Direction is unknown &mdash; the squeeze "
        "signals <i>magnitude</i>, not direction. Traders should prepare for movement, not commit "
        "to a side until the breakout occurs.", styles["Body"]))
    story.append(Paragraph("<b>Bias impact:</b> 0 (directionally neutral)", styles["Body"]))

    story.append(Paragraph("3.4 RSI Divergence", styles["SubHead"]))
    story.append(Paragraph(
        "<b>Bullish divergence:</b> Price makes a lower low but RSI makes a higher low. "
        "Selling pressure is weakening even though price keeps falling. Often precedes reversals.", styles["Body"]))
    story.append(Paragraph(
        "<b>Bearish divergence:</b> Price makes a higher high but RSI makes a lower high. "
        "Buying pressure is fading even though price keeps rising. The rally is losing internal "
        "momentum.", styles["Body"]))
    story.append(Paragraph("<b>Bias impact:</b> +2 (bullish div) or &minus;2 (bearish div)", styles["Body"]))

    # ── 4. Real Examples ──
    story.append(Paragraph("4. Real Examples", styles["SectionHead"]))

    story.append(Paragraph("Example 1: Brent Oil &mdash; Exhaustion in a Bull Market", styles["SubHead"]))
    story.append(Paragraph(
        '<font face="Courier">xyz:BRENTOIL @ $109.00<br/>'
        'RSI: 69 (near overbought) | BB: above_upper | Pattern: doji<br/>'
        'All timeframes: up | 28% rally over window | Above VWAP<br/>'
        'Near resistance: $108.2 (+0.7%)</font>', styles["Example"]))
    story.append(Paragraph(
        "<b>Score calculation:</b> Trend up (+2) + All TF aligned (+1) + Near overbought RSI (&minus;1) "
        "+ Above upper BB (implicit in exhaustion) + Exhaustion pattern (&minus;2) + Near resistance (&minus;1) "
        "= <b>&minus;1 BEARISH</b>", styles["Body"]))
    story.append(Paragraph(
        "<b>Output:</b> Despite the strongly bullish trend, the system correctly identifies exhaustion. "
        "The model tells the user: <i>\"Pullback likely. Shorts have near-term opportunity if momentum "
        "fades. Longs should wait for pullback.\"</i> This is the nuance a dumb model misses &mdash; it "
        "would just say \"bullish\" and miss the reversal setup.", styles["Body"]))

    story.append(Paragraph("Example 2: Bitcoin &mdash; Capitulation Bounce", styles["SubHead"]))
    story.append(Paragraph(
        '<font face="Courier">BTC @ $66,050<br/>'
        'RSI: 20 (oversold) | BB: below_lower | Low volatility flag<br/>'
        'Below VWAP | Near support: $66,000 (+0.1%)</font>', styles["Example"]))
    story.append(Paragraph(
        "<b>Score:</b> Trend down (&minus;1) + Oversold RSI (+1) + Below lower BB (capitulation +2) "
        "+ Near support (+1) = <b>+1 BULLISH</b>", styles["Body"]))
    story.append(Paragraph(
        "<b>Output:</b> The system identifies a bounce opportunity despite the bearish trend. "
        "The model tells the user: <i>\"Oversold zone. Near-term bounce likely. Longs have an "
        "opportunity. Shorts should take profits and cover risk.\"</i>", styles["Body"]))

    story.append(Paragraph("Example 3: Gold &mdash; Strong Trend Continuation", styles["SubHead"]))
    story.append(Paragraph(
        '<font face="Courier">xyz:GOLD @ $4,614<br/>'
        'RSI: 55 (neutral) | BB: mid | All 3 timeframes: up<br/>'
        'Strong trend flag on 4h | Above VWAP</font>', styles["Example"]))
    story.append(Paragraph(
        "<b>Score:</b> Trend up strong (+2) + All TF aligned (+1) + Above VWAP (context) = "
        "<b>+3 STRONGLY BULLISH</b>", styles["Body"]))
    story.append(Paragraph(
        "<b>Output:</b> Clean trend continuation. No exhaustion, no divergence, RSI in healthy "
        "range. The model gives clear guidance: <i>\"Strongly bullish. Longs: favorable conditions. "
        "Shorts: against trend, high risk.\"</i>", styles["Body"]))

    # ── 5. Position Guidance ──
    story.append(PageBreak())
    story.append(Paragraph("5. Position Guidance Logic", styles["SectionHead"]))
    story.append(Paragraph(
        "The signal interpreter produces <b>directional guidance for both longs AND shorts</b> "
        "in every assessment. This ensures the model gives relevant advice regardless of which "
        "side the user is on.", styles["Body"]))

    guide_data = [
        ["Condition", "Longs", "Shorts"],
        ["Score >= +2", "Favorable conditions", "Against trend, high risk"],
        ["Score <= -2", "Against trend, high risk", "Favorable conditions"],
        ["Exhaustion (bull)", "Wait for pullback", "Near-term opportunity"],
        ["Capitulation (bear)", "Near-term bounce opportunity", "Take profits, cover risk"],
        ["Neutral / mixed", "Wait for directional signal", "Wait for directional signal"],
        ["High volatility", "Size conservatively", "Size conservatively"],
        ["Low volatility", "Breakout setup possible", "Breakout setup possible"],
    ]
    t3 = Table(guide_data, colWidths=[1.8*inch, 2.2*inch, 2.2*inch])
    t3.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, LIGHT_BG]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t3)

    # ── 6. Data Sources ──
    story.append(Spacer(1, 12))
    story.append(Paragraph("6. Data Sources & Indicators", styles["SectionHead"]))

    data_data = [
        ["Indicator", "Source", "Timeframes", "Purpose"],
        ["RSI (14)", "Candle closes", "1h, 4h, 1d", "Momentum / overbought-oversold"],
        ["Bollinger Bands (20,2)", "Candle closes", "1h, 4h, 1d", "Volatility envelope + squeeze"],
        ["EMA 20/50", "Candle closes", "1h, 4h, 1d", "Trend direction + spread"],
        ["ATR (14)", "H/L/C candles", "1h, 4h, 1d", "Volatility for stops + sizing"],
        ["VWAP (24-bar)", "OHLCV candles", "1h", "Institutional fair value"],
        ["Volume Profile", "Volume per price", "4h", "Support/resistance (POC, VA)"],
        ["Candle Patterns", "OHLC shape analysis", "1h", "Doji, hammer, engulfing, etc."],
        ["Key Levels", "Swing H/L + BB + VP", "All", "Support/resistance with strength"],
    ]
    t4 = Table(data_data, colWidths=[1.3*inch, 1.3*inch, 1.1*inch, 2.5*inch])
    t4.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, LIGHT_BG]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t4)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "All candle data fetched from HyperLiquid via the REST API and cached in a local SQLite "
        "database (<font face='Courier'>modules/candle_cache.py</font>). Snapshots are computed "
        "on each AI message via <font face='Courier'>build_snapshot()</font> and rendered via "
        "<font face='Courier'>render_snapshot()</font> + <font face='Courier'>render_signal_summary()</font>.",
        styles["Body"]))

    # ── 7. Limitations ──
    story.append(Paragraph("7. Limitations", styles["SectionHead"]))
    story.append(Paragraph(
        "This system is designed for a <b>Telegram trading bot</b>, not a quantitative hedge fund. "
        "It provides actionable signals at a level appropriate for a human trader who wants "
        "AI-assisted analysis. It does <b>not</b> cover:", styles["Body"]))

    limits = [
        "<b>Order flow analysis</b> &mdash; no bid/ask imbalance, no Level 2 data, no tape reading",
        "<b>Cross-market correlation</b> &mdash; doesn't detect when oil moves drag BTC, or vice versa",
        "<b>Regime detection</b> &mdash; no Hidden Markov Models or statistical regime classification",
        "<b>Sentiment analysis</b> &mdash; no news NLP, no social media signals, no funding rate sentiment",
        "<b>Machine learning signals</b> &mdash; all logic is rule-based, no trained models",
        "<b>Backtest validation</b> &mdash; signals are not historically backtested for win rates",
    ]
    for lim in limits:
        story.append(Paragraph(lim, styles["BulletCustom"], bulletText="\u2022"))

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "The system is <b>extensible</b> &mdash; new signal types can be added to "
        "<font face='Courier'>render_signal_summary()</font> without changing the snapshot "
        "pipeline. Future additions could include funding rate signals, cross-market correlation, "
        "and volume-weighted momentum.", styles["Body"]))

    story.append(hr())
    story.append(Paragraph(
        "<i>Generated from common/market_snapshot.py. "
        "Source of truth is the code.</i>", styles["SmallNote"]))

    doc.build(story)
    print(f"PDF saved to {OUTPUT}")


if __name__ == "__main__":
    build()
