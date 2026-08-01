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
    return f"Bot Matrix Status: ONLINE | Elephant Edge & Gann Scanner Active", 200

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# 🚨 CREDENTIALS & HOOKS 🚨
# ==========================================
TELEGRAM_TOKEN = "8992095386:AAFexnI8IRh990PlwZtkn6WkjeOV0yHjkCE"
TELEGRAM_CHAT_ID = "1136613703"

# 🔗 YOUR MAKE.COM WEBHOOK URL
MAKE_WEBHOOK_URL = "https://hook.us2.make.com/ztcvn6rzkkidnnwyn2c7imhtgz1yr3sw"

# ==========================================
# 📋 WATCHLIST & PREV CLOSE SYNC
# ==========================================
ACTIVE_SYMBOLS = ["BTC-USD", "ETH-USD", "PAXG-USD"]
DISPLAY_NAMES = {
    "BTC-USD": "BITCOIN (BTC/USD)",
    "ETH-USD": "ETHEREUM (ETH/USD)",
    "PAXG-USD": "GOLD SPOT (PAXG/USD)"
}

# ⚠️ EXACT VALUES EXTRACTED FROM YOUR TRADINGVIEW CHARTS
MANUAL_PREV_CLOSES = {
    "BTC-USD": 62834, 
    "ETH-USD": 1861,  
    "PAXG-USD": 4044  
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
        "Midline": 63054.09
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

alert_state_cache = {} # Used for 5-minute cooldown tracking

# ==========================================
# DISPATCH PIPELINES (TELEGRAM & MAKE.COM)
# ==========================================
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Network error sending Telegram notification: {e}")

def send_make_webhook(alert_data):
    try:
        requests.post(MAKE_WEBHOOK_URL, json=alert_data, timeout=10)
    except Exception as e:
        print(f"Network error sending Make Webhook: {e}")

# ==========================================
# DATA FETCHING PIPELINE
# ==========================================
def fetch_candles(symbol, limit=200):
    try:
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="5d", interval="5m")
        if history.empty: return None
            
        df = history.reset_index()
        df.rename(columns={"Datetime": "timestamp", "Date": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}, inplace=True)
        return df.tail(limit).copy()
    except: return None

# ==========================================
# CORE ALERT PROCESSOR & ANTI-SPAM
# ==========================================
def process_alert(alert_key, alert_type, symbol, message, price=None, rsi_5m=None, rsi_15m=None):
    global alert_state_cache
    now = datetime.now(timezone.utc)
    
    # 🛑 5-MINUTE COOLDOWN ANTI-SPAM LOGIC
    if alert_key in alert_state_cache:
        last_alert_time = alert_state_cache[alert_key]
        if (now - last_alert_time).total_seconds() < 300: # 300 seconds = 5 Minutes
            return  
            
    alert_state_cache[alert_key] = now
    
    display_name = DISPLAY_NAMES.get(symbol, symbol)
    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A"
    
    rsi_5m_str = f"{rsi_5m:.2f}" if isinstance(rsi_5m, (int, float)) and not pd.isna(rsi_5m) else "N/A"
    rsi_15m_str = f"{rsi_15m:.2f}" if isinstance(rsi_15m, (int, float)) and not pd.isna(rsi_15m) else "N/A"
    
    if "Demand" in alert_type or "Bull" in alert_type or "Base" in alert_type:
        header = f"🟢 *[MACRO BUY SIGNAL MATCHED]* 🟢"
    elif "Supply" in alert_type or "Bear" in alert_type:
        header = f"🔴 *[MACRO SELL SIGNAL MATCHED]* 🔴"
    else:
        header = f"🟡 *[MACRO ZONE ALERT MATCHED]* 🟡"
    
    # 1. Dispatch to Telegram
    tg_message = (
        f"{header}\n\n"
        f"• *Asset:* `{display_name}`\n"
        f"• *Price:* `{price_str}`\n"
        f"• *RSI (5M):* `{rsi_5m_str}`\n"
        f"• *RSI (15M):* `{rsi_15m_str}`\n"
        f"• *Timeframe:* `GLOBAL (Live)`\n"
        f"• *Signal:* `{alert_type}`\n"
        f"• *Context:* {message}"
    )
    send_telegram_message(tg_message)

    # 2. Dispatch to Make.com Webhook (Triggers Twilio SMS)
    # 🟢 SENDS BOTH 'body' AND 'text' TO PREVENT MISSING KEY ERRORS IN MAKE.COM
    alert_text = f"TRADING ALERT: {display_name} | Signal: {alert_type} | Price: {price_str} | RSI(5M): {rsi_5m_str} | RSI(15M): {rsi_15m_str}"
    
    sms_payload = {
        "body": alert_text,
        "text": alert_text
    }
    send_make_webhook(sms_payload)

