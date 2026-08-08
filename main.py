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
    return f"Bot Matrix Status: ONLINE | Focused Scanner Active (Gann, MTF OC, Elephant Zones)", 200

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# 🚨 CREDENTIALS & HOOKS 🚨
# ==========================================
TELEGRAM_TOKEN = "8992095386:AAFexnI8IRh990PlwZtkn6WkjeOV0yHjkCE"

TELEGRAM_CHAT_IDS = [
    "-5385748601",  # 📡Signal Telegram Group
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

# Updated to match the latest Pine Script and chart values
MANUAL_PREV_CLOSES = {
    "BTC-USD": 64859,
    "ETH-USD": 1912,
    "PAXG-USD": 4341
}

# ==========================================
# 🐘 ELEPHANT EDGE CONFIGURATIONS (UPDATED LEVELS)
# ==========================================
ELEPHANT_EDGE_LEVELS = {
    "BTC-USD": {
        "Supply 2": {"top": 66014.88, "bottom": 65762.99},
        "Supply 1": {"top": 65299.25, "bottom": 65149.40},
        "Midline": 64763.54,
        "Demand 1": {"top": 64568.12, "bottom": 64418.27},
        "Demand 2": {"top": 63954.53, "bottom": 63702.64}
    },
    "ETH-USD": {
        "Supply 2": {"top": 1957.75, "bottom": 1947.84},
        "Supply 1": {"top": 1929.61, "bottom": 1923.72},
        "Midline": 1914.09,
        "Demand 1": {"top": 1900.86, "bottom": 1894.97},
        "Demand 2": {"top": 1876.74, "bottom": 1866.83}
    },
    "PAXG-USD": {
        "Supply 2": {"top": 4391.33, "bottom": 4380.31},
        "Supply 1": {"top": 4360.03, "bottom": 4353.48},
        "Midline": 4306.93,
        "Demand 1": {"top": 4328.06, "bottom": 4321.51},
        "Demand 2": {"top": 4301.23, "bottom": 4290.21}
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
        history = ticker.history(period="7d", interval="5m")
        if history.empty: return None
            
        df = history.reset_index()
        df.rename(columns={"Datetime": "timestamp", "Date": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}, inplace=True)
        return df.tail(limit).copy()
    except Exception as e:
        return None

# ==========================================
# CORE ALERT PROCESSOR & DUAL ANTI-SPAM
# ==========================================
def process_alert(alert_key, alert_type, symbol, message, price=None, rsi_5m=None, rsi_15m=None):
    global tg_alert_cache, sms_alert_cache
    now = datetime.now(timezone.utc)
    
    display_name = DISPLAY_NAMES.get(symbol, symbol)
    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A"
    rsi_5m_str = f"{rsi_5m:.2f}" if isinstance(rsi_5m, (int, float)) and not pd.isna(rsi_5m) else "N/A"
    rsi_15m_str = f"{rsi_15m:.2f}" if isinstance(rsi_15m, (int, float)) and not pd.isna(rsi_15m) else "N/A"

    # Telegram Dispatch
    tg_cooldown = 1800  # 30 minutes cooldown
    send_tg = False

    if alert_key not in tg_alert_cache:
        send_tg = True
    elif (now - tg_alert_cache[alert_key]).total_seconds() >= tg_cooldown:
        send_tg = True

    if send_tg:
        tg_alert_cache[alert_key] = now
        
        if "Demand" in alert_type or "Bull" in alert_type:
            header = f"🟢 *[MACRO BUY SIGNAL]* 🟢"
        elif "Supply" in alert_type or "Bear" in alert_type:
            header = f"🔴 *[MACRO SELL SIGNAL]* 🔴"
        else:
            header = f"🟡 *[GANN / ZONE SIGNAL]* 🟡"
            
        tg_message = (
            f"{header}\n\n"
            f"• *Asset:* `{display_name}`\n"
            f"• *Price:* `{price_str}`\n"
            f"• *RSI (5M):* `{rsi_5m_str}`\n"
            f"• *RSI (15M):* `{rsi_15m_str}`\n"
            f"• *Signal Type:* `{alert_type}`\n"
            f"• *Details:* {message}"
        )
        send_telegram_message(tg_message)

    # SMS / Make Webhook Dispatch
    sms_cooldown = 3600  # 1 hour cooldown
    send_sms = False

    if alert_key not in sms_alert_cache:
        send_sms = True
    elif (now - sms_alert_cache[alert_key]).total_seconds() >= sms_cooldown:
        send_sms = True

    if send_sms:
        sms_alert_cache[alert_key] = now
        alert_text = f"ALERT: {display_name} | {alert_type} | Price: {price_str} | RSI(15M): {rsi_15m_str}"
        sms_payload = {
            "body": alert_text,
            "text": alert_text,
            "message": alert_text
        }
        send_make_webhook(sms_payload)

# ==========================================
# MULTI-TIMEFRAME OPERATOR CANDLE (OC) EVALUATOR
# ==========================================
def evaluate_operator_oc_mtf(df_tf, tf_label, symbol, rsi_5m, rsi_15m):
    """
    Evaluates Operator Candle (OC) Setup for specific timeframe:
    - Minimum move percentage: pct_thresh = 0.5%
    - Bullish OC: Previous Red, Engulfing Green, 50 < RSI < 70
    - Bearish OC: Previous Green, Engulfing Red, 30 < RSI < 50
    """
    if len(df_tf) < 3:
        return

    df_tf['rsi'] = ta.rsi(df_tf['close'], length=14, mamode='rma')
    curr = df_tf.iloc[-1]
    prev = df_tf.iloc[-2]

    curr_open, curr_close = curr['open'], curr['close']
    curr_high, curr_low = curr['high'], curr['low']
    prev_open, prev_close = prev['open'], prev['close']
    rsi_tf = curr['rsi']

    if pd.isna(rsi_tf):
        return

    pct_thresh = 0.005  # 0.5% Minimum Move

    # Bullish Operator Candle
    is_prev_red = prev_close < prev_open
    is_curr_green = curr_close > curr_open
    green_move_pct = (curr_close - curr_low) / curr_low if curr_low > 0 else 0
    is_engulfing_bull = (curr_open <= prev_close) and (curr_close > prev_open)

    bull_oc = is_prev_red and is_curr_green and is_engulfing_bull and (green_move_pct >= pct_thresh) and (50.0 < rsi_tf < 70.0)

    if bull_oc:
        alert_key = f"{symbol}_{tf_label}_OC_BULL_{curr.name}"
        process_alert(
            alert_key, 
            f"{tf_label} Operator Bull OC Candle 🕯️", 
            symbol, 
            f"{tf_label} Bullish OC Reversal Detected! Move: `{green_move_pct*100:.2f}%`, {tf_label} RSI: `{rsi_tf:.2f}`", 
            curr_close, rsi_5m, rsi_15m
        )

    # Bearish Operator Candle
    is_prev_green = prev_close > prev_open
    is_curr_red = curr_close < curr_open
    red_move_pct = (curr_high - curr_close) / curr_high if curr_high > 0 else 0
    is_engulfing_bear = (curr_open >= prev_close) and (curr_close < prev_open)

    bear_oc = is_prev_green and is_curr_red and is_engulfing_bear and (red_move_pct >= pct_thresh) and (30.0 < rsi_tf < 50.0)

    if bear_oc:
        alert_key = f"{symbol}_{tf_label}_OC_BEAR_{curr.name}"
        process_alert(
            alert_key, 
            f"{tf_label} Operator Bear OC Candle 🕯️", 
            symbol, 
            f"{tf_label} Bearish OC Reversal Detected! Move: `{red_move_pct*100:.2f}%`, {tf_label} RSI: `{rsi_tf:.2f}`", 
            curr_close, rsi_5m, rsi_15m
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
    # SIGNAL 1: MTF OPERATOR OC CANDLE (15M, 1H, 4H, 1D)
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
    # SIGNAL 3: GANN NUMBER LEVEL TOUCHES
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
    send_telegram_message("🚀 *Focused Signal Engine Online* 🚀\n• Enabled Alerts ONLY for:\n  1. Gann Numbers\n  2. MTF Operator OC Candles (15M, 1H, 4H, 1D)\n  3. Elephant Zone Touches")
    
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
