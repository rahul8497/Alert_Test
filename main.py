import time
import threading
import os
import math
import pandas as pd
import numpy as np
import pandas_ta as ta
import requests
import yfinance as yf
from datetime import datetime, timezone
from flask import Flask

# ==========================================
# 🔧 LEGACY COMPATIBILITY PATCH FOR PANDAS-TA
# ==========================================
if not hasattr(np, 'int'):
    np.int = int
if not hasattr(np, 'float'):
    np.float = float
if not hasattr(np, 'bool'):
    np.bool = bool

# ==========================================
# 🟢 FLASK HEARTBEAT WEB SERVER FOR RENDER
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return f"Bot Matrix Status: ONLINE | Focused Scanner Active (Gann, MTF OC, Elephant Zones, Strategy TP Bubble)", 200

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# 🚨 CREDENTIALS & HOOKS 🚨
# ==========================================
TELEGRAM_TOKEN = "8992095386:AAFexnI8IRh990PlwZtkn6WkjeOV0yHjkCE"

TELEGRAM_CHAT_IDS = [
    "-5385748601",  # 📡 Signal Telegram Group
    "1136613703"    # Personal Telegram ID
]

MAKE_WEBHOOK_URL = "https://hook.us2.make.com/ztcvn6rzkkidnnwyn2c7imhtgz1yr3sw"

# ==========================================
# 📋 WATCHLIST
# ==========================================
ACTIVE_SYMBOLS = ["BTC-USD", "ETH-USD", "PAXG-USD"]
DISPLAY_NAMES = {
    "BTC-USD": "BITCOIN (BTC/USD)",
    "ETH-USD": "ETHEREUM (ETH/USD)",
    "PAXG-USD": "GOLD SPOT (PAXG/USD)"
}

tg_alert_cache = {}
sms_alert_cache = {}

# ==========================================
# DISPATCH PIPELINES (TELEGRAM & MAKE.COM)
# ==========================================
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            print(f"Network error sending Telegram notification to {chat_id}: {e}")

def send_make_webhook(alert_data):
    try:
        requests.post(MAKE_WEBHOOK_URL, json=alert_data, timeout=10)
    except Exception as e:
        print(f"Network error sending Make Webhook: {e}")

# Live fetch function for 5m intraday candles
def fetch_candles(symbol, limit=500):
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="7d", interval="5m")
        if history.empty: return None
            
        df = history.reset_index()
        cols = {c: c.lower() for c in df.columns}
        df.rename(columns=cols, inplace=True)
        df.rename(columns={"datetime": "timestamp", "date": "timestamp"}, inplace=True)
        return df.tail(limit).copy()
    except Exception as e:
        print(f"Fetch error for {symbol}: {e}")
        return None

# Dedicated daily fetcher
def fetch_daily_candles(symbol, limit=60):
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="3m", interval="1d")
        if history.empty: return None
            
        df = history.reset_index()
        cols = {c: c.lower() for c in df.columns}
        df.rename(columns=cols, inplace=True)
        df.rename(columns={"date": "timestamp", "datetime": "timestamp"}, inplace=True)
        return df.tail(limit).copy()
    except Exception as e:
        print(f"Daily fetch error for {symbol}: {e}")
        return None

# Dedicated weekly fetcher
def fetch_weekly_candles(symbol, limit=20):
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="6m", interval="1wk")
        if history.empty: return None
            
        df = history.reset_index()
        cols = {c: c.lower() for c in df.columns}
        df.rename(columns=cols, inplace=True)
        df.rename(columns={"date": "timestamp", "datetime": "timestamp"}, inplace=True)
        return df.tail(limit).copy()
    except Exception as e:
        print(f"Weekly fetch error for {symbol}: {e}")
        return None

