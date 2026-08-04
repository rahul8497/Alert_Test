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
    return f"Bot Matrix Status: ONLINE | Focused Scanner Active (Gann, 15M OC, Zone Touches)", 200

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# 🚨 CREDENTIALS & HOOKS 🚨
# ==========================================
TELEGRAM_TOKEN = "8992095386:AAFexnI8IRh990PlwZtkn6WkjeOV0yHjkCE"

TELEGRAM_CHAT_IDS = [
    "-5385748601",  # 📡Signal Telegram Group
    "1136613703"    # Your personal Telegram ID (Backup)
]

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

# EXACT VALUES MATCHING TRADINGVIEW GANN BASE LEVELS
MANUAL_PREV_CLOSES = {
    "BTC-USD": 63455,
    "ETH-USD": 1859,
    "PAXG-USD": 4048
}

# ==========================================
# 🐘 ELEPHANT EDGE CONFIGURATIONS (EXACT LEVELS)
# ==========================================
ELEPHANT_EDGE_LEVELS = {
    "BTC-USD": {
        "Supply 2": {"top": 64719.16, "bottom": 64443.88},
        "Supply 1": {"top": 63937.08, "bottom": 63773.32},
        "Demand 1": {"top": 63138.06, "bottom": 62974.30},
        "Demand 2": {"top": 62467.50, "bottom": 62192.27},
        "Midline": 63232.35
    },
    "ETH-USD": {
        "Supply 2": {"top": 1910.80, "bottom": 1899.40},
        "Supply 1": {"top": 1878.43, "bottom": 1871.65},
        "Demand 1": {"top": 1845.35, "bottom": 1838.57},
        "Demand 2": {"top": 1817.60, "bottom": 1806.20},
        "Midline": 1856.60
    },
    "PAXG-USD": {
        "Supply 2": {"top": 4096.54, "bottom": 4085.87},
        "Supply 1": {"top": 4066.23, "bottom": 4059.89},
        "Demand 1": {"top": 4035.27, "bottom": 4028.93},
        "Demand 2": {"top": 4009.29, "bottom": 3998.62},
        "Midline": 4045.17
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
# CORE ALERT PROCESSOR & DUAL ANTI-SPAM
# ==========================================
def process_alert(alert_key, alert_type, symbol, message, price=None, rsi_5m=None, rsi_15m=None):
    global tg_alert_cache, sms_alert_cache
    now = datetime.now(timezone.utc)
    
    display_name = DISPLAY_NAMES.get(symbol, symbol)
    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A"
    rsi_5m_str = f"{rsi_5m:.2f}" if isinstance(rsi_5m, (int, float)) and not pd.isna(rsi_5m) else "N/A"
    rsi_15m_str = f"{rsi_15m:.2f}" if isinstance(rsi_15m, (int, float)) and not pd.isna(rsi_15m) else "N/A"

    # ==========================================================
    # 1. TELEGRAM DISPATCH
    # ==========================================================
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

    # ==========================================================
    # 2. MOBILE SMS DISPATCH (Webhook for Make.com)
    # ==========================================================
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
# SIGNAL 1: 15-MINUTE OC (ELEPHANT) CANDLE
# ==========================================
def evaluate_elephant_candle_15m(df_15m, symbol, rsi_5m, rsi_15m):
    if len(df_15m) < 105:
        return

    df_15m['ma_fast'] = ta.sma(df_15m['close'], length=8)
    df_15m['atr'] = ta.atr(df_15m['high'], df_15m['low'], df_15m['close'], length=100)

    curr = df_15m.iloc[-1]
    prev_atr = df_15m['atr'].iloc[-2]

    open_p = curr['open']
    close_p = curr['close']
    high_p = curr['high']
    low_p = curr['low']

    body_size = abs(close_p - open_p)
    candle_range = abs(high_p - low_p)

    if candle_range == 0 or pd.isna(prev_atr):
        return

    body_percentage = (body_size * 100.0) / candle_range

    is_bull = close_p > open_p
    is_bear = close_p < open_p

    body_valid = body_percentage >= 70.0
    atr_valid = body_size >= (prev_atr * 1.3)

    fast_ma_rising = df_15m['ma_fast'].iloc[-1] > df_15m['ma_fast'].iloc[-2]
    fast_ma_falling = df_15m['ma_fast'].iloc[-1] < df_15m['ma_fast'].iloc[-2]

    # Bullish OC Candle Trigger
    if is_bull and body_valid and atr_valid and fast_ma_rising:
        alert_key = f"{symbol}_15M_BULL_ELEPHANT_{curr.name}"
        process_alert(
            alert_key, 
            "15M Bullish Elephant Candle 🐘", 
            symbol, 
            f"15M OC Candle Formed! Body Ratio: `{body_percentage:.1f}%`, Range: `${candle_range:.2f}`", 
            close_p, rsi_5m, rsi_15m
        )

    # Bearish OC Candle Trigger
    if is_bear and body_valid and atr_valid and fast_ma_falling:
        alert_key = f"{symbol}_15M_BEAR_ELEPHANT_{curr.name}"
        process_alert(
            alert_key, 
            "15M Bearish Elephant Candle 🐘", 
            symbol, 
            f"15M OC Candle Formed! Body Ratio: `{body_percentage:.1f}%`, Range: `${candle_range:.2f}`", 
            close_p, rsi_5m, rsi_15m
        )

# ==========================================
# MAIN SCANNER ROUTINE (3 SIGNALS ONLY)
# ==========================================
def analyze_market(df_5m, symbol):
    if len(df_5m) < 45: return
    
    # Calculate RSI
    df_5m['rsi_5m'] = ta.rsi(df_5m['close'], length=14, mamode='rma')
    
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

    # ----------------------------------------------------------
    # SIGNAL 1: 15-MINUTE OC (ELEPHANT) CANDLE FORMATION
    # ----------------------------------------------------------
    evaluate_elephant_candle_15m(df_15m, symbol, live_rsi_5m, live_rsi_15m)

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
    send_telegram_message("🚀 *Focused Signal Engine Online* 🚀\n• Enabled Alerts ONLY for:\n  1. Gann Numbers\n  2. 15M OC (Elephant) Candles\n  3. Elephant Zone Touches")
    
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