# ==========================================
# STRATEGY ANALYSIS: GANN & ELEPHANT EDGE ONLY
# ==========================================
def analyze_market(df_5m, symbol):
    if len(df_5m) < 45: return
    
    # 1. Calculate 5M RSI
    df_5m['rsi_5m'] = ta.rsi(df_5m['close'], length=14, mamode='rma')
    
    # 2. Resample 5M to 15M to Calculate 15M RSI
    df_temp = df_5m.copy()
    df_temp.set_index('timestamp', inplace=True)
    df_15m = df_temp.resample('15min').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    
    df_15m['rsi_15m'] = ta.rsi(df_15m['close'], length=14, mamode='rma')
    
    live_low = df_5m['low'].iloc[-1]
    live_high = df_5m['high'].iloc[-1]
    live_close = df_5m['close'].iloc[-1]
    
    live_rsi_5m = df_5m['rsi_5m'].iloc[-1]
    live_rsi_15m = df_15m['rsi_15m'].iloc[-1] if not df_15m.empty else np.nan

    # ==========================================================
    # 🐘 ASSET-SPECIFIC ELEPHANT EDGE LOGIC
    # ==========================================================
    if symbol in ELEPHANT_EDGE_LEVELS:
        levels = ELEPHANT_EDGE_LEVELS[symbol]
        
        for key, limits in levels.items():
            if key == "Midline": continue
            if live_high >= limits["bottom"] and live_low <= limits["top"]:
                process_alert(
                    f"{symbol}_{key.replace(' ', '_')}_Touch", f"{key} Tested", symbol, 
                    f"Price interacted with {key}: `[${limits['bottom']:.2f} - ${limits['top']:.2f}]`", live_close, live_rsi_5m, live_rsi_15m
                )
                
        # Midline with $15 buffer for BTC
        mid_to_check = levels.get("Midline")
        midline_buffer = 15.0 if symbol == "BTC-USD" else 1.5
        
        if mid_to_check and (live_high >= (mid_to_check - midline_buffer)) and (live_low <= (mid_to_check + midline_buffer)):
            process_alert(
                f"{symbol}_Midline_Touch", "Elephant Edge Midline Tested", symbol, 
                f"Price touched the Dotted Midline at `${mid_to_check:.2f}`", live_close, live_rsi_5m, live_rsi_15m
            )

    # ==========================================================
    # 🧮 DYNAMIC GANN LOGIC
    # ==========================================================
    prev_close = MANUAL_PREV_CLOSES.get(symbol)
    if prev_close:
        base_sqrt = round(math.sqrt(prev_close))
        
        gann_levels = {
            "Base Level": base_sqrt ** 2, 
            "First Target (FT)": 63069.09 if symbol == "BTC-USD" else (base_sqrt + 0.27) ** 2,
            "Second Target (ST)": 63135.26 if symbol == "BTC-USD" else (base_sqrt + 0.53) ** 2,
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
                    f"{symbol}_Gann_{g_name.replace(' ', '_').replace('(', '').replace(')', '')}", f"Gann Level Tested", symbol, 
                    f"Price tested Gann {g_name} at `${g_level:.2f}`", live_close, live_rsi_5m, live_rsi_15m
                )

# ==========================================
# RUNTIME SCANNER LIFECYCLE
# ==========================================
def core_market_scanner_loop():
    print(f"Global Macro Market Scanner Online...")
    send_telegram_message("🚀 *Macro Watchlist Engine Online* 🚀\n• Scanning Crypto & Gold 24/7\n• STRICT MODE: Elephant Edge & Gann Levels Only (Telegram + Mobile SMS Active).")
    
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
