"""Pure technical indicator functions for market structure analysis.

Zero I/O, zero external deps. All functions take lists of floats and return
computed values. Designed to pre-digest raw candle data so the AI never has
to do mental math — code does the heavy lifting.

Reuses EMA/RSI from radar_technicals where possible, adds:
- Bollinger Bands (20-period SMA ± 2σ)
- ATR (standalone, Wilder smoothing)
- VWAP (volume-weighted average price)
- Volume profile (price-bucketed volume distribution)
- Trend strength score (composite)
- Key level detection (support/resistance clusters)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════════════════════
# Data types
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class OHLCV:
    """Normalized candle — all floats, ready for math."""
    t: int       # timestamp ms
    o: float
    h: float
    l: float
    c: float
    v: float

    @classmethod
    def from_hl(cls, d: Dict) -> "OHLCV":
        """Convert HL API candle dict (string values) to OHLCV."""
        return cls(
            t=int(d["t"]),
            o=float(d["o"]),
            h=float(d["h"]),
            l=float(d["l"]),
            c=float(d["c"]),
            v=float(d["v"]),
        )

    @classmethod
    def from_hl_list(cls, candles: List[Dict]) -> List["OHLCV"]:
        return [cls.from_hl(c) for c in candles]


@dataclass
class BollingerBands:
    """Bollinger Band state at a point in time."""
    upper: float
    middle: float  # SMA
    lower: float
    bandwidth: float  # (upper - lower) / middle — squeeze detection
    pct_b: float      # (price - lower) / (upper - lower) — position within bands

    @property
    def is_squeeze(self) -> bool:
        """Bandwidth below 4% signals a squeeze (low volatility → breakout pending)."""
        return self.bandwidth < 0.04

    @property
    def zone(self) -> str:
        """Where price sits: 'above_upper', 'upper_half', 'lower_half', 'below_lower'."""
        if self.pct_b > 1.0:
            return "above_upper"
        elif self.pct_b > 0.5:
            return "upper_half"
        elif self.pct_b > 0.0:
            return "lower_half"
        else:
            return "below_lower"


@dataclass
class VolumeProfile:
    """Volume distributed across price buckets."""
    poc: float              # Point of Control — price with highest volume
    value_area_high: float  # Upper bound of 70% volume range
    value_area_low: float   # Lower bound of 70% volume range
    buckets: List[Tuple[float, float]]  # [(price_mid, volume), ...] sorted by price
    total_volume: float

    @property
    def value_area_width_pct(self) -> float:
        """Width of value area as % of POC price."""
        if self.poc == 0:
            return 0.0
        return (self.value_area_high - self.value_area_low) / self.poc * 100


@dataclass
class TrendAnalysis:
    """Composite trend assessment across timeframes."""
    direction: str          # "strong_up", "up", "neutral", "down", "strong_down"
    strength: int           # 0-100
    ema_fast: float         # current fast EMA value
    ema_slow: float         # current slow EMA value
    ema_spread_pct: float   # (fast - slow) / slow * 100
    rsi: float              # current RSI
    rsi_divergence: str     # "bullish_div", "bearish_div", "none"
    higher_highs: bool
    higher_lows: bool
    candle_patterns: List[str]  # detected patterns (hammer, engulfing, etc.)


@dataclass
class KeyLevel:
    """A significant price level (support or resistance)."""
    price: float
    type: str           # "support" or "resistance"
    strength: int       # 1-5 (number of touches/confluences)
    source: str         # "swing", "volume_poc", "bollinger", "round_number"
    distance_pct: float # distance from current price as %


# ═══════════════════════════════════════════════════════════════════════════════
# Core indicators — pure functions
# ═══════════════════════════════════════════════════════════════════════════════

def sma(values: List[float], period: int) -> List[float]:
    """Simple Moving Average. Returns list of length len(values) - period + 1."""
    if len(values) < period:
        return []
    result = []
    window_sum = sum(values[:period])
    result.append(window_sum / period)
    for i in range(period, len(values)):
        window_sum += values[i] - values[i - period]
        result.append(window_sum / period)
    return result


def ema(values: List[float], period: int) -> List[float]:
    """Exponential Moving Average. Returns list same length as input."""
    if not values or period <= 0:
        return []
    k = 2.0 / (period + 1)
    result = [values[0]]
    for i in range(1, len(values)):
        result.append(values[i] * k + result[-1] * (1 - k))
    return result


def atr(candles: List[OHLCV], period: int = 14) -> float:
    """Average True Range (Wilder smoothing). Returns current ATR value.

    Returns 0.0 if insufficient data.
    """
    if len(candles) < period + 1:
        return 0.0

    true_ranges = []
    for i in range(1, len(candles)):
        c = candles[i]
        prev_close = candles[i - 1].c
        tr = max(
            c.h - c.l,
            abs(c.h - prev_close),
            abs(c.l - prev_close),
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return 0.0

    # Initial ATR = simple average of first `period` TRs
    current_atr = sum(true_ranges[:period]) / period

    # Wilder smoothing for remaining
    for i in range(period, len(true_ranges)):
        current_atr = (current_atr * (period - 1) + true_ranges[i]) / period

    return current_atr


def atr_series(candles: List[OHLCV], period: int = 14) -> List[float]:
    """ATR as a series (one value per candle after warmup). For trend detection."""
    if len(candles) < period + 1:
        return []

    true_ranges = []
    for i in range(1, len(candles)):
        c = candles[i]
        prev_close = candles[i - 1].c
        tr = max(c.h - c.l, abs(c.h - prev_close), abs(c.l - prev_close))
        true_ranges.append(tr)

    result = []
    current = sum(true_ranges[:period]) / period
    result.append(current)
    for i in range(period, len(true_ranges)):
        current = (current * (period - 1) + true_ranges[i]) / period
        result.append(current)
    return result


def rsi(closes: List[float], period: int = 14) -> float:
    """Relative Strength Index (0-100). Returns 50.0 if insufficient data."""
    if len(closes) < period + 1:
        return 50.0

    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))

    if len(gains) < period:
        return 50.0

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def bollinger_bands(
    closes: List[float],
    period: int = 20,
    num_std: float = 2.0,
    current_price: Optional[float] = None,
) -> Optional[BollingerBands]:
    """Compute Bollinger Bands. Returns None if insufficient data."""
    if len(closes) < period:
        return None

    window = closes[-period:]
    middle = sum(window) / period
    variance = sum((x - middle) ** 2 for x in window) / period
    std = math.sqrt(variance)

    upper = middle + num_std * std
    lower = middle - num_std * std
    bandwidth = (upper - lower) / middle if middle > 0 else 0
    price = current_price if current_price is not None else closes[-1]
    band_width = upper - lower
    pct_b = (price - lower) / band_width if band_width > 0 else 0.5

    return BollingerBands(
        upper=upper,
        middle=middle,
        lower=lower,
        bandwidth=bandwidth,
        pct_b=pct_b,
    )


def vwap(candles: List[OHLCV]) -> float:
    """Volume-Weighted Average Price over the given candles.

    Returns 0.0 if no volume.
    """
    total_pv = 0.0
    total_v = 0.0
    for c in candles:
        typical = (c.h + c.l + c.c) / 3
        total_pv += typical * c.v
        total_v += c.v
    return total_pv / total_v if total_v > 0 else 0.0


def volume_profile(
    candles: List[OHLCV],
    num_buckets: int = 20,
    value_area_pct: float = 0.70,
) -> Optional[VolumeProfile]:
    """Compute volume profile — distribute volume across price buckets.

    The Point of Control (POC) is the price level with the most volume.
    The Value Area covers value_area_pct (default 70%) of total volume
    centered on the POC.

    Returns None if insufficient data.
    """
    if len(candles) < 5:
        return None

    # Find price range
    all_lows = [c.l for c in candles]
    all_highs = [c.h for c in candles]
    price_min = min(all_lows)
    price_max = max(all_highs)

    if price_max <= price_min:
        return None

    bucket_size = (price_max - price_min) / num_buckets
    if bucket_size <= 0:
        return None

    # Distribute volume into buckets
    # Each candle's volume is distributed proportionally across its range
    bucket_volumes = [0.0] * num_buckets
    total_vol = 0.0

    for c in candles:
        if c.v <= 0:
            continue
        total_vol += c.v
        low_bucket = max(0, int((c.l - price_min) / bucket_size))
        high_bucket = min(num_buckets - 1, int((c.h - price_min) / bucket_size))

        if low_bucket == high_bucket:
            bucket_volumes[low_bucket] += c.v
        else:
            # Spread volume across range
            span = high_bucket - low_bucket + 1
            per_bucket = c.v / span
            for b in range(low_bucket, high_bucket + 1):
                bucket_volumes[b] += per_bucket

    if total_vol == 0:
        return None

    # Find POC (bucket with max volume)
    poc_bucket = max(range(num_buckets), key=lambda i: bucket_volumes[i])
    poc_price = price_min + (poc_bucket + 0.5) * bucket_size

    # Build value area: expand from POC until we cover value_area_pct of volume
    target_vol = total_vol * value_area_pct
    va_vol = bucket_volumes[poc_bucket]
    lo_idx = poc_bucket
    hi_idx = poc_bucket

    while va_vol < target_vol and (lo_idx > 0 or hi_idx < num_buckets - 1):
        expand_lo = bucket_volumes[lo_idx - 1] if lo_idx > 0 else 0
        expand_hi = bucket_volumes[hi_idx + 1] if hi_idx < num_buckets - 1 else 0

        if expand_lo >= expand_hi and lo_idx > 0:
            lo_idx -= 1
            va_vol += bucket_volumes[lo_idx]
        elif hi_idx < num_buckets - 1:
            hi_idx += 1
            va_vol += bucket_volumes[hi_idx]
        else:
            lo_idx -= 1
            va_vol += bucket_volumes[lo_idx]

    va_low = price_min + lo_idx * bucket_size
    va_high = price_min + (hi_idx + 1) * bucket_size

    buckets = [
        (price_min + (i + 0.5) * bucket_size, bucket_volumes[i])
        for i in range(num_buckets)
    ]

    return VolumeProfile(
        poc=poc_price,
        value_area_high=va_high,
        value_area_low=va_low,
        buckets=buckets,
        total_volume=total_vol,
    )


def swing_levels(
    candles: List[OHLCV],
    lookback: int = 5,
    max_levels: int = 5,
) -> Tuple[List[float], List[float]]:
    """Find support and resistance from swing highs/lows.

    Returns (supports, resistances) sorted most recent first.
    """
    if len(candles) < lookback * 2 + 1:
        return [], []

    supports = []
    resistances = []

    for i in range(lookback, len(candles) - lookback):
        # Check if candle i is a swing high
        is_high = all(
            candles[i].h >= candles[j].h
            for j in range(i - lookback, i + lookback + 1)
            if j != i
        )
        if is_high:
            resistances.append(candles[i].h)

        # Check if candle i is a swing low
        is_low = all(
            candles[i].l <= candles[j].l
            for j in range(i - lookback, i + lookback + 1)
            if j != i
        )
        if is_low:
            supports.append(candles[i].l)

    return list(reversed(supports[-max_levels:])), list(reversed(resistances[-max_levels:]))


def cluster_levels(
    levels: List[float],
    tolerance_pct: float = 0.5,
) -> List[Tuple[float, int]]:
    """Cluster nearby price levels. Returns [(avg_price, touch_count)] sorted by count desc."""
    if not levels:
        return []

    sorted_levels = sorted(levels)
    clusters: List[List[float]] = []
    current_cluster = [sorted_levels[0]]

    for price in sorted_levels[1:]:
        if current_cluster and (price - current_cluster[-1]) / current_cluster[-1] * 100 <= tolerance_pct:
            current_cluster.append(price)
        else:
            clusters.append(current_cluster)
            current_cluster = [price]
    clusters.append(current_cluster)

    result = [
        (sum(c) / len(c), len(c))
        for c in clusters
    ]
    return sorted(result, key=lambda x: x[1], reverse=True)


def detect_rsi_divergence(
    closes: List[float],
    period: int = 14,
    lookback: int = 20,
) -> str:
    """Detect RSI divergence over the lookback window.

    - Bullish divergence: price makes lower low but RSI makes higher low
    - Bearish divergence: price makes higher high but RSI makes lower high

    Returns "bullish_div", "bearish_div", or "none".
    """
    if len(closes) < period + lookback:
        return "none"

    # Compute RSI series for the lookback window
    rsi_values = []
    for i in range(lookback):
        end_idx = len(closes) - lookback + i + 1
        rsi_values.append(rsi(closes[:end_idx], period))

    if len(rsi_values) < 2:
        return "none"

    price_window = closes[-lookback:]

    # Find swing lows in both
    mid = lookback // 2
    price_first_half_low = min(price_window[:mid])
    price_second_half_low = min(price_window[mid:])
    rsi_first_half_low = min(rsi_values[:mid])
    rsi_second_half_low = min(rsi_values[mid:])

    # Bullish: price lower low, RSI higher low
    if price_second_half_low < price_first_half_low and rsi_second_half_low > rsi_first_half_low:
        return "bullish_div"

    # Find swing highs
    price_first_half_high = max(price_window[:mid])
    price_second_half_high = max(price_window[mid:])
    rsi_first_half_high = max(rsi_values[:mid])
    rsi_second_half_high = max(rsi_values[mid:])

    # Bearish: price higher high, RSI lower high
    if price_second_half_high > price_first_half_high and rsi_second_half_high < rsi_first_half_high:
        return "bearish_div"

    return "none"


def trend_analysis(
    candles: List[OHLCV],
    fast_period: int = 9,
    slow_period: int = 21,
    rsi_period: int = 14,
) -> TrendAnalysis:
    """Composite trend assessment from multiple indicators.

    Combines EMA crossover, RSI, swing structure, and candlestick patterns
    into a single TrendAnalysis object.
    """
    closes = [c.c for c in candles]

    # EMAs
    ema_fast = ema(closes, fast_period)
    ema_slow = ema(closes, slow_period)
    fast_val = ema_fast[-1] if ema_fast else closes[-1] if closes else 0
    slow_val = ema_slow[-1] if ema_slow else closes[-1] if closes else 0
    spread_pct = (fast_val - slow_val) / slow_val * 100 if slow_val else 0

    # RSI
    rsi_val = rsi(closes, rsi_period)

    # RSI divergence
    div = detect_rsi_divergence(closes, rsi_period)

    # Swing structure
    highs = [c.h for c in candles]
    lows = [c.l for c in candles]
    hh, hl = False, False
    if len(candles) >= 10:
        # Simple: compare last quarter to previous quarter
        q = len(candles) // 4
        if q >= 2:
            recent_highs = highs[-q:]
            prev_highs = highs[-2*q:-q]
            recent_lows = lows[-q:]
            prev_lows = lows[-2*q:-q]
            hh = max(recent_highs) > max(prev_highs) if prev_highs else False
            hl = min(recent_lows) > min(prev_lows) if prev_lows else False

    # Candlestick patterns (convert to HL dict format for reuse)
    candle_dicts = [{"o": str(c.o), "h": str(c.h), "l": str(c.l), "c": str(c.c)} for c in candles[-5:]]
    patterns = _detect_patterns(candle_dicts)

    # Composite direction + strength
    score = 0
    if spread_pct > 0:
        score += min(int(abs(spread_pct) * 10), 30)
    else:
        score -= min(int(abs(spread_pct) * 10), 30)

    if rsi_val > 50:
        score += int((rsi_val - 50) * 0.4)
    else:
        score -= int((50 - rsi_val) * 0.4)

    if hh and hl:
        score += 20
    elif not hh and not hl:
        score -= 20

    # EMA alignment duration
    if ema_fast and ema_slow and len(ema_fast) == len(ema_slow):
        aligned = 0
        for i in range(len(ema_fast) - 1, max(len(ema_fast) - 10, -1), -1):
            if (spread_pct > 0 and ema_fast[i] > ema_slow[i]) or \
               (spread_pct < 0 and ema_fast[i] < ema_slow[i]):
                aligned += 1
            else:
                break
        score += aligned * 2 if spread_pct > 0 else -(aligned * 2)

    strength = min(abs(score), 100)

    if score > 40:
        direction = "strong_up"
    elif score > 15:
        direction = "up"
    elif score < -40:
        direction = "strong_down"
    elif score < -15:
        direction = "down"
    else:
        direction = "neutral"

    return TrendAnalysis(
        direction=direction,
        strength=strength,
        ema_fast=fast_val,
        ema_slow=slow_val,
        ema_spread_pct=round(spread_pct, 3),
        rsi=round(rsi_val, 1),
        rsi_divergence=div,
        higher_highs=hh,
        higher_lows=hl,
        candle_patterns=patterns,
    )


def find_key_levels(
    candles: List[OHLCV],
    current_price: float,
    bb: Optional[BollingerBands] = None,
    vp: Optional[VolumeProfile] = None,
    max_levels: int = 8,
) -> List[KeyLevel]:
    """Assemble key price levels from multiple sources, ranked by strength.

    Sources: swing S/R, volume POC/VA, Bollinger bands, round numbers.
    All levels include distance from current price for quick AI scanning.
    """
    raw_levels: List[KeyLevel] = []

    if current_price <= 0:
        return raw_levels

    # 1. Swing-based support/resistance
    supports, resistances = swing_levels(candles)
    s_clusters = cluster_levels(supports)
    r_clusters = cluster_levels(resistances)

    for price, count in s_clusters[:4]:
        dist = (current_price - price) / current_price * 100
        raw_levels.append(KeyLevel(
            price=round(price, 4),
            type="support",
            strength=min(count, 5),
            source="swing",
            distance_pct=round(dist, 2),
        ))

    for price, count in r_clusters[:4]:
        dist = (price - current_price) / current_price * 100
        raw_levels.append(KeyLevel(
            price=round(price, 4),
            type="resistance",
            strength=min(count, 5),
            source="swing",
            distance_pct=round(dist, 2),
        ))

    # 2. Volume profile levels
    if vp:
        dist_poc = abs(current_price - vp.poc) / current_price * 100
        raw_levels.append(KeyLevel(
            price=round(vp.poc, 4),
            type="support" if vp.poc < current_price else "resistance",
            strength=4,
            source="volume_poc",
            distance_pct=round(dist_poc, 2),
        ))
        for edge, label in [(vp.value_area_low, "support"), (vp.value_area_high, "resistance")]:
            dist = abs(current_price - edge) / current_price * 100
            raw_levels.append(KeyLevel(
                price=round(edge, 4),
                type=label,
                strength=3,
                source="volume_poc",
                distance_pct=round(dist, 2),
            ))

    # 3. Bollinger band levels
    if bb:
        for price, label in [(bb.lower, "support"), (bb.upper, "resistance"), (bb.middle, "support")]:
            dist = abs(current_price - price) / current_price * 100
            tp = "support" if price < current_price else "resistance"
            raw_levels.append(KeyLevel(
                price=round(price, 4),
                type=tp,
                strength=2,
                source="bollinger",
                distance_pct=round(dist, 2),
            ))

    # 4. Round numbers (psychological levels)
    if current_price > 0:
        magnitude = 10 ** max(0, int(math.log10(current_price)) - 1)
        rounded = round(current_price / magnitude) * magnitude
        for offset in [-2, -1, 0, 1, 2]:
            level = rounded + offset * magnitude
            if level > 0:
                dist = abs(current_price - level) / current_price * 100
                if dist < 5:  # only include if within 5%
                    tp = "support" if level < current_price else "resistance"
                    raw_levels.append(KeyLevel(
                        price=level,
                        type=tp,
                        strength=1,
                        source="round_number",
                        distance_pct=round(dist, 2),
                    ))

    # Deduplicate close levels and sort by strength desc, then distance asc
    seen_prices: set = set()
    deduped: List[KeyLevel] = []
    for kl in sorted(raw_levels, key=lambda x: (-x.strength, abs(x.distance_pct))):
        # Round to avoid near-dupes
        bucket = round(kl.price / (current_price * 0.002)) if current_price > 0 else kl.price
        if bucket not in seen_prices:
            seen_prices.add(bucket)
            deduped.append(kl)

    return deduped[:max_levels]


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _detect_patterns(candles: List[Dict]) -> List[str]:
    """Detect candlestick patterns (inlined to avoid circular import with radar_technicals)."""
    if len(candles) < 2:
        return []

    patterns = []
    c = candles[-1]
    o, h, l, cl = float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"])
    body = abs(cl - o)
    total_range = h - l
    if total_range == 0:
        return []

    upper_wick = h - max(o, cl)
    lower_wick = min(o, cl) - l

    # Doji
    is_doji = body / total_range < 0.1

    # Hammer
    if lower_wick > total_range * 0.6 and upper_wick < total_range * 0.1 and body / total_range < 0.35:
        patterns.append("hammer")
    # Shooting star (inverse hammer at resistance)
    elif upper_wick > total_range * 0.6 and lower_wick < total_range * 0.1 and body / total_range < 0.35:
        patterns.append("shooting_star")
    elif is_doji:
        patterns.append("doji")

    # Engulfing
    if len(candles) >= 2:
        prev = candles[-2]
        po, pcl = float(prev["o"]), float(prev["c"])
        if pcl < po and cl > o and cl > po and o < pcl:
            patterns.append("bullish_engulfing")
        if pcl > po and cl < o and cl < po and o > pcl:
            patterns.append("bearish_engulfing")

    return patterns
