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
# 📋 WATCHLIST & PREV CLOSE SYNC (UPDATED)
# ==========================================
ACTIVE_SYMBOLS = ["BTC-USD", "ETH-USD", "PAXG-USD"]
DISPLAY_NAMES = {
    "BTC-USD": "BITCOIN (BTC/USD)",
    "ETH-USD": "ETHEREUM (ETH/USD)",
    "PAXG-USD": "GOLD SPOT (PAXG/USD)"
}

MANUAL_PREV_CLOSES = {
    "BTC-USD": 69283.00,
    "ETH-USD": 2251.00,
    "PAXG-USD": 4495.00
}

# ==========================================
# 🐘 ELEPHANT EDGE CONFIGURATIONS (UPDATED SYNCED LEVELS)
# ==========================================
ELEPHANT_EDGE_LEVELS = {
    "BTC-USD": {
        "Supply 2": {"top": 70236.62, "bottom": 70028.87},
        "Supply 1": {"top": 69646.38, "bottom": 69522.79},
        "Midline": 67641.06,  # Dotted Midline / Base Line
        "Demand 1": {"top": 69043.35, "bottom": 68919.76},
        "Demand 2": {"top": 68537.27, "bottom": 68329.52}
    },
    "ETH-USD": {
        "Supply 2": {"top": 2285.85, "bottom": 2278.31},
        "Supply 1": {"top": 2264.42, "bottom": 2259.93},
        "Midline": 2153.04,  # Dotted Midline / Base Line
        "Demand 1": {"top": 2242.51, "bottom": 2238.02},
        "Demand 2": {"top": 2224.13, "bottom": 2216.59}
    },
    "PAXG-USD": {
        "Supply 2": {"top": 4551.10, "bottom": 4538.81},
        "Supply 1": {"top": 4516.19, "bottom": 4508.88},
        "Midline": 4443.75,  # Dotted Midline / Base Line
        "Demand 1": {"top": 4480.52, "bottom": 4473.21},
        "Demand 2": {"top": 4450.59, "bottom": 4438.30}
    }
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

def fetch_candles(symbol, limit=500):
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="60d", interval="5m")
        if history.empty: return None
            
        df = history.reset_index()
        df.rename(columns={"Datetime": "timestamp", "Date": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}, inplace=True)
        return df.tail(limit).copy()
    except Exception as e:
        return None

