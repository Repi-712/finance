# -*- coding: utf-8 -*-
"""
テクニカル指標の計算関数群（標準ライブラリのみ、pandas不要）。
すべて「日付昇順」のリストを受け取り、同じ長さのリストを返す
（計算に必要な期間が足りない箇所は None）。
"""


def sma(values, period):
    out = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1: i + 1]
        out[i] = sum(window) / period
    return out


def ema(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    k = 2 / (period + 1)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(closes, period=14):
    """Wilder's RSI"""
    out = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def calc(ag, al):
        if al == 0:
            return 100.0
        rs = ag / al
        return 100 - (100 / (1 + rs))

    out[period] = calc(avg_gain, avg_loss)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i + 1] = calc(avg_gain, avg_loss)
    return out


def bollinger_bands(closes, period=20, num_std=2.0):
    mid = sma(closes, period)
    upper = [None] * len(closes)
    lower = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1: i + 1]
        m = mid[i]
        var = sum((x - m) ** 2 for x in window) / period
        sd = var ** 0.5
        upper[i] = m + num_std * sd
        lower[i] = m - num_std * sd
    return mid, upper, lower


def cross_signal(short_ma, long_ma):
    """
    直近バーで short が long を上抜け/下抜けしたか判定。
    戻り値: "golden" | "dead" | None
    """
    if len(short_ma) < 2 or len(long_ma) < 2:
        return None
    s_prev, s_now = short_ma[-2], short_ma[-1]
    l_prev, l_now = long_ma[-2], long_ma[-1]
    if None in (s_prev, s_now, l_prev, l_now):
        return None
    if s_prev <= l_prev and s_now > l_now:
        return "golden"
    if s_prev >= l_prev and s_now < l_now:
        return "dead"
    return None


def volume_spike(volumes, lookback=20, multiplier=2.0):
    """直近出来高が過去lookback日平均のmultiplier倍を超えたか"""
    if len(volumes) < lookback + 1:
        return None
    base = volumes[-(lookback + 1):-1]
    avg = sum(base) / len(base)
    if avg == 0:
        return None
    ratio = volumes[-1] / avg
    return ratio if ratio >= multiplier else None


def pct_change_spike(closes, threshold=5.0):
    """直近1日の騰落率が閾値(%)を超えたか"""
    if len(closes) < 2 or closes[-2] == 0:
        return None
    chg = (closes[-1] - closes[-2]) / closes[-2] * 100
    return chg if abs(chg) >= threshold else None


def new_high(highs, lookback=5):
    """本日の高値が過去(lookback-1)日の高値をすべて上回っていれば、その高値を返す"""
    if len(highs) < lookback:
        return None
    prior = highs[-lookback:-1]
    if not prior:
        return None
    return highs[-1] if highs[-1] > max(prior) else None


def new_low(lows, lookback=5):
    """本日の安値が過去(lookback-1)日の安値をすべて下回っていれば、その安値を返す"""
    if len(lows) < lookback:
        return None
    prior = lows[-lookback:-1]
    if not prior:
        return None
    return lows[-1] if lows[-1] < min(prior) else None
