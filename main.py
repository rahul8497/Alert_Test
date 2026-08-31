import time
import threading
import os
import math
import pandas as pd
import numpy as np
import pandas_ta as ta
import requests
import yfinance as yf
from datetime import datetime, time as dtime, timezone
import pytz
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
    return "Bot Matrix Status: ONLINE | Multi-Timeframe Pine Script Scanner Active", 200

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
# 📋 WATCHLIST & TIMEFRAME CONFIGURATION
# ==========================================
SYMBOL_CONFIG = {
    "BTC-USD": {"display": "BITCOIN (BTC/USD)", "interval": "15m", "label": "15 Minutes"},
    "PAXG-USD": {"display": "GOLD SPOT (PAXG/USD)", "interval": "15m", "label": "15 Minutes"},
    "^NSEI": {"display": "NIFTY 50 INDEX", "interval": "5m", "label": "5 Minutes"}
}

ALERT_COOLDOWN_SEC = 14400  # 4 Hours Cooldown (in seconds)

tg_alert_cache = {}
sms_alert_cache = {}

# ==========================================
# ⏰ MARKET HOURS CHECKER (FOR NSE/NIFTY)
# ==========================================
def is_indian_market_open():
    tz = pytz.timezone('Asia/Kolkata')
    now = datetime.now(tz)
    
    if now.weekday() >= 5:
        return False
    
    market_start = dtime(9, 15)
    market_end = dtime(15, 30)
    return market_start <= now.time() <= market_end

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

