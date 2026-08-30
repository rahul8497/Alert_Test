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
    return "Bot Matrix Status: ONLINE | 15M Pine Script Scanner Active", 200

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
# 📋 WATCHLIST & CONFIGURATION (BTC, GOLD, 15M, 4H COOLDOWN)
# ==========================================
ACTIVE_SYMBOLS = ["BTC-USD", "PAXG-USD"]
DISPLAY_NAMES = {
    "BTC-USD": "BITCOIN (BTC/USD)",
    "PAXG-USD": "GOLD SPOT (PAXG/USD)"
}

ALERT_COOLDOWN_SEC = 14400  # 4 Hours Cooldown (in seconds)

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

def fetch_candles(symbol, interval="15m", period="7d"):
    try:
        df = yf.download(symbol, period=period, interval=interval, progress=False)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.reset_index(inplace=True)
        cols = {c: str(c).lower() for c in df.columns}
        df.rename(columns=cols, inplace=True)
        df.rename(columns={"datetime": "timestamp", "date": "timestamp"}, inplace=True)
        return df
    except Exception as e:
        print(f"Candle fetch error for {symbol} ({interval}): {e}")
        return None

# ==========================================
# 📈 PINE SCRIPT MATH ENGINE CONVERSIONS
# ==========================================

# SECTION 1: AI TREND NAVIGATOR (kNN Moving Average)
def calculate_knn_trend(df, ma_len=5, ma_len_target=5, num_closest=3, smoothing_period=50):
    if df is None or len(df) < max(ma_len, ma_len_target, smoothing_period) + 30:
        return df

    df_calc = df.copy()
    df_calc['hl2'] = (df_calc['high'] + df_calc['low']) / 2.0
    value_in = ta.sma(df_calc['hl2'], length=ma_len)
    target_in = ta.rma(df_calc['close'], length=ma_len_target)

    window_size = max(num_closest, 30)
    knn_ma = []

    for idx in range(len(df_calc)):
        if idx < window_size:
            knn_ma.append(np.nan)
            continue
        
        target_val = target_in.iloc[idx]
        if pd.isna(target_val):
            knn_ma.append(np.nan)
            continue

        distances = []
        for i in range(1, window_size + 1):
            v = value_in.iloc[idx - i]
            if not pd.isna(v):
                dist = abs(target_val - v)
                distances.append((dist, v))

        if len(distances) < num_closest:
            knn_ma.append(np.nan)
            continue

        distances.sort(key=lambda x: x[0])
        closest_vals = [x[1] for x in distances[:num_closest]]
        knn_ma.append(np.mean(closest_vals))

    df_calc['knn_ma'] = knn_ma
    df_calc['knn_ma_smooth'] = ta.wma(df_calc['knn_ma'], length=5)
    df_calc['ma_knn'] = ta.rma(df_calc['knn_ma'], length=smoothing_period)

    return df_calc

# SECTION 2: HTF LEVELS, PIVOT POINTS & GANN BASE LINE
def calculate_htf_levels(symbol):
    df_d = fetch_candles(symbol, interval="1d", period="30d")
    df_w = fetch_candles(symbol, interval="1wk", period="60d")
    df_m = fetch_candles(symbol, interval="1mo", period="180d")

    if df_d is None or len(df_d) < 2: return None

    # Previous Day Levels
    pdc = float(df_d['close'].iloc[-2])
    pdh = float(df_d['high'].iloc[-2])
    pdl = float(df_d['low'].iloc[-2])
    pdp = (pdc + pdh + pdl) / 3.0

    # Gann Base Line Level
    gann_base_sqrt = round(math.sqrt(pdc))
    gann_base_level = float(gann_base_sqrt ** 2)

    # Previous Week Levels
    pwh = float(df_w['high'].iloc[-2]) if df_w is not None and len(df_w) >= 2 else np.nan
    pwl = float(df_w['low'].iloc[-2]) if df_w is not None and len(df_w) >= 2 else np.nan

    # Previous Month Levels
    pmh = float(df_m['high'].iloc[-2]) if df_m is not None and len(df_m) >= 2 else np.nan
    pml = float(df_m['low'].iloc[-2]) if df_m is not None and len(df_m) >= 2 else np.nan

    return {
        "PDH": pdh, "PDL": pdl, "PP": pdp, "Gann Base": gann_base_level,
        "PWH": pwh, "PWL": pwl, "PMH": pmh, "PML": pml
    }

