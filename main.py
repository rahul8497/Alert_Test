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
    return f"Bot Matrix Status: ONLINE | Focused Scanner Active", 200

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

# Live fetch functions
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

# ==========================================
# 🐘 ADSZ ELEPHANT ZONE ENGINE
# ==========================================
def calculate_adsz_levels(df_1d, d_atr_period=20, d_slope=0.69, d_intercept=0.0):
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

        phi = 1.618034
        sqrt2 = math.sqrt(2)
        sqrt252 = math.sqrt(252)

        atr_ann_pct = (day_atr / day_close_prev) * sqrt252 * 100.0
        effvol = (d_slope * atr_ann_pct) + d_intercept
        
        P = round(day_open)
        sigma = (P * effvol) / (100.0 * sqrt252)
        dist_strong = sigma
        dist_weak = sigma / (2.0 * sqrt2)
        
        ws = round(sigma / 4.0)
        ww = round(sigma / (4.0 * phi))

        sd_low   = round(P - dist_strong - (ws / 2.0))
        sd_high  = round(P - dist_strong + (ws / 2.0))
        wd_low   = round(P - dist_weak - (ww / 2.0))
        wd_high  = round(P - dist_weak + (ww / 2.0))
        wsp_low  = round(P + dist_weak - (ww / 2.0))
        wsp_high = round(P + dist_weak + (ww / 2.0))
        ss_low   = round(P + dist_strong - (ws / 2.0))
        ss_high  = round(P + dist_strong + (ws / 2.0))
        
        dpoc = round((day_high_prev + day_low_prev + day_close_prev) / 3.0)

        return {
            "Supply 2": {"top": float(ss_high), "bottom": float(ss_low)},
            "Supply 1": {"top": float(wsp_high), "bottom": float(wsp_low)},
            "Daily Midline": float(dpoc),
            "Demand 1": {"top": float(wd_high), "bottom": float(wd_low)},
            "Demand 2": {"top": float(sd_high), "bottom": float(sd_low)}
        }
    except Exception as e:
        print(f"Error calculating ADSZ: {e}")
        return None

# ==========================================
# ALERT DISPATCHER (30-SECOND TEST COOLDOWN)
# ==========================================
def process_alert(alert_key, alert_type, symbol, message, price=None, rsi_5m=None, rsi_15m=None):
    global tg_alert_cache
    now = datetime.now(timezone.utc)
    
    display_name = DISPLAY_NAMES.get(symbol, symbol)
    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A"
    rsi_5m_str = f"{rsi_5m:.2f}" if isinstance(rsi_5m, (int, float)) and not pd.isna(rsi_5m) else "N/A"
    rsi_15m_str = f"{rsi_15m:.2f}" if isinstance(rsi_15m, (int, float)) and not pd.isna(rsi_15m) else "N/A"

    # Fast 30-second cooldown for immediate proof
    cooldown_sec = 30
    send_tg = False

    if alert_key not in tg_alert_cache:
        send_tg = True
    elif (now - tg_alert_cache[alert_key]).total_seconds() >= cooldown_sec:
        send_tg = True

    if send_tg:
        tg_alert_cache[alert_key] = now
        
        tg_message = (
            f"🟢 *[ELEPHANT ZONE TEST ALERT]* 🟢\n\n"
            f"• *Asset:* `{display_name}`\n"
            f"• *Price:* `{price_str}`\n"
            f"• *RSI (5M):* `{rsi_5m_str}`\n"
            f"• *RSI (15M):* `{rsi_15m_str}`\n"
            f"• *Signal Type:* `{alert_type}`\n"
            f"• *Details:* {message}"
        )
        send_telegram_message(tg_message)

# ==========================================
# MAIN SCANNER ROUTINE
# ==========================================
def analyze_market(df_5m, symbol):
    try:
        if len(df_5m) < 45: return
        
        df_5m['rsi_5m'] = ta.rsi(df_5m['close'], length=14, mamode='rma')
        
        df_temp = df_5m.copy()
        df_temp.set_index('timestamp', inplace=True)
        
        resample_rules = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
        df_15m = df_temp.resample('15min').agg(resample_rules).dropna()
        df_1d  = fetch_daily_candles(symbol)

        live_close = df_5m['close'].iloc[-1]
        live_rsi_5m = df_5m['rsi_5m'].iloc[-1]
        
        if df_15m is not None and not df_15m.empty:
            df_15m['rsi'] = ta.rsi(df_15m['close'], length=14, mamode='rma')
            live_rsi_15m = df_15m['rsi'].iloc[-1]
        else:
            live_rsi_15m = np.nan

        # SCAN ELEPHANT ZONES
        dynamic_elephant_levels = calculate_adsz_levels(df_1d)
        
        if dynamic_elephant_levels:
            for key, limits in dynamic_elephant_levels.items():
                if key == "Daily Midline" or not isinstance(limits, dict): 
                    continue
                
                # Broad $50 buffer check for instant proof
                buf = 50.0 if symbol == "BTC-USD" else 2.0
                z_bottom = limits["bottom"] - buf
                z_top = limits["top"] + buf

                if z_bottom <= live_close <= z_top:
                    # Time-stamped cache key forces a fresh alert every 30 seconds
                    test_key = f"{symbol}_{key.replace(' ', '_')}_{int(time.time() // 30)}"
                    
                    process_alert(
                        alert_key=test_key, 
                        alert_type=f"Elephant Zone Touch ({key})", 
                        symbol=symbol, 
                        message=f"Live price ${live_close:,.2f} inside {key}: `[${limits['bottom']:.2f} - ${limits['top']:.2f}]`", 
                        price=live_close, 
                        rsi_5m=live_rsi_5m, 
                        rsi_15m=live_rsi_15m
                    )
    except Exception as e:
        print(f"Error in scanner for {symbol}: {e}")

# ==========================================
# RUNTIME LOOP
# ==========================================
def core_market_scanner_loop():
    print(f"Market Scanner Online...")
    send_telegram_message("🚀 *Signal Engine Online (30-Sec Zone Test Mode)* 🚀")
    
    while True:
        try:
            for symbol in ACTIVE_SYMBOLS:
                df = fetch_candles(symbol)
                if df is not None and not df.empty:
                    analyze_market(df, symbol)
                        
            time.sleep(10)
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    scanner_thread = threading.Thread(target=core_market_scanner_loop, daemon=True)
    scanner_thread.start()
    run_web_server()