# SECTION 3: ADAPTIVE DEMAND & SUPPLY ZONES ENGINE
def calculate_adaptive_zones(symbol):
    phi = 1.618034
    sqrt2 = math.sqrt(2)
    sqrt252 = math.sqrt(252)

    zones = {}

    # 1. DAILY ZONES
    df_d = fetch_candles(symbol, interval="1d", period="60d")
    if df_d is not None and len(df_d) >= 22:
        df_d['atr'] = ta.atr(df_d['high'], df_d['low'], df_d['close'], length=20)
        day_open = float(df_d['open'].iloc[-1])
        day_atr = float(df_d['atr'].iloc[-2])
        day_close_prev = float(df_d['close'].iloc[-2])
        day_high_prev = float(df_d['high'].iloc[-2])
        day_low_prev = float(df_d['low'].iloc[-2])

        atr_ann_pct = (day_atr / day_close_prev) * sqrt252 * 100
        effvol = 0.69 * atr_ann_pct + 0.0
        P = round(day_open)
        sigma = P * effvol / (100.0 * sqrt252)
        dist_strong = sigma
        dist_weak = sigma / (2.0 * sqrt2)
        ws = round(sigma / 4.0)
        ww = round(sigma / (4.0 * phi))

        zones['Daily'] = {
            'sd_low': round(P - dist_strong - ws / 2),
            'sd_high': round(P - dist_strong + ws / 2),
            'wd_low': round(P - dist_weak - ww / 2),
            'wd_high': round(P - dist_weak + ww / 2),
            'ws_low': round(P + dist_weak - ww / 2),
            'ws_high': round(P + dist_weak + ww / 2),
            'ss_low': round(P + dist_strong - ws / 2),
            'ss_high': round(P + dist_strong + ws / 2),
            'dpoc': round((day_high_prev + day_low_prev + day_close_prev) / 3)
        }

    # 2. WEEKLY ZONES
    df_w = fetch_candles(symbol, interval="1wk", period="180d")
    if df_w is not None and len(df_w) >= 6:
        df_w['atr'] = ta.atr(df_w['high'], df_w['low'], df_w['close'], length=5)
        week_open = float(df_w['open'].iloc[-1])
        w_atr_weekly = float(df_w['atr'].iloc[-2])
        w_close_prev = float(df_w['close'].iloc[-2])

        w_atr_ann_pct = (w_atr_weekly / w_close_prev) * math.sqrt(52) * 100
        effvol_w = 0.68 * w_atr_ann_pct + 0.0
        P_w = round(week_open)
        sigma_w = P_w * effvol_w / (100.0 * math.sqrt(252.0 / 5.0))
        dist_strong_w = sigma_w
        dist_weak_w = sigma_w / (2.0 * sqrt2)
        ws_w = round(sigma_w / 4.0)
        ww_w = round(sigma_w / (4.0 * phi))

        zones['Weekly'] = {
            'wsd_low': round(P_w - dist_strong_w - ws_w / 2),
            'wsd_high': round(P_w - dist_strong_w + ws_w / 2),
            'wwd_low': round(P_w - dist_weak_w - ww_w / 2),
            'wwd_high': round(P_w - dist_weak_w + ww_w / 2),
            'wws_low': round(P_w + dist_weak_w - ww_w / 2),
            'wws_high': round(P_w + dist_weak_w + ww_w / 2),
            'wss_low': round(P_w + dist_strong_w - ws_w / 2),
            'wss_high': round(P_w + dist_strong_w + ws_w / 2),
            'wpoc': P_w + 8
        }

    # 3. MONTHLY ZONES
    df_m = fetch_candles(symbol, interval="1mo", period="730d")
    if df_m is not None and len(df_m) >= 21:
        df_m['atr'] = ta.atr(df_m['high'], df_m['low'], df_m['close'], length=20)
        month_open = float(df_m['open'].iloc[-1])
        m_atr_monthly = float(df_m['atr'].iloc[-2])
        m_close_prev = float(df_m['close'].iloc[-2])
        m_high_prev = float(df_m['high'].iloc[-2])
        m_low_prev = float(df_m['low'].iloc[-2])

        m_atr_ann_pct = (m_atr_monthly / month_open) * math.sqrt(12) * 100
        effvol_m = 0.90 * m_atr_ann_pct + 0.0
        P_m = round(month_open)
        sigma_m = P_m * effvol_m / (100.0 * math.sqrt(12.0))
        dist_strong_m = sigma_m
        dist_weak_m = sigma_m / 2.77
        ws_m = round(sigma_m / 4.35)
        ww_m = round(sigma_m / 5.1)

        zones['Monthly'] = {
            'msd_low': round(P_m - dist_strong_m - ws_m / 2),
            'msd_high': round(P_m - dist_strong_m + ws_m / 2),
            'mwd_low': round(P_m - dist_weak_m - ww_m / 2),
            'mwd_high': round(P_m - dist_weak_m + ww_m / 2),
            'mws_low': round(P_m + dist_weak_m - ww_m / 2),
            'mws_high': round(P_m + dist_weak_m + ww_m / 2),
            'mss_low': round(P_m + dist_strong_m - ws_m / 2),
            'mss_high': round(P_m + dist_strong_m + ws_m / 2),
            'mpoc': round((m_high_prev + m_low_prev + m_close_prev) / 3)
        }

    return zones