# ==========================================
# 🐘 ADSZ ELEPHANT ZONE & AVERAGES ENGINE
# ==========================================
def calculate_adsz_levels(df_1d, df_1w=None, d_atr_period=20, d_slope=0.69, d_intercept=0.0):
    try:
        if df_1d is None or len(df_1d) < d_atr_period + 2:
            return None

        df_calc = df_1d.copy()
        df_calc['atr'] = ta.atr(df_calc['high'], df_calc['low'], df_calc['close'], length=d_atr_period)
        
        day_open = df_calc['open'].iloc[-1]
        day_atr = df_calc['atr'].iloc[-2]
        day_close_prev = df_calc['close'].iloc[-2]
        day_high_prev = df_calc['high'].iloc[-2]
        day_low_prev = df_calc['low'].iloc[-2]

        if pd.isna(day_atr) or day_close_prev == 0:
            return None

        # Constants
        phi = 1.618034
        sqrt2 = math.sqrt(2)
        sqrt252 = math.sqrt(252)

        # Volatility & Sigma Math
        atr_ann_pct = (day_atr / day_close_prev) * sqrt252 * 100.0
        effvol = (d_slope * atr_ann_pct) + d_intercept
        
        P = round(day_open)
        sigma = (P * effvol) / (100.0 * sqrt252)
        dist_strong = sigma
        dist_weak = sigma / (2.0 * sqrt2)
        
        ws = round(sigma / 4.0)
        ww = round(sigma / (4.0 * phi))

        # Dynamic Zones
        sd_low   = round(P - dist_strong - (ws / 2.0))
        sd_high  = round(P - dist_strong + (ws / 2.0))
        wd_low   = round(P - dist_weak - (ww / 2.0))
        wd_high  = round(P - dist_weak + (ww / 2.0))
        wsp_low  = round(P + dist_weak - (ww / 2.0))
        wsp_high = round(P + dist_weak + (ww / 2.0))
        ss_low   = round(P + dist_strong - (ws / 2.0))
        ss_high  = round(P + dist_strong + (ws / 2.0))
        
        # Daily Average / Dotted Midline (dpoc)
        dpoc = round((day_high_prev + day_low_prev + day_close_prev) / 3.0)

        # Weekly Average / Weekly POC
        wpoc = None
        if df_1w is not None and not df_1w.empty and 'open' in df_1w.columns:
            week_open = df_1w['open'].iloc[-1]
            p_w = round(week_open)
            wpoc = p_w + 8.0

        return {
            "Supply 2": {"top": float(ss_high), "bottom": float(ss_low)},
            "Supply 1": {"top": float(wsp_high), "bottom": float(wsp_low)},
            "Daily Midline": float(dpoc),
            "Weekly Midline": float(wpoc) if wpoc is not None else None,
            "Demand 1": {"top": float(wd_high), "bottom": float(wd_low)},
            "Demand 2": {"top": float(sd_high), "bottom": float(sd_low)}
        }
    except Exception as e:
        print(f"Error in calculate_adsz_levels: {e}")
        return None