# SECTION 3: LORENTZIAN CLASSIFICATION ML ENGINE
def calculate_lorentzian_classification(df, neighbors_count=8, max_bars_back=2000):
    if df is None or len(df) < 50:
        return df

    df_calc = df.copy()
    df_calc['hlc3'] = (df_calc['high'] + df_calc['low'] + df_calc['close']) / 3.0
    
    f1 = ta.rsi(df_calc['close'], length=14)
    f2 = ta.rsi(df_calc['hlc3'], length=10)
    f3 = ta.cci(df_calc['high'], df_calc['low'], df_calc['close'], length=20)
    f4 = ta.adx(df_calc['high'], df_calc['low'], df_calc['close'], length=20)['ADX_20']
    f5 = ta.rsi(df_calc['close'], length=9)

    features = pd.concat([f1, f2, f3, f4, f5], axis=1).fillna(0).values
    close_vals = df_calc['close'].values
    
    y_train = np.zeros(len(df_calc))
    for i in range(4, len(df_calc)):
        if close_vals[i-4] < close_vals[i]:
            y_train[i] = 1
        elif close_vals[i-4] > close_vals[i]:
            y_train[i] = -1

    predictions = np.zeros(len(df_calc))
    start_idx = max(50, len(df_calc) - max_bars_back)
    
    for idx in range(start_idx, len(df_calc)):
        curr_feat = features[idx]
        feat_diffs = np.abs(features[start_idx:idx] - curr_feat)
        lorentzian_dists = np.sum(np.log1p(feat_diffs), axis=1)
        
        if len(lorentzian_dists) >= neighbors_count:
            nearest_indices = np.argsort(lorentzian_dists)[:neighbors_count]
            pred_val = np.sum(y_train[start_idx + nearest_indices])
            predictions[idx] = pred_val

    df_calc['ml_prediction'] = predictions
    df_calc['ml_signal'] = np.where(predictions > 0, 1, np.where(predictions < 0, -1, 0))
    return df_calc

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

    total_trades, tp1_hits, tp2_hits, tp3_hits = 0, 0, 0, 0

    for i in range(slow_len, len(df_calc) - 20):
        prev_fast, curr_fast = df_calc['fast_ema'].iloc[i-1], df_calc['fast_ema'].iloc[i]
        prev_slow, curr_slow = df_calc['slow_ema'].iloc[i-1], df_calc['slow_ema'].iloc[i]
        
        crossover = (prev_fast <= prev_slow) and (curr_fast > curr_slow)
        crossunder = (prev_fast >= prev_slow) and (curr_fast < curr_slow)

        if crossover or crossunder:
            direction = 1 if crossover else -1
            entry_price = df_calc['close'].iloc[i]
            atr_v = df_calc['atr'].iloc[i]
            
            if pd.isna(atr_v) or atr_v == 0: continue

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
    rate1, rate2, rate3 = tp1_hits / tr, tp2_hits / tr, tp3_hits / tr
    v1, v2, v3 = rate1 * 100, rate2 * 100, rate3 * 100

    best_tp = 1
    best_rate = v1

    if v2 > best_rate:
        best_tp = 2
        best_rate = v2
    if v3 > best_rate:
        best_tp = 3
        best_rate = v3

    bubble_text = f"TP{best_tp} {best_rate:.1f}%"
    return bubble_text, best_tp, best_rate