# SECTION 4: LORENTZIAN CLASSIFICATION ML ENGINE
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
# CORE ALERT PROCESSOR (STRICT 5 CATEGORIES)
# ==========================================
def process_alert(alert_key, symbol, category_title, price=None, rsi_5m=None, rsi_15m=None, tp_bubble=None, cooldown_sec=14400):
    global tg_alert_cache, sms_alert_cache
    now = datetime.now(timezone.utc)
    
    if alert_key in tg_alert_cache and (now - tg_alert_cache[alert_key]).total_seconds() < cooldown_sec:
        return

    tg_alert_cache[alert_key] = now

    cfg = SYMBOL_CONFIG.get(symbol, {"display": symbol, "label": "15 Minutes"})
    display_name = cfg["display"]
    tf_label = cfg["label"]

    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A"
    rsi_5m_str = f"{rsi_5m:.2f}" if isinstance(rsi_5m, (int, float)) and not pd.isna(rsi_5m) else "N/A"
    rsi_15m_str = f"{rsi_15m:.2f}" if isinstance(rsi_15m, (int, float)) and not pd.isna(rsi_15m) else "N/A"
    bubble_str = f"`{tp_bubble}`" if tp_bubble else "N/A"

    # Header icon mapping for the 5 requested categories
    if category_title == "DEMAND":
        header_text = "🟢 *[DEMAND]* 🟢\n\n"
    elif category_title == "SUPPLY":
        header_text = "🔴 *[SUPPLY]* 🔴\n\n"
    elif category_title == "IMPORTANT LEVEL":
        header_text = "🟡 *[IMPORTANT LEVEL]* 🟡\n\n"
    elif category_title == "TREND CROSS OVER":
        header_text = "⚡ *[TREND CROSS OVER]* ⚡\n\n"
    elif category_title == "TREND CHANGING":
        header_text = "🔄 *[TREND CHANGING]* 🔄\n\n"
    else:
        header_text = f"📢 *[{category_title}]* 📢\n\n"

    tg_message = (
        f"{header_text}"
        f"• *Asset:* `{display_name}`\n"
        f"• *Timeframe:* `{tf_label}`\n"
        f"• *Price:* `{price_str}`\n"
        f"• *RSI (5M):* `{rsi_5m_str}`\n"
        f"• *RSI (15M):* `{rsi_15m_str}`\n"
        f"• *Suggested TP Bubble:* {bubble_str}"
    )
    send_telegram_message(tg_message)

    if alert_key not in sms_alert_cache or (now - sms_alert_cache[alert_key]).total_seconds() >= cooldown_sec:
        sms_alert_cache[alert_key] = now
        alert_text = f"ALERT ({tf_label}): {display_name} | {category_title} | Price: {price_str} | Bubble: {tp_bubble if tp_bubble else 'N/A'}"
        send_make_webhook({"body": alert_text, "text": alert_text, "message": alert_text})

