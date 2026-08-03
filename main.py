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
    return f"Bot Status: ONLINE | Scanner Active", 200

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# 🚨 CREDENTIALS & HOOKS 🚨
# ==========================================
TELEGRAM_TOKEN = "8992095386:AAFexnI8IRh990PlwZtkn6WkjeOV0yHjkCE"

# 👥 MULTI-TARGET TELEGRAM DISPATCH LIST
TELEGRAM_CHAT_IDS = [
    "-5385748601",  # 📡Signal Telegram Group
    "1136613703"    # Personal Backup
]

# 🔗 MAKE.COM WEBHOOK URL
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

# ⚠️ GANN BASE PREVIOUS CLOSES
MANUAL_PREV_CLOSES = {
    "BTC-USD": 63506,
    "ETH-USD": 1883,
    "PAXG-USD": 4068
}

# 🐘 ELEPHANT EDGE CONFIGURATIONS (ALL UPDATED LEVELS)
ELEPHANT_EDGE_LEVELS = {
    "BTC-USD": {
        "Supply 2": {"top": 64755.64, "bottom": 64483.42},
        "Supply 1": {"top": 63982.27, "bottom": 63820.33},
        "Demand 1": {"top": 63192.15, "bottom": 63030.21},
        "Demand 2": {"top": 62529.06, "bottom": 62256.84},
        "Midline": 63326.90
    },
    "ETH-USD": {
        "Supply 2": {"top": 1935.39, "bottom": 1924.06},
        "Supply 1": {"top": 1903.21, "bottom": 1896.48},
        "Demand 1": {"top": 1870.34, "bottom": 1863.61},
        "Demand 2": {"top": 1842.76, "bottom": 1831.43},
        "Midline": 1873.94
    },
    "PAXG-USD": {
        "Supply 2": {"top": 4117.11, "bottom": 4106.39},
        "Supply 1": {"top": 4086.65, "bottom": 4080.27},
        "Demand 1": {"top": 4055.53, "bottom": 4049.15},
        "Demand 2": {"top": 4029.41, "bottom": 4018.69},
        "Midline": 4062.27
    }
}

tg_alert_cache = {}
sms_alert_cache = {}

# ==========================================
# DISPATCH PIPELINES
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
    except Exception as e:
        return None

# ==========================================
# CORE ALERT PROCESSOR (MASKED & SMS FIX)
# ==========================================
def process_alert(alert_key, alert_type, symbol, price=None):
    global tg_alert_cache, sms_alert_cache
    now = datetime.now(timezone.utc)
    
    display_name = DISPLAY_NAMES.get(symbol, symbol)
    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A"

    # ==========================================================
    # 1. TELEGRAM DISPATCH (Masked Output)
    # ==========================================================
    tg_cooldown = 3600  # 1 hour = 3,600 seconds
    send_tg = False

    if alert_key not in tg_alert_cache:
        send_tg = True
    elif (now - tg_alert_cache[alert_key]).total_seconds() >= tg_cooldown:
        send_tg = True

    if send_tg:
        tg_alert_cache[alert_key] = now
        
        # Categorize without exposing strategy math
        if "Demand" in alert_type or "Bull" in alert_type or "Base" in alert_type:
            action_header = "🟢 *[LONG SIGNAL MATCHED]* 🟢"
            signal_mode = "BUY / ACCUMULATION"
        elif "Supply" in alert_type or "Bear" in alert_type:
            action_header = "🔴 *[SHORT SIGNAL MATCHED]* 🔴"
            signal_mode = "SELL / DISTRIBUTION"
        else:
            action_header = "⚡ *[KEY LEVEL TESTED]* ⚡"
            signal_mode = "ZONE REACTION"
            
        tg_message = (
            f"{action_header}\n\n"
            f"• *Asset:* `{display_name}`\n"
            f"• *Current Price:* `{price_str}`\n"
            f"• *Action:* `{signal_mode}`\n"
            f"• *Timeframe:* `15M / Global`\n"
            f"• *Status:* `Active Confirmation`"
        )
        send_telegram_message(tg_message)

    # ==========================================================
    # 2. MOBILE SMS DISPATCH
    # ==========================================================
    if "Supply" in alert_type or "Demand" in alert_type:
        sms_cooldown = 14400  # 4 hours = 14,400 seconds
        send_sms = False

        if alert_key not in sms_alert_cache:
            send_sms = True
        elif (now - sms_alert_cache[alert_key]).total_seconds() >= sms_cooldown:
            send_sms = True

        if send_sms:
            sms_alert_cache[alert_key] = now
            alert_text = f"MARKET SIGNAL: {display_name} | Price: {price_str} | Action: {signal_mode}"
            
            sms_payload = {
                "body": alert_text,
                "text": alert_text,
                "message": alert_text
            }
            send_make_webhook(sms_payload)

# ==========================================
# STRATEGY ANALYSIS
# ==========================================
def analyze_market(df_5m, symbol):
    if len(df_5m) < 45: return
    
    live_low = df_5m['low'].iloc[-1]
    live_high = df_5m['high'].iloc[-1]
    live_close = df_5m['close'].iloc[-1]

    # Elephant Edge Evaluation
    if symbol in ELEPHANT_EDGE_LEVELS:
        levels = ELEPHANT_EDGE_LEVELS[symbol]
        
        for key, limits in levels.items():
            if key == "Midline": continue
            if live_high >= limits["bottom"] and live_low <= limits["top"]:
                process_alert(f"{symbol}_{key.replace(' ', '_')}_Touch", f"{key} Tested", symbol, live_close)
                
        mid_to_check = levels.get("Midline")
        midline_buffer = 15.0 if symbol == "BTC-USD" else 1.5
        
        if mid_to_check and (live_high >= (mid_to_check - midline_buffer)) and (live_low <= (mid_to_check + midline_buffer)):
            process_alert(f"{symbol}_Midline_Touch", "Midline Tested", symbol, live_close)

    # Gann Evaluation
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
                process_alert(f"{symbol}_Gann_{g_name.replace(' ', '_')}", f"Gann {g_name}", symbol, live_close)

# ==========================================
# RUNTIME SCANNER LIFECYCLE
# ==========================================
def core_market_scanner_loop():
    print("Global Market Scanner Online...")
    
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