# ==========================================
# 💡 TP BUBBLE CALCULATION ENGINE
# ==========================================
def calculate_suggested_tp_bubble(df, suggest_metric="Hit Rate", fast_len=9, slow_len=21, atr_len=14, tp1_val=1.0, tp2_val=2.0, tp3_val=3.0, sl1_val=1.5):
    """
    Calculates historical Take Profit hit rates (TP1, TP2, TP3) and determines 
    the best recommended TP target and hit rate percentage (Pine Script Bubble Logic).
    """
    if len(df) < slow_len + atr_len:
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

            # Evaluate forward bars for TP hits
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
def process_alert(alert_key, alert_type, symbol, message, price=None, rsi_5m=None, rsi_15m=None, tp_bubble=None):
    global tg_alert_cache, sms_alert_cache
    now = datetime.now(timezone.utc)
    
    display_name = DISPLAY_NAMES.get(symbol, symbol)
    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A"
    rsi_5m_str = f"{rsi_5m:.2f}" if isinstance(rsi_5m, (int, float)) and not pd.isna(rsi_5m) else "N/A"
    rsi_15m_str = f"{rsi_15m:.2f}" if isinstance(rsi_15m, (int, float)) and not pd.isna(rsi_15m) else "N/A"
    bubble_str = f"`{tp_bubble}`" if tp_bubble else "N/A"

    # Telegram Dispatch - 4 Hours Cooldown (14400 Seconds)
    tg_cooldown = 14400  
    send_tg = False

    if alert_key not in tg_alert_cache:
        send_tg = True
    elif (now - tg_alert_cache[alert_key]).total_seconds() >= tg_cooldown:
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

    # SMS / Make Webhook Dispatch - 4 Hours Cooldown (14400 Seconds)
    sms_cooldown = 14400  
    send_sms = False

    if alert_key not in sms_alert_cache:
        send_sms = True
    elif (now - sms_alert_cache[alert_key]).total_seconds() >= sms_cooldown:
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
# MULTI-TIMEFRAME EVALUATOR (OC CANDLES & TP BUBBLE CROSSOVERS)
# ==========================================
def evaluate_operator_oc_mtf(df_tf, tf_label, symbol, rsi_5m, rsi_15m):
    """
    Evaluates Operator Candle (OC) Setup & Strategy Crossovers for specific timeframe (15M, 1H, 4H, 1D):
    """
    if len(df_tf) < 25:
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

    pct_thresh = 0.005  # 0.5% Minimum Move

    # Calculate Suggested TP Bubble for this timeframe
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

    # 3. Strategy EMA Crossover Trigger (TP Bubble Signal)
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
    if len(df_5m) < 45: return
    
    # 5M RSI
    df_5m['rsi_5m'] = ta.rsi(df_5m['close'], length=14, mamode='rma')
    
    # Resample Timeframes (15m, 1h, 4h, 1d)
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
    df_1d  = df_temp.resample('1D').agg(resample_rules).dropna()

    live_low = df_5m['low'].iloc[-1]
    live_high = df_5m['high'].iloc[-1]
    live_close = df_5m['close'].iloc[-1]
    
    live_rsi_5m = df_5m['rsi_5m'].iloc[-1]
    
    if not df_15m.empty:
        df_15m['rsi'] = ta.rsi(df_15m['close'], length=14, mamode='rma')
        live_rsi_15m = df_15m['rsi'].iloc[-1]
    else:
        live_rsi_15m = np.nan

    # ----------------------------------------------------------
    # SIGNAL 1: MTF OPERATOR OC CANDLES & EMA CROSSOVER BUBBLE (15M, 1H, 4H, 1D)
    # ----------------------------------------------------------
    evaluate_operator_oc_mtf(df_15m, "15M", symbol, live_rsi_5m, live_rsi_15m)
    evaluate_operator_oc_mtf(df_1h,  "1H",  symbol, live_rsi_5m, live_rsi_15m)
    evaluate_operator_oc_mtf(df_4h,  "4H",  symbol, live_rsi_5m, live_rsi_15m)
    evaluate_operator_oc_mtf(df_1d,  "1D",  symbol, live_rsi_5m, live_rsi_15m)

    # ----------------------------------------------------------
    # SIGNAL 2: ELEPHANT ZONE TOUCHES (Supply, Demand & Midline)
    # ----------------------------------------------------------
    if symbol in ELEPHANT_EDGE_LEVELS:
        levels = ELEPHANT_EDGE_LEVELS[symbol]
        
        for key, limits in levels.items():
            if key == "Midline": continue
            if live_high >= limits["bottom"] and live_low <= limits["top"]:
                process_alert(
                    f"{symbol}_{key.replace(' ', '_')}_Touch", 
                    f"Elephant Zone Touch ({key})", 
                    symbol, 
                    f"Price touched {key}: `[${limits['bottom']:.2f} - ${limits['top']:.2f}]`", 
                    live_close, live_rsi_5m, live_rsi_15m
                )
                
        # Midline touch check
        mid_to_check = levels.get("Midline")
        midline_buffer = 15.0 if symbol == "BTC-USD" else 1.5
        
        if mid_to_check and (live_high >= (mid_to_check - midline_buffer)) and (live_low <= (mid_to_check + midline_buffer)):
            process_alert(
                f"{symbol}_Midline_Touch", 
                "Elephant Midline Touch", 
                symbol, 
                f"Price touched Dotted Midline at `${mid_to_check:.2f}`", 
                live_close, live_rsi_5m, live_rsi_15m
            )

    # ----------------------------------------------------------
    # SIGNAL 3: GANN NUMBER LEVEL TOUCHES (Matching Pine Script Formula)
    # ----------------------------------------------------------
    prev_close = MANUAL_PREV_CLOSES.get(symbol)
    if prev_close:
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

# ==========================================
# RUNTIME SCANNER LIFECYCLE
# ==========================================
def core_market_scanner_loop():
    print(f"Global Macro Market Scanner Online...")
    send_telegram_message("🚀 *Focused Signal Engine Online* 🚀\n• Enabled Alerts ONLY for:\n  1. Gann Numbers\n  2. MTF Operator OC Candles (15M, 1H, 4H, 1D)\n  3. Elephant Zone Touches\n  4. Strategy TP Bubble Recommendations (15M, 1H, 4H, 1D)")
    
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