# ==========================================
# MAIN SCANNER ROUTINE
# ==========================================
def analyze_market(symbol):
    try:
        if symbol == "^NSEI" and not is_indian_market_open():
            return

        cfg = SYMBOL_CONFIG[symbol]
        target_tf = cfg["interval"]

        df_main = fetch_candles(symbol, interval=target_tf, period="7d")
        if df_main is None or len(df_main) < 50: return
        
        df_main['rsi_main'] = ta.rsi(df_main['close'], length=14, mamode='rma')
        live_rsi_main = float(df_main['rsi_main'].iloc[-2])

        if target_tf == "5m":
            live_rsi_5m = live_rsi_main
            df_15m_temp = fetch_candles(symbol, interval="15m", period="7d")
            if df_15m_temp is not None and not df_15m_temp.empty:
                df_15m_temp['rsi_15m'] = ta.rsi(df_15m_temp['close'], length=14, mamode='rma')
                live_rsi_15m = float(df_15m_temp['rsi_15m'].iloc[-2])
            else:
                live_rsi_15m = np.nan
        else:
            live_rsi_15m = live_rsi_main
            df_5m_temp = fetch_candles(symbol, interval="5m", period="2d")
            if df_5m_temp is not None and not df_5m_temp.empty:
                df_5m_temp['rsi_5m'] = ta.rsi(df_5m_temp['close'], length=14, mamode='rma')
                live_rsi_5m = float(df_5m_temp['rsi_5m'].iloc[-2])
            else:
                live_rsi_5m = np.nan

        confirmed_close = float(df_main['close'].iloc[-2])
        confirmed_high = float(df_main['high'].iloc[-2])
        confirmed_low = float(df_main['low'].iloc[-2])
        prev_low = float(df_main['low'].iloc[-3])
        prev_high = float(df_main['high'].iloc[-3])
        
        candle_ts = str(df_main['timestamp'].iloc[-2])

        tp_bubble_text, _, _ = calculate_suggested_tp_bubble(df_main)

        # ---------------------------------------------------------------------
        # 1. TREND CROSS OVER (kNN Moving Average Crossover)
        # ---------------------------------------------------------------------
        df_knn = calculate_knn_trend(df_main)
        if df_knn is not None and 'knn_ma_smooth' in df_knn.columns and len(df_knn) >= 3:
            knn_curr = df_knn['knn_ma_smooth'].iloc[-2]
            knn_prev = df_knn['knn_ma_smooth'].iloc[-3]
            ma_knn_curr = df_knn['ma_knn'].iloc[-2]
            ma_knn_prev = df_knn['ma_knn'].iloc[-3]

            if (knn_prev <= ma_knn_prev) and (knn_curr > ma_knn_curr):
                process_alert(
                    alert_key=f"{symbol}_KNN_Bullish_Cross_{target_tf}_{candle_ts}",
                    symbol=symbol, category_title="TREND CROSS OVER",
                    price=confirmed_close, rsi_5m=live_rsi_5m, rsi_15m=live_rsi_15m,
                    tp_bubble=tp_bubble_text, cooldown_sec=ALERT_COOLDOWN_SEC
                )
            elif (knn_prev >= ma_knn_prev) and (knn_curr < ma_knn_curr):
                process_alert(
                    alert_key=f"{symbol}_KNN_Bearish_Cross_{target_tf}_{candle_ts}",
                    symbol=symbol, category_title="TREND CROSS OVER",
                    price=confirmed_close, rsi_5m=live_rsi_5m, rsi_15m=live_rsi_15m,
                    tp_bubble=tp_bubble_text, cooldown_sec=ALERT_COOLDOWN_SEC
                )

        # ---------------------------------------------------------------------
        # 2. TREND CHANGING (Lorentzian Machine Learning Signal)
        # ---------------------------------------------------------------------
        df_ml = calculate_lorentzian_classification(df_main)
        if df_ml is not None and 'ml_signal' in df_ml.columns and len(df_ml) >= 3:
            ml_sig_curr = df_ml['ml_signal'].iloc[-2]
            ml_sig_prev = df_ml['ml_signal'].iloc[-3]

            if ml_sig_curr == 1 and ml_sig_prev != 1:
                process_alert(
                    alert_key=f"{symbol}_Lorentzian_Green_Shape_{target_tf}_{candle_ts}",
                    symbol=symbol, category_title="TREND CHANGING",
                    price=confirmed_close, rsi_5m=live_rsi_5m, rsi_15m=live_rsi_15m,
                    tp_bubble=tp_bubble_text, cooldown_sec=ALERT_COOLDOWN_SEC
                )
            elif ml_sig_curr == -1 and ml_sig_prev != -1:
                process_alert(
                    alert_key=f"{symbol}_Lorentzian_Red_Shape_{target_tf}_{candle_ts}",
                    symbol=symbol, category_title="TREND CHANGING",
                    price=confirmed_close, rsi_5m=live_rsi_5m, rsi_15m=live_rsi_15m,
                    tp_bubble=tp_bubble_text, cooldown_sec=ALERT_COOLDOWN_SEC
                )

        # ---------------------------------------------------------------------
        # 3. IMPORTANT LEVEL (PDH, PDL, PP, Gann Base, PWH, PWL, PMH, PML)
        # ---------------------------------------------------------------------
        htf_levels = calculate_htf_levels(symbol)
        if htf_levels:
            buf = 25.0 if symbol == "BTC-USD" else (10.0 if symbol == "^NSEI" else 0.1)
            for lvl_name, lvl_val in htf_levels.items():
                if pd.isna(lvl_val): continue
                if (confirmed_low - buf) <= lvl_val <= (confirmed_high + buf):
                    process_alert(
                        alert_key=f"{symbol}_{lvl_name}_Level_Touch_{target_tf}_{candle_ts}",
                        symbol=symbol, category_title="IMPORTANT LEVEL",
                        price=confirmed_close, rsi_5m=live_rsi_5m, rsi_15m=live_rsi_15m,
                        tp_bubble=tp_bubble_text, cooldown_sec=ALERT_COOLDOWN_SEC
                    )

        # ---------------------------------------------------------------------
        # 4 & 5. DEMAND and SUPPLY (Adaptive Supply & Demand Zones)
        # ---------------------------------------------------------------------
        all_zones = calculate_adaptive_zones(symbol)

        # Daily Zone Checks
        if 'Daily' in all_zones:
            z = all_zones['Daily']
            if confirmed_low <= z['sd_high'] and prev_low > z['sd_high']:
                process_alert(f"{symbol}_Daily_SD_Entry_{candle_ts}", symbol, "DEMAND", confirmed_close, live_rsi_5m, live_rsi_15m, tp_bubble_text, ALERT_COOLDOWN_SEC)
            if confirmed_low <= z['wd_high'] and prev_low > z['wd_high']:
                process_alert(f"{symbol}_Daily_WD_Entry_{candle_ts}", symbol, "DEMAND", confirmed_close, live_rsi_5m, live_rsi_15m, tp_bubble_text, ALERT_COOLDOWN_SEC)
            if confirmed_high >= z['ws_low'] and prev_high < z['ws_low']:
                process_alert(f"{symbol}_Daily_WS_Entry_{candle_ts}", symbol, "SUPPLY", confirmed_close, live_rsi_5m, live_rsi_15m, tp_bubble_text, ALERT_COOLDOWN_SEC)
            if confirmed_high >= z['ss_low'] and prev_high < z['ss_low']:
                process_alert(f"{symbol}_Daily_SS_Entry_{candle_ts}", symbol, "SUPPLY", confirmed_close, live_rsi_5m, live_rsi_15m, tp_bubble_text, ALERT_COOLDOWN_SEC)

        # Weekly Zone Checks
        if 'Weekly' in all_zones:
            z = all_zones['Weekly']
            if confirmed_low <= z['wsd_high'] and prev_low > z['wsd_high']:
                process_alert(f"{symbol}_Weekly_SD_Entry_{candle_ts}", symbol, "DEMAND", confirmed_close, live_rsi_5m, live_rsi_15m, tp_bubble_text, ALERT_COOLDOWN_SEC)
            if confirmed_high >= z['wss_low'] and prev_high < z['wss_low']:
                process_alert(f"{symbol}_Weekly_SS_Entry_{candle_ts}", symbol, "SUPPLY", confirmed_close, live_rsi_5m, live_rsi_15m, tp_bubble_text, ALERT_COOLDOWN_SEC)

        # Monthly Zone Checks
        if 'Monthly' in all_zones:
            z = all_zones['Monthly']
            if confirmed_low <= z['msd_high'] and prev_low > z['msd_high']:
                process_alert(f"{symbol}_Monthly_SD_Entry_{candle_ts}", symbol, "DEMAND", confirmed_close, live_rsi_5m, live_rsi_15m, tp_bubble_text, ALERT_COOLDOWN_SEC)
            if confirmed_high >= z['mss_low'] and prev_high < z['mss_low']:
                process_alert(f"{symbol}_Monthly_SS_Entry_{candle_ts}", symbol, "SUPPLY", confirmed_close, live_rsi_5m, live_rsi_15m, tp_bubble_text, ALERT_COOLDOWN_SEC)

    except Exception as e:
        print(f"Error in scanner for {symbol}: {e}")

# ==========================================
# RUNTIME LOOP
# ==========================================
def core_market_scanner_loop():
    print(f"Multi-Timeframe Market Scanner Fully Online...")
    send_telegram_message("🚀 *Multi-Timeframe Market Scanner Online* 🚀\n• Scanning BTC & PAXG (15M) and NIFTY 50 (5M during market hours).")
    
    while True:
        try:
            for symbol in SYMBOL_CONFIG.keys():
                analyze_market(symbol)
                        
            time.sleep(30)
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    scanner_thread = threading.Thread(target=core_market_scanner_loop, daemon=True)
    scanner_thread.start()
    run_web_server()
