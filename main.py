import time
import threading
import os
import datetime
import math
import pandas as pd
import numpy as np
import requests
import yfinance as yf
from flask import Flask

# ==========================================
# 🟢 FLASK HEARTBEAT WEB SERVER FOR RENDER
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return f"Bot Matrix Status: ONLINE | Elephant Edge & Gann Scanner Active", 200

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# 🚨 TELEGRAM CREDENTIALS 🚨
# ==========================================
TELEGRAM_TOKEN = "8992095386:AAFexnI8IRh990PlwZtkn6WkjeOV0yHjkCE"
TELEGRAM_CHAT_ID = "1136613703"

# ==========================================
# 📋 WATCHLIST
# ==========================================
ACTIVE_SYMBOLS = ["BTC-USD", "ETH-USD", "PAXG-USD"]
DISPLAY_NAMES = {
    "BTC-USD": "BITCOIN (BTC/USD)",
    "ETH-USD": "ETHEREUM (ETH/USD)",
    "PAXG-USD": "GOLD SPOT (PAXG/USD)"
}

# ==========================================
# 🐘 ELEPHANT EDGE CONFIGURATIONS (PER ASSET)
# ==========================================
ELEPHANT_EDGE_LEVELS = {
    "BTC-USD": {
        "Supply 1": {"top": 64032.17, "bottom": 63771.13},
        "Supply 2": {"top": 63290.55, "bottom": 63135.26},
        "Demand 1": {"top": 62532.86, "bottom": 62377.57},
        "Demand 2": {"top": 61896.99, "bottom": 61635.95},
        "Midline": 63535.31
    },
    "ETH-USD": {
        "Supply 1": {"top": 1912.00, "bottom": 1900.87},
        "Supply 2": {"top": 1880.38, "bottom": 1873.76},
        "Demand 1": {"top": 1848.08, "bottom": 1841.46},
        "Demand 2": {"top": 1820.97, "bottom": 1809.84},
        "Midline": 1881.16
    },
    "PAXG-USD": {
        "Supply 1": {"top": 4092.82, "bottom": 4082.27},
        "Supply 2": {"top": 4062.84, "bottom": 4056.56},
        "Demand 1": {"top": 4032.20, "bottom": 4025.92},
        "Demand 2": {"top": 4006.49, "bottom": 3995.94},
        "Midline": 4054.00
    }
}

DAILY_CACHE = {} 
LAST_DAILY_FETCH = None
TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"] 
alert_state_cache = {}

# ==========================================
# TELEGRAM DISPATCH PIPELINE
# ==========================================
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Network error sending Telegram notification: {e}")

# ==========================================
# MATHEMATICAL RESAMPLING ENGINE
# ==========================================
def resample_to_4h(df_1h):
    try:
        if df_1h is None or df_1h.empty: return None
        df_1h = df_1h.set_index('timestamp')
        resample_rules = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
        df_4h = df_1h.resample('4h', closed='left', label='left').agg(resample_rules).dropna(subset=['close']).reset_index()
        return df_4h
    except: return None

# ==========================================
# DATA FETCHING PIPELINE
# ==========================================
def fetch_candles(symbol, timeframe, limit=100):
    try:
        target_tf = "60m" if timeframe == "4h" else timeframe
        yf_tf_map = {"1m": "1m", "3m": "2m", "5m": "5m", "15m": "15m", "1h": "60m", "1d": "1d"}
        yf_tf = yf_tf_map.get(target_tf, "15m")
        period_map = {"1m": "1d", "2m": "1d", "5m": "5d", "15m": "5d", "60m": "14d", "1d": "3mo"}
        fetch_period = "14d" if timeframe == "4h" else period_map.get(yf_tf, "5d")
        
        ticker = yf.Ticker(symbol)
        history = ticker.history(period=fetch_period, interval=yf_tf)
        if history.empty: return None
            
        df = history.reset_index()
        df.rename(columns={"Datetime": "timestamp", "Date": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}, inplace=True)
        if timeframe == "4h":
            df = resample_to_4h(df)
            if df is None: return None
        return df.tail(limit).copy()
    except: return None