# ==========================================
# 💡 TP BUBBLE CALCULATION ENGINE
# ==========================================
def calculate_suggested_tp_bubble(df, suggest_metric="Hit Rate", fast_len=9, slow_len=21, atr_len=14, tp1_val=1.0, tp2_val=2.0, tp3_val=3.0, sl1_val=1.5):
    if df is None or len(df) < slow_len + atr_len:
        return "TP1 50.0%", 1, 50.0

    df_calc = df.copy()
    df_calc['fast_ema'] = ta.ema(df_calc['close'], length=fast_len)
    df_calc['slow_ema'] = ta.ema(df_calc['close'], length=slow_len)
    df_calc['atr'] = ta.atr(df_calc['high'], df_calc['low'], df_calc['close'], length=atr_len)

    total_trades = 0
    tp1_hits = 0
    tp2_hits = 0
    tp3_hits = 0

    for i in range(slow_len, len(df_calc) - 20):
        prev_fast, curr_fast = df_calc['fast_ema'].iloc[i-1], df_calc['fast_ema'].iloc[i]
        prev_slow, curr_slow = df_calc['slow_ema'].iloc[i-1], df_calc['slow_ema'].iloc[i]
        
        crossover = (prev_fast <= prev_slow) and (curr_fast > curr_slow)
        crossunder = (prev_fast >= prev_slow) and (curr_fast < curr_slow)

        if crossover or crossunder:
            direction = 1 if crossover else -1
            entry_price = df_calc['close'].iloc[i]
            atr_v = df_calc['atr'].iloc[i]
            
            if pd.isna(atr_v) or atr_v == 0:
                continue

            total_trades += 1
            d_tp1 = entry_price + (direction * tp1_val * atr_v)
            d_tp2 = entry_price + (direction * tp2_val * atr_v)
            d_tp3 = entry_price + (direction * tp3_val * atr_v)

            hit_1, hit_2, hit_3 = False, False, False

            for j in range(i + 1, min(i + 30, len(df_calc))):
                high_p = df_calc['high'].iloc[j]
                low_p = df_calc['low'].iloc[j]

                if direction == 1:
                    if high_p >= d_tp1: hit_1 = True
                    if high_p >= d_tp2: hit_2 = True
                    if high_p >= d_tp3: hit_3 = True
                else:
                    if low_p <= d_tp1: hit_1 = True
                    if low_p <= d_tp2: hit_2 = True
                    if low_p <= d_tp3: hit_3 = True

            if hit_1: tp1_hits += 1
            if hit_2: tp2_hits += 1
            if hit_3: tp3_hits += 1

    tr = max(1, total_trades)
    rate1 = tp1_hits / tr
    rate2 = tp2_hits / tr
    rate3 = tp3_hits / tr

    d_tp1_dist = tp1_val
    d_tp2_dist = tp2_val
    d_tp3_dist = tp3_val
    sl_dist = max(0.0001, sl1_val)

    if suggest_metric == "Expected Profit":
        v1, v2, v3 = rate1 * d_tp1_dist, rate2 * d_tp2_dist, rate3 * d_tp3_dist
    elif suggest_metric == "Total Profit":
        v1, v2, v3 = tp1_hits * d_tp1_dist, tp2_hits * d_tp2_dist, tp3_hits * d_tp3_dist
    elif suggest_metric == "Risk/Reward":
        v1, v2, v3 = d_tp1_dist / sl_dist, d_tp2_dist / sl_dist, d_tp3_dist / sl_dist
    else:  # "Hit Rate"
        v1, v2, v3 = rate1 * 100, rate2 * 100, rate3 * 100

    best_v = v1
    best_tp = 1
    best_rate = rate1 * 100

    if v2 > best_v:
        best_v = v2
        best_tp = 2
        best_rate = rate2 * 100
    if v3 > best_v:
        best_v = v3
        best_tp = 3
        best_rate = rate3 * 100

    bubble_text = f"TP{best_tp} {best_rate:.1f}%"
    return bubble_text, best_tp, best_rate

# ==========================================
# CORE ALERT PROCESSOR & DUAL ANTI-SPAM
# ==========================================
def process_alert(alert_key, alert_type, symbol, message, price=None, rsi_5m=None, rsi_15m=None, tp_bubble=None, cooldown_sec=14400):
    global tg_alert_cache, sms_alert_cache
    now = datetime.now(timezone.utc)
    
    display_name = DISPLAY_NAMES.get(symbol, symbol)
    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A"
    rsi_5m_str = f"{rsi_5m:.2f}" if isinstance(rsi_5m, (int, float)) and not pd.isna(rsi_5m) else "N/A"
    rsi_15m_str = f"{rsi_15m:.2f}" if isinstance(rsi_15m, (int, float)) and not pd.isna(rsi_15m) else "N/A"
    bubble_str = f"`{tp_bubble}`" if tp_bubble else "N/A"

    # Telegram Dispatch with dynamic cooldown
    send_tg = False

    if alert_key not in tg_alert_cache:
        send_tg = True
    elif (now - tg_alert_cache[alert_key]).total_seconds() >= cooldown_sec:
        send_tg = True

    if send_tg:
        tg_alert_cache[alert_key] = now
        
        if "Demand" in alert_type or "Bull" in alert_type or "BUY" in alert_type:
            header = f"🟢 *[MACRO BUY SIGNAL]* 🟢"
        elif "Supply" in alert_type or "Bear" in alert_type or "SELL" in alert_type:
            header = f"🔴 *[MACRO SELL SIGNAL]* 🔴"
        else:
            header = f"🟡 *[GANN / ZONE SIGNAL]* 🟡"
            
        tg_message = (
            f"{header}\n\n"
            f"• *Asset:* `{display_name}`\n"
            f"• *Price:* `{price_str}`\n"
            f"• *RSI (5M):* `{rsi_5m_str}`\n"
            f"• *RSI (15M):* `{rsi_15m_str}`\n"
            f"• *Suggested TP Bubble:* {bubble_str}\n"
            f"• *Signal Type:* `{alert_type}`\n"
            f"• *Details:* {message}"
        )
        send_telegram_message(tg_message)

    # SMS / Make Webhook Dispatch
    send_sms = False

    if alert_key not in sms_alert_cache:
        send_sms = True
    elif (now - sms_alert_cache[alert_key]).total_seconds() >= cooldown_sec:
        send_sms = True

    if send_sms:
        sms_alert_cache[alert_key] = now
        alert_text = f"ALERT: {display_name} | {alert_type} | Price: {price_str} | Bubble: {tp_bubble if tp_bubble else 'N/A'}"
        sms_payload = {
            "body": alert_text,
            "text": alert_text,
            "message": alert_text
        }
        send_make_webhook(sms_payload)

