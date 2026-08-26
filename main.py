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
# 🐘 ADSZ ELEPHANT ZONE ENGINE
# ==========================================
def calculate_adsz_levels(df_1d, d_atr_period=20, d_slope=0.69, d_intercept=0.0):
    try:
        if df_1d is None or len(df_1d) < 5:
            return None

        df_calc = df_1d.copy()
        
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
# CORE ALERT PROCESSOR (RESTORED ORIGINAL MESSAGE FORMAT)
# ==========================================
def process_alert(alert_key, alert_type, symbol, message, price=None, rsi_5m=None, rsi_15m=None, tp_bubble=None, cooldown_sec=900):
    global tg_alert_cache, sms_alert_cache
    now = datetime.now(timezone.utc)
    
    display_name = DISPLAY_NAMES.get(symbol, symbol)
    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A"
    rsi_5m_str = f"{rsi_5m:.2f}" if isinstance(rsi_5m, (int, float)) and not pd.isna(rsi_5m) else "N/A"
    rsi_15m_str = f"{rsi_15m:.2f}" if isinstance(rsi_15m, (int, float)) and not pd.isna(rsi_15m) else "N/A"
    bubble_str = f"`{tp_bubble}`" if tp_bubble else "N/A"

    send_tg = False

    if alert_key not in tg_alert_cache:
        send_tg = True
    elif (now - tg_alert_cache[alert_key]).total_seconds() >= cooldown_sec:
        send_tg = True

    if send_tg:
        tg_alert_cache[alert_key] = now
        
        # Original Dynamic Header Logic
        if "Demand" in alert_type or "Bull" in alert_type or "BUY" in alert_type:
            header = f"🟢 *[MACRO BUY SIGNAL]* 🟢"
        elif "Supply" in alert_type or "Bear" in alert_type or "SELL" in alert_type:
            header = f"🔴 *[MACRO SELL SIGNAL]* 🔴"
        else:
            header = f"🟡 *[GANN / ZONE SIGNAL]* 🟡"
            
        # Restored Original Message Template
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

        # Calculate TP Bubble target recommendation
        tp_bubble_text, _, _ = calculate_suggested_tp_bubble(df_5m)

        dynamic_elephant_levels = calculate_adsz_levels(df_1d)
        
        if dynamic_elephant_levels:
            print(f"[{symbol}] ADSZ Levels: {dynamic_elephant_levels}")
            
            for key, limits in dynamic_elephant_levels.items():
                if key == "Daily Midline" or not isinstance(limits, dict): 
                    continue
                
                buf = 25.0 if symbol == "BTC-USD" else 1.0
                z_bottom = limits["bottom"] - buf
                z_top = limits["top"] + buf

                if (z_bottom <= live_close <= z_top) or (live_high >= z_bottom and live_low <= z_top):
                    process_alert(
                        alert_key=f"{symbol}_{key.replace(' ', '_')}_Touch", 
                        alert_type=f"Elephant Zone Touch ({key})", 
                        symbol=symbol, 
                        message=f"Price tested {key}: `[${limits['bottom']:.2f} - ${limits['top']:.2f}]`", 
                        price=live_close, 
                        rsi_5m=live_rsi_5m, 
                        rsi_15m=live_rsi_15m,
                        tp_bubble=tp_bubble_text,
                        cooldown_sec=900
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
