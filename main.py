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
    return "Bot Matrix Status: ONLINE | Elephant ADSZ Scanner Active", 200

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
            print(f"Error sending Telegram notification to {chat_id}: {e}")

def send_make_webhook(alert_data):
    try:
        requests.post(MAKE_WEBHOOK_URL, json=alert_data, timeout=10)
    except Exception as e:
        print(f"Error sending Make Webhook: {e}")

# Robust Fetch Functions using yf.download to bypass rate limits
def fetch_candles(symbol):
    try:
        df = yf.download(symbol, period="7d", interval="5m", progress=False)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.reset_index(inplace=True)
        cols = {c: str(c).lower() for c in df.columns}
        df.rename(columns=cols, inplace=True)
        df.rename(columns={"datetime": "timestamp", "date": "timestamp"}, inplace=True)
        return df
    except Exception as e:
        print(f"Intraday fetch error for {symbol}: {e}")
        return None

def fetch_daily_candles(symbol):
    try:
        df = yf.download(symbol, period="6m", interval="1d", progress=False)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.reset_index(inplace=True)
        cols = {c: str(c).lower() for c in df.columns}
        df.rename(columns=cols, inplace=True)
        df.rename(columns={"date": "timestamp", "datetime": "timestamp"}, inplace=True)
        return df
    except Exception as e:
        print(f"Daily fetch error for {symbol}: {e}")
        return None

# ==========================================
# 🐘 ADSZ ELEPHANT ZONE ENGINE (Pine Script v6 Exact Match)
# ==========================================
def calculate_adsz_levels(df_1d, d_atr_period=20, d_slope=0.69, d_intercept=0.0):
    try:
        if df_1d is None or len(df_1d) < 5:
            return None

        df_calc = df_1d.copy()
        
        # Adjust ATR period safely if available history is slightly shorter
        atr_len = min(d_atr_period, len(df_calc) - 2)
        if atr_len < 1: atr_len = 1
        
        df_calc['atr'] = ta.atr(df_calc['high'], df_calc['low'], df_calc['close'], length=atr_len)
        
        day_open = float(df_calc['open'].iloc[-1])
        day_atr = float(df_calc['atr'].iloc[-2]) if not pd.isna(df_calc['atr'].iloc[-2]) else float(df_calc['atr'].iloc[-1])
        day_close_prev = float(df_calc['close'].iloc[-2])
        day_high_prev = float(df_calc['high'].iloc[-2])
        day_low_prev = float(df_calc['low'].iloc[-2])

        if pd.isna(day_atr) or day_close_prev == 0:
            day_atr = float(df_calc['high'].iloc[-2] - df_calc['low'].iloc[-2])

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
# ALERT DISPATCHER (15-MINUTE COOLDOWN)
# ==========================================
def process_alert(alert_key, alert_type, symbol, message, price=None, rsi_5m=None, rsi_15m=None):
    global tg_alert_cache
    now = datetime.now(timezone.utc)
    
    display_name = DISPLAY_NAMES.get(symbol, symbol)
    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A"
    rsi_5m_str = f"{rsi_5m:.2f}" if isinstance(rsi_5m, (int, float)) and not pd.isna(rsi_5m) else "N/A"
    rsi_15m_str = f"{rsi_15m:.2f}" if isinstance(rsi_15m, (int, float)) and not pd.isna(rsi_15m) else "N/A"

    cooldown_sec = 900  # 15 minutes between alerts for the same level
    send_tg = False

    if alert_key not in tg_alert_cache:
        send_tg = True
    elif (now - tg_alert_cache[alert_key]).total_seconds() >= cooldown_sec:
        send_tg = True

    if send_tg:
        tg_alert_cache[alert_key] = now
        
        tg_message = (
            f"🟢 *[ELEPHANT ZONE ALERT]* 🟢\n\n"
            f"• *Asset:* `{display_name}`\n"
            f"• *Price:* `{price_str}`\n"
            f"• *RSI (5M):* `{rsi_5m_str}`\n"
            f"• *RSI (15M):* `{rsi_15m_str}`\n"
            f"• *Signal Type:* `{alert_type}`\n"
            f"• *Details:* {message}"
        )
        send_telegram_message(tg_message)
        send_make_webhook({"text": f"{display_name} | {alert_type} | {price_str}"})

# ==========================================
# MAIN SCANNER ROUTINE
# ==========================================
def analyze_market(df_5m, symbol):
    try:
        if df_5m is None or len(df_5m) < 15: return
        
        df_5m['rsi_5m'] = ta.rsi(df_5m['close'], length=14, mamode='rma')
        
        df_temp = df_5m.copy()
        df_temp.set_index('timestamp', inplace=True)
        
        resample_rules = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
        df_15m = df_temp.resample('15min').agg(resample_rules).dropna()
        
        df_1d = fetch_daily_candles(symbol)

        live_close = float(df_5m['close'].iloc[-1])
        live_high = float(df_5m['high'].iloc[-1])
        live_low = float(df_5m['low'].iloc[-1])
        live_rsi_5m = float(df_5m['rsi_5m'].iloc[-1])
        
        if df_15m is not None and not df_15m.empty:
            df_15m['rsi'] = ta.rsi(df_15m['close'], length=14, mamode='rma')
            live_rsi_15m = float(df_15m['rsi'].iloc[-1])
        else:
            live_rsi_15m = np.nan

        dynamic_elephant_levels = calculate_adsz_levels(df_1d)
        
        if dynamic_elephant_levels:
            print(f"[{symbol}] ADSZ Levels: {dynamic_elephant_levels}")
            
            for key, limits in dynamic_elephant_levels.items():
                if key == "Daily Midline" or not isinstance(limits, dict): 
                    continue
                
                # Buffer for feed spread
                buf = 25.0 if symbol == "BTC-USD" else 1.0
                z_bottom = limits["bottom"] - buf
                z_top = limits["top"] + buf

                # Triggers if price is currently inside or wick touches the zone
                if (z_bottom <= live_close <= z_top) or (live_high >= z_bottom and live_low <= z_top):
                    process_alert(
                        alert_key=f"{symbol}_{key.replace(' ', '_')}_Touch", 
                        alert_type=f"Elephant Zone Touch ({key})", 
                        symbol=symbol, 
                        message=f"Price ${live_close:,.2f} tested {key}: `[${limits['bottom']:.2f} - ${limits['top']:.2f}]`", 
                        price=live_close, 
                        rsi_5m=live_rsi_5m, 
                        rsi_15m=live_rsi_15m
                    )
        else:
            print(f"[{symbol}] Daily data unavailable for ADSZ calculation.")
            
    except Exception as e:
        print(f"Error in scanner for {symbol}: {e}")

# ==========================================
# RUNTIME LOOP
# ==========================================
def core_market_scanner_loop():
    print(f"Market Scanner Fully Online...")
    send_telegram_message("🚀 *Elephant ADSZ Signal Engine Online* 🚀")
    
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