# ==========================================
# CORE ALERT PROCESSOR
# ==========================================
def process_alert(alert_key, current_timestamp, alert_type, symbol, timeframe, message, price=None):
    global alert_state_cache
    live_tracking_key = f"{alert_key}_{current_timestamp}"
    if alert_state_cache.get(live_tracking_key): return  
    alert_state_cache[live_tracking_key] = True
    
    display_name = DISPLAY_NAMES.get(symbol, symbol)
    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A"
    
    if "Demand" in alert_type or "Bull" in alert_type or "Support" in alert_type:
        header = f"🟢 *[MACRO BUY SIGNAL MATCHED]* 🟢"
    elif "Supply" in alert_type or "Bear" in alert_type or "Resistance" in alert_type:
        header = f"🔴 *[MACRO SELL SIGNAL MATCHED]* 🔴"
    else:
        header = f"🟡 *[MACRO ZONE ALERT MATCHED]* 🟡"
    
    tg_message = (
        f"{header}\n\n"
        f"• *Asset:* `{display_name}`\n"
        f"• *Price:* `{price_str}`\n"
        f"• *Timeframe:* `{timeframe.upper()}`\n"
        f"• *Signal:* `{alert_type}`\n"
        f"• *Context:* {message}"
    )
    send_telegram_message(tg_message)

# ==========================================
# STRATEGY ANALYSIS: GANN & ELEPHANT EDGE ONLY
# ==========================================
def analyze_market(df, symbol):
    global DAILY_CACHE
    if len(df) < 5: return
    
    tf = df.timeframe_meta
    live_low = df['low'].iloc[-1]
    live_high = df['high'].iloc[-1]
    live_close = df['close'].iloc[-1]
    current_timestamp = str(df['timestamp'].iloc[-1])

    # ==========================================================
    # 🐘 ASSET-SPECIFIC ELEPHANT EDGE LOGIC
    # ==========================================================
    if symbol in ELEPHANT_EDGE_LEVELS:
        levels = ELEPHANT_EDGE_LEVELS[symbol]
        
        # Check Box Zones (Supply 1/2, Demand 1/2)
        for key, limits in levels.items():
            if key == "Midline": continue
            if live_high >= limits["bottom"] and live_low <= limits["top"]:
                process_alert(
                    f"{symbol}_{tf}_{key.replace(' ', '_')}_Touch", current_timestamp, f"{key} Tested", symbol, tf, 
                    f"Price interacted with {key}: `[${limits['bottom']:.2f} - ${limits['top']:.2f}]`", live_close
                )
                
        # Check Dotted Midline
        mid_to_check = levels.get("Midline")
        if mid_to_check and live_high >= mid_to_check and live_low <= mid_to_check:
            process_alert(
                f"{symbol}_{tf}_Midline_Touch", current_timestamp, "Elephant Edge Midline Tested", symbol, tf, 
                f"Price touched the Dotted Midline at `${mid_to_check:.2f}`", live_close
            )

    # ==========================================================
    # 🧮 DYNAMIC GANN LOGIC
    # ==========================================================
    prev_close = DAILY_CACHE.get(symbol)
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
        
        # 0.05% buffer for single line touch detection
        buffer = live_close * 0.0005 
        
        for g_name, g_level in gann_levels.items():
            if live_high >= (g_level - buffer) and live_low <= (g_level + buffer):
                process_alert(
                    f"{symbol}_{tf}_Gann_{g_name.replace(' ', '_')}", current_timestamp, f"Gann Level Tested", symbol, tf, 
                    f"Price tested Gann {g_name} at `${g_level:.2f}`", live_close
                )

# ==========================================
# RUNTIME SCANNER LIFECYCLE
# ==========================================
def core_market_scanner_loop():
    global LAST_DAILY_FETCH, DAILY_CACHE
    print(f"Global Macro Market Scanner Online...")
    send_telegram_message("🚀 *Macro Watchlist Engine Online* 🚀\n• Scanning Crypto & Gold 24/7\n• STRICT MODE: Elephant Edge & Gann Levels Only.")
    
    while True:
        try:
            current_date = datetime.datetime.utcnow().date()
            if current_date != LAST_DAILY_FETCH:
                print("Fetching Daily closes for Gann Math...")
                for symbol in ACTIVE_SYMBOLS:
                    daily_df = fetch_candles(symbol, "1d", limit=2)
                    if daily_df is not None and len(daily_df) > 1: DAILY_CACHE[symbol] = daily_df['close'].iloc[-2] 
                LAST_DAILY_FETCH = current_date

            for symbol in ACTIVE_SYMBOLS:
                for tf in TIMEFRAMES:
                    df = fetch_candles(symbol, tf)
                    if df is not None and not df.empty:
                        df.timeframe_meta = tf
                        analyze_market(df, symbol)
                        
            time.sleep(15)
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    scanner_thread = threading.Thread(target=core_market_scanner_loop, daemon=True)
    scanner_thread.start()
    run_web_server()