# ==========================================
# MULTI-TIMEFRAME EVALUATOR
# ==========================================
def evaluate_operator_oc_mtf(df_tf, tf_label, symbol, rsi_5m, rsi_15m):
    if df_tf is None or len(df_tf) < 25:
        return

    df_tf['rsi'] = ta.rsi(df_tf['close'], length=14, mamode='rma')
    df_tf['fast_ema'] = ta.ema(df_tf['close'], length=9)
    df_tf['slow_ema'] = ta.ema(df_tf['close'], length=21)

    curr = df_tf.iloc[-1]
    prev = df_tf.iloc[-2]

    curr_open, curr_close = curr['open'], curr['close']
    curr_high, curr_low = curr['high'], curr['low']
    prev_open, prev_close = prev['open'], prev['close']
    rsi_tf = curr['rsi']

    if pd.isna(rsi_tf): return

    pct_thresh = 0.005

    tp_bubble_text, _, _ = calculate_suggested_tp_bubble(df_tf)

    # 1. Bullish Operator Candle
    is_prev_red = prev_close < prev_open
    is_curr_green = curr_close > curr_open
    green_move_pct = (curr_close - curr_low) / curr_low if curr_low > 0 else 0
    is_engulfing_bull = (curr_open <= prev_close) and (curr_close > prev_open)

    bull_oc = is_prev_red and is_curr_green and is_engulfing_bull and (green_move_pct >= pct_thresh) and (50.0 < rsi_tf < 70.0)

    if bull_oc:
        alert_key = f"{symbol}_{tf_label}_OC_BULL"
        process_alert(
            alert_key, 
            f"{tf_label} Operator Bull OC Candle 🕯️", 
            symbol, 
            f"{tf_label} Bullish OC Reversal! Move: `{green_move_pct*100:.2f}%`, {tf_label} RSI: `{rsi_tf:.2f}`", 
            curr_close, rsi_5m, rsi_15m, tp_bubble=tp_bubble_text
        )

    # 2. Bearish Operator Candle
    is_prev_green = prev_close > prev_open
    is_curr_red = curr_close < curr_open
    red_move_pct = (curr_high - curr_close) / curr_high if curr_high > 0 else 0
    is_engulfing_bear = (curr_open >= prev_close) and (curr_close < prev_open)

    bear_oc = is_prev_green and is_curr_red and is_engulfing_bear and (red_move_pct >= pct_thresh) and (30.0 < rsi_tf < 50.0)

    if bear_oc:
        alert_key = f"{symbol}_{tf_label}_OC_BEAR"
        process_alert(
            alert_key, 
            f"{tf_label} Operator Bear OC Candle 🕯️", 
            symbol, 
            f"{tf_label} Bearish OC Reversal! Move: `{red_move_pct*100:.2f}%`, {tf_label} RSI: `{rsi_tf:.2f}`", 
            curr_close, rsi_5m, rsi_15m, tp_bubble=tp_bubble_text
        )

    # 3. Strategy EMA Crossover Trigger
    prev_fast, curr_fast = prev['fast_ema'], curr['fast_ema']
    prev_slow, curr_slow = prev['slow_ema'], curr['slow_ema']

    ema_bull_cross = (prev_fast <= prev_slow) and (curr_fast > curr_slow)
    ema_bear_cross = (prev_fast >= prev_slow) and (curr_fast < curr_slow)

    if ema_bull_cross:
        alert_key = f"{symbol}_{tf_label}_EMA_BULL"
        process_alert(
            alert_key,
            f"{tf_label} 9/21 EMA Bullish Crossover 🚀",
            symbol,
            f"Golden Cross detected on {tf_label}! Recommended Target: `{tp_bubble_text}`",
            curr_close, rsi_5m, rsi_15m, tp_bubble=tp_bubble_text
        )

    if ema_bear_cross:
        alert_key = f"{symbol}_{tf_label}_EMA_BEAR"
        process_alert(
            alert_key,
            f"{tf_label} 9/21 EMA Bearish Crossunder 🔻",
            symbol,
            f"Death Cross detected on {tf_label}! Recommended Target: `{tp_bubble_text}`",
            curr_close, rsi_5m, rsi_15m, tp_bubble=tp_bubble_text
        )