# ==========================================
# CORE ALERT PROCESSOR (MODIFIED TO REMOVE SIGNAL TYPE & DETAILS)
# ==========================================
def process_alert(alert_key, alert_type, symbol, message, price=None, rsi_5m=None, rsi_15m=None, tp_bubble=None, cooldown_sec=14400):
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
        
        # Case insensitive parsing for Telegram header
        alert_type_upper = alert_type.upper()
        if "BUY" in alert_type_upper or "BULL" in alert_type_upper:
            header = f"🟢 *[15M BUY SIGNAL]* 🟢"
        elif "SELL" in alert_type_upper or "BEAR" in alert_type_upper:
            header = f"🔴 *[15M SELL SIGNAL]* 🔴"
        else:
            header = f"🟡 *[15M LEVEL TOUCH SIGNAL]* 🟡"
            
        tg_message = (
            f"{header}\n\n"
            f"• *Asset:* `{display_name}`\n"
            f"• *Timeframe:* `15 Minutes`\n"
            f"• *Price:* `{price_str}`\n"
            f"• *RSI (5M):* `{rsi_5m_str}`\n"
            f"• *RSI (15M):* `{rsi_15m_str}`\n"
            f"• *Suggested TP Bubble:* {bubble_str}"
        )
        send_telegram_message(tg_message)

    send_sms = False
    if alert_key not in sms_alert_cache:
        send_sms = True
    elif (now - sms_alert_cache[alert_key]).total_seconds() >= cooldown_sec:
        send_sms = True

    if send_sms:
        sms_alert_cache[alert_key] = now
        alert_text = f"ALERT (15M): {display_name} | Price: {price_str} | Bubble: {tp_bubble if tp_bubble else 'N/A'}"
        send_make_webhook({"body": alert_text, "text": alert_text, "message": alert_text})