# ==========================================
# MAIN SCANNER ROUTINE
# ==========================================
def analyze_market(df_5m, symbol):
    try:
        if len(df_5m) < 45: return
        
        # 5M RSI
        df_5m['rsi_5m'] = ta.rsi(df_5m['close'], length=14, mamode='rma')
        
        # Resample Timeframes
        df_temp = df_5m.copy()
        df_temp.set_index('timestamp', inplace=True)
        
        resample_rules = {
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }

        df_15m = df_temp.resample('15min').agg(resample_rules).dropna()
        df_1h  = df_temp.resample('1h').agg(resample_rules).dropna()
        df_4h  = df_temp.resample('4h').agg(resample_rules).dropna()
        
        df_1d  = fetch_daily_candles(symbol)
        df_1w  = fetch_weekly_candles(symbol)

        live_low = df_5m['low'].iloc[-1]
        live_high = df_5m['high'].iloc[-1]
        live_close = df_5m['close'].iloc[-1]
        
        live_rsi_5m = df_5m['rsi_5m'].iloc[-1]
        
        if df_15m is not None and not df_15m.empty:
            df_15m['rsi'] = ta.rsi(df_15m['close'], length=14, mamode='rma')
            live_rsi_15m = df_15m['rsi'].iloc[-1]
        else:
            live_rsi_15m = np.nan

        # ----------------------------------------------------------
        # SIGNAL 1: MTF OPERATOR OC CANDLES & EMA CROSSOVER BUBBLE
        # ----------------------------------------------------------
        evaluate_operator_oc_mtf(df_15m, "15M", symbol, live_rsi_5m, live_rsi_15m)
        evaluate_operator_oc_mtf(df_1h,  "1H",  symbol, live_rsi_5m, live_rsi_15m)
        evaluate_operator_oc_mtf(df_4h,  "4H",  symbol, live_rsi_5m, live_rsi_15m)
        evaluate_operator_oc_mtf(df_1d,  "1D",  symbol, live_rsi_5m, live_rsi_15m)

        # ----------------------------------------------------------
        # SIGNAL 2: AUTOMATED ELEPHANT ADSZ ZONES & MIDLINE TOUCHES
        # ----------------------------------------------------------
        dynamic_elephant_levels = calculate_adsz_levels(df_1d, df_1w)
        
        if dynamic_elephant_levels:
            # 1. Supply & Demand Zone Touches (Reduced to 15-min cooldown to avoid blocking re-tests)
            for key, limits in dynamic_elephant_levels.items():
                if "Midline" in key or limits is None or not isinstance(limits, dict): continue
                
                # Add $10 buffer for BTC to account for TradingView / Yahoo price spread
                buf = 10.0 if symbol == "BTC-USD" else 0.5
                zone_bottom = limits["bottom"] - buf
                zone_top = limits["top"] + buf

                if live_high >= zone_bottom and live_low <= zone_top:
                    process_alert(
                        f"{symbol}_{key.replace(' ', '_')}_Touch", 
                        f"Elephant Zone Touch ({key})", 
                        symbol, 
                        f"Price touched {key}: `[${limits['bottom']:.2f} - ${limits['top']:.2f}]`", 
                        live_close, live_rsi_5m, live_rsi_15m,
                        cooldown_sec=0  # 15 minutes cooldown for zone re-tests
                    )
                    
            # 2. Daily Midline Touch Check (dpoc)
            d_mid = dynamic_elephant_levels.get("Daily Midline")
            d_buffer = 15.0 if symbol == "BTC-USD" else 1.5
            
            if d_mid and (live_high >= (d_mid - d_buffer)) and (live_low <= (d_mid + d_buffer)):
                process_alert(
                    f"{symbol}_Daily_Midline_Touch", 
                    "Daily Midline Touch 🎯", 
                    symbol, 
                    f"Price touched Daily Midline (CPR Pivot) at `${d_mid:.2f}`", 
                    live_close, live_rsi_5m, live_rsi_15m,
                    cooldown_sec=900
                )

            # 3. Weekly Midline Touch Check (wpoc)
            w_mid = dynamic_elephant_levels.get("Weekly Midline")
            w_buffer = 25.0 if symbol == "BTC-USD" else 2.5
            
            if w_mid and (live_high >= (w_mid - w_buffer)) and (live_low <= (w_mid + w_buffer)):
                process_alert(
                    f"{symbol}_Weekly_Midline_Touch", 
                    "Weekly Midline Touch 🎯", 
                    symbol, 
                    f"Price touched Weekly Midline (POC) at `${w_mid:.2f}`", 
                    live_close, live_rsi_5m, live_rsi_15m,
                    cooldown_sec=900
                )

        # ----------------------------------------------------------
        # SIGNAL 3: DYNAMIC GANN NUMBER LEVEL TOUCHES
        # ----------------------------------------------------------
        if df_1d is not None and len(df_1d) >= 2:
            prev_close = df_1d['close'].iloc[-2]
            base_sqrt = round(math.sqrt(prev_close))
            
            gann_levels = {
                "Base Level": base_sqrt ** 2, 
                "Bull +1": (base_sqrt + 1.0) ** 2, 
                "Bull +2": (base_sqrt + 2.0) ** 2, 
                "Bull +3": (base_sqrt + 3.0) ** 2,
                "Bear -1": (base_sqrt - 1.0) ** 2, 
                "Bear -2": (base_sqrt - 2.0) ** 2, 
                "Bear -3": (base_sqrt - 3.0) ** 2
            }
            
            buffer = live_close * 0.0002
            
            for g_name, g_level in gann_levels.items():
                if live_high >= (g_level - buffer) and live_low <= (g_level + buffer):
                    process_alert(
                        f"{symbol}_Gann_{g_name.replace(' ', '_').replace('(', '').replace(')', '')}", 
                        f"Gann Number Touch ({g_name})", 
                        symbol, 
                        f"Price tested Gann Level `{g_name}` at `${g_level:.2f}`", 
                        live_close, live_rsi_5m, live_rsi_15m
                    )
    except Exception as e:
        print(f"Error analyzing market for {symbol}: {e}")

# ==========================================
# RUNTIME SCANNER LIFECYCLE
# ==========================================
def core_market_scanner_loop():
    print(f"Global Macro Market Scanner Online...")
    send_telegram_message("🚀 *Focused Signal Engine Online* 🚀\n• Enabled Alerts ONLY for:\n  1. Important Numbers\n  2. Operator OC Candles (15M, 1H, 4H, 1D)\n  3. Zone Touches\n  4. Trend Recommendations (15M, 1H, 4H, 1D)")
    
    while True:
        try:
            for symbol in ACTIVE_SYMBOLS:
                df = fetch_candles(symbol)
                if df is not None and not df.empty:
                    analyze_market(df, symbol)
                        
            time.sleep(15)
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    scanner_thread = threading.Thread(target=core_market_scanner_loop, daemon=True)
    scanner_thread.start()
    run_web_server()