# ==========================================
# MAIN SCANNER ROUTINE (15M CLOSED CANDLES)
# ==========================================
def analyze_market(df_15m, symbol):
    try:
        # Require enough historical data for completed candle checks
        if df_15m is None or len(df_15m) < 50: return
        
        # Calculate RSIs on confirmed closed candle (iloc[-2])
        df_15m['rsi_15m'] = ta.rsi(df_15m['close'], length=14, mamode='rma')
        live_rsi_15m = float(df_15m['rsi_15m'].iloc[-2])

        df_5m = fetch_candles(symbol, interval="5m", period="2d")
        if df_5m is not None and not df_5m.empty:
            df_5m['rsi_5m'] = ta.rsi(df_5m['close'], length=14, mamode='rma')
            live_rsi_5m = float(df_5m['rsi_5m'].iloc[-2])
        else:
            live_rsi_5m = np.nan

        confirmed_close = float(df_15m['close'].iloc[-2])
        confirmed_high = float(df_15m['high'].iloc[-2])
        confirmed_low = float(df_15m['low'].iloc[-2])

        tp_bubble_text, _, _ = calculate_suggested_tp_bubble(df_15m)

        # ---------------------------------------------------------------------
        # 1. AI TREND NAVIGATOR (kNN LINE CROSSOVER ALERTS)
        # ---------------------------------------------------------------------
        df_knn = calculate_knn_trend(df_15m)
        if df_knn is not None and 'knn_ma_smooth' in df_knn.columns and len(df_knn) >= 3:
            knn_curr = df_knn['knn_ma_smooth'].iloc[-2]  # Just closed candle
            knn_prev = df_knn['knn_ma_smooth'].iloc[-3]  # Previous closed candle
            ma_knn_curr = df_knn['ma_knn'].iloc[-2]
            ma_knn_prev = df_knn['ma_knn'].iloc[-3]

            # Bullish Crossover (Green Line Trend Switch)
            if (knn_prev <= ma_knn_prev) and (knn_curr > ma_knn_curr):
                process_alert(
                    alert_key=f"{symbol}_KNN_Bullish_Cross_15m",
                    alert_type="AI Trend Navigator Bullish Cross (15M)",
                    symbol=symbol,
                    message="AI Trend Navigator fast line crossed ABOVE average line (Bullish Trend Switch).",
                    price=confirmed_close, rsi_5m=live_rsi_5m, rsi_15m=live_rsi_15m,
                    tp_bubble=tp_bubble_text, cooldown_sec=ALERT_COOLDOWN_SEC
                )
            # Bearish Crossunder (Red Line Trend Switch)
            elif (knn_prev >= ma_knn_prev) and (knn_curr < ma_knn_curr):
                process_alert(
                    alert_key=f"{symbol}_KNN_Bearish_Cross_15m",
                    alert_type="AI Trend Navigator Bearish Cross (15M)",
                    symbol=symbol,
                    message="AI Trend Navigator fast line crossed BELOW average line (Bearish Trend Switch).",
                    price=confirmed_close, rsi_5m=live_rsi_5m, rsi_15m=live_rsi_15m,
                    tp_bubble=tp_bubble_text, cooldown_sec=ALERT_COOLDOWN_SEC
                )

        # ---------------------------------------------------------------------
        # 2. LORENTZIAN CLASSIFICATION (SHAPE SIGNAL ALERTS ON CANDLE CLOSE)
        # ---------------------------------------------------------------------
        df_ml = calculate_lorentzian_classification(df_15m)
        if df_ml is not None and 'ml_signal' in df_ml.columns and len(df_ml) >= 3:
            ml_sig_curr = df_ml['ml_signal'].iloc[-2] # Closed candle prediction
            ml_sig_prev = df_ml['ml_signal'].iloc[-3] # Prior bar prediction
            ml_pred = df_ml['ml_prediction'].iloc[-2]

            # Green Pentagon Shape (Bullish Formation)
            if ml_sig_curr == 1 and ml_sig_prev != 1:
                process_alert(
                    alert_key=f"{symbol}_Lorentzian_Green_Shape_15m",
                    alert_type="Lorentzian ML Buy Shape (15M)",
                    symbol=symbol,
                    message=f"🟢 Green Buy shape confirmed on candle close! Score: `+{ml_pred}`",
                    price=confirmed_close, rsi_5m=live_rsi_5m, rsi_15m=live_rsi_15m,
                    tp_bubble=tp_bubble_text, cooldown_sec=ALERT_COOLDOWN_SEC
                )
            # Red Pentagon Shape (Bearish Formation)
            elif ml_sig_curr == -1 and ml_sig_prev != -1:
                process_alert(
                    alert_key=f"{symbol}_Lorentzian_Red_Shape_15m",
                    alert_type="Lorentzian ML Sell Shape (15M)",
                    symbol=symbol,
                    message=f"🔴 Red Sell shape confirmed on candle close! Score: `{ml_pred}`",
                    price=confirmed_close, rsi_5m=live_rsi_5m, rsi_15m=live_rsi_15m,
                    tp_bubble=tp_bubble_text, cooldown_sec=ALERT_COOLDOWN_SEC
                )

        # ---------------------------------------------------------------------
        # 3. HTF LEVEL TOUCH ALERTS (PDH, PDL, PP, GANN BASE, PWH, PWL, PMH, PML)
        # ---------------------------------------------------------------------
        htf_levels = calculate_htf_levels(symbol)
        if htf_levels:
            buf = 25.0 if symbol == "BTC-USD" else 0.1

            for lvl_name, lvl_val in htf_levels.items():
                if pd.isna(lvl_val): continue
                
                if (confirmed_low - buf) <= lvl_val <= (confirmed_high + buf):
                    process_alert(
                        alert_key=f"{symbol}_{lvl_name}_Level_Touch_15m",
                        alert_type=f"HTF Level Touch ({lvl_name})",
                        symbol=symbol,
                        message=f"15M Candle tested HTF Level *{lvl_name}* at `${lvl_val:,.2f}`",
                        price=confirmed_close, rsi_5m=live_rsi_5m, rsi_15m=live_rsi_15m,
                        tp_bubble=tp_bubble_text, cooldown_sec=ALERT_COOLDOWN_SEC
                    )

    except Exception as e:
        print(f"Error in scanner for {symbol}: {e}")

# ==========================================
# RUNTIME LOOP
# ==========================================
def core_market_scanner_loop():
    print(f"15M Market Scanner Fully Online...")
    send_telegram_message("🚀 *15M Bitcoin & Gold Scanner Online* 🚀\n• Scanning BTC and PAXG (Gold) on 15M timeframe with a 4-hour alert cooldown.")
    
    while True:
        try:
            for symbol in ACTIVE_SYMBOLS:
                df = fetch_candles(symbol, interval="15m", period="7d")
                if df is not None and not df.empty:
                    analyze_market(df, symbol)
                        
            time.sleep(30)
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    scanner_thread = threading.Thread(target=core_market_scanner_loop, daemon=True)
    scanner_thread.start()
    run_web_server()
