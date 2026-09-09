import time
import threading
import os
import math
import pandas as pd
import numpy as np
import pandas_ta as ta
import requests
from datetime import datetime, timezone
import pytz
from flask import Flask
from tvDatafeed import TvDatafeed, Interval

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
    return "Bot Status: ONLINE | Complete Engine (PDH, PDL, PP, Gann + Strict ML) Active", 200

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
# 📋 BTC & GOLD 15-MINUTE WATCHLIST CONFIG
# ==========================================
SYMBOL_CONFIG = {
    "BTCUSDT": {
        "tv_symbol": "BTCUSDT",
        "exchange": "BINANCE",
        "display": "BITCOIN (BTC/USDT)",
        "interval_tv": Interval.in_15_minute,
        "label": "15 Minutes"
    },
    "PAXGUSDT": {
        "tv_symbol": "PAXGUSDT",
        "exchange": "BINANCE",
        "display": "GOLD SPOT (PAXG/USDT)",
        "interval_tv": Interval.in_15_minute,
        "label": "15 Minutes"
    }
}

# --- UNIVERSAL COOLDOWN TIMERS ---
ZONE_COOLDOWN_SEC = 14400   # 4 Hours Cooldown for Instant Intrabar Zone/Level Touches
ARROW_COOLDOWN_SEC = 14400  # 4 Hours Cooldown for Confirmed Candle-Close ML Arrows

tg_alert_cache = {}
sms_alert_cache = {}

# Initialize TradingView Feed Client
tv = TvDatafeed()

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

# ==========================================
# 🟢 EXACT TRADINGVIEW CANDLE FETCHING ENGINE
# ==========================================
def fetch_candles(symbol_key, interval=Interval.in_15_minute, n_bars=1000):
    try:
        cfg = SYMBOL_CONFIG.get(symbol_key)
        if not cfg:
            return None
            
        df = tv.get_hist(
            symbol=cfg["tv_symbol"],
            exchange=cfg["exchange"],
            interval=interval,
            n_bars=n_bars
        )
        
        if df is None or df.empty:
            return None
            
        df.reset_index(inplace=True)
        cols = {c: str(c).lower() for c in df.columns}
        df.rename(columns=cols, inplace=True)
        df.rename(columns={"datetime": "timestamp", "date": "timestamp"}, inplace=True)
        return df
    except Exception as e:
        print(f"TradingView Candle fetch error for {symbol_key}: {e}")
        return None

# ==========================================
# 📈 PINE SCRIPT MATH ENGINE CONVERSIONS
# ==========================================

# SECTION 1: HTF LEVELS (PDH, PDL, PP, GANN BASE)
def calculate_htf_levels(symbol_key):
    df_d = fetch_candles(symbol_key, interval=Interval.in_daily, n_bars=30)
    if df_d is None or len(df_d) < 2: return None

    pdc = float(df_d['close'].iloc[-2])
    pdh = float(df_d['high'].iloc[-2])
    pdl = float(df_d['low'].iloc[-2])
    
    # Standard Daily Pivot Point
    pdp = (pdc + pdh + pdl) / 3.0

    # Exact Gann Base Line (Nearest Square Root Level)
    gann_base_sqrt = round(math.sqrt(pdc))
    gann_base_level = float(gann_base_sqrt ** 2)

    return {
        "PDH": pdh,
        "PDL": pdl,
        "PP": pdp,
        "Gann Base": gann_base_level
    }

# SECTION 2: ADAPTIVE DEMAND & SUPPLY ZONES ENGINE
def calculate_adaptive_zones(symbol_key):
    phi = 1.618034
    sqrt2 = math.sqrt(2)
    sqrt252 = math.sqrt(252)

    zones = {}

    df_d = fetch_candles(symbol_key, interval=Interval.in_daily, n_bars=60)
    if df_d is not None and len(df_d) >= 22:
        df_d['atr'] = ta.atr(df_d['high'], df_d['low'], df_d['close'], length=20)
        day_open = float(df_d['open'].iloc[-1])
        day_atr = float(df_d['atr'].iloc[-2])
        day_close_prev = float(df_d['close'].iloc[-2])

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
            'ss_high': round(P + dist_strong + ws / 2)
        }

    return zones

# SECTION 3: STRICT TRADINGVIEW LORENTZIAN ARROW ENGINE
def calculate_lorentzian_classification(df, neighbors_count=8, max_bars_back=1000, ema_len=20):
    if df is None or len(df) < max(50, ema_len):
        return df

    df_calc = df.copy()
    df_calc['hlc3'] = (df_calc['high'] + df_calc['low'] + df_calc['close']) / 3.0
    
    f1 = ta.rsi(df_calc['close'], length=14)
    f2 = ta.rsi(df_calc['hlc3'], length=10)
    f3 = ta.cci(df_calc['high'], df_calc['low'], df_calc['close'], length=20)
    
    adx_df = ta.adx(df_calc['high'], df_calc['low'], df_calc['close'], length=20)
    f4 = adx_df['ADX_20'] if adx_df is not None and 'ADX_20' in adx_df.columns else pd.Series(0, index=df_calc.index)
    f5 = ta.rsi(df_calc['close'], length=9)

    features = pd.concat([f1, f2, f3, f4, f5], axis=1).fillna(0).values
    close_vals = df_calc['close'].values
    
    df_calc['ema_filter'] = ta.ema(df_calc['close'], length=ema_len)
    ema_vals = df_calc['ema_filter'].values
    
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

    # --- STRICT UI ARROW DETECTION LOGIC ---
    ml_signal = np.zeros(len(df_calc))
    last_signal_bar = -10
    current_state = 0

    for i in range(4, len(df_calc)):
        score = predictions[i]
        price_close = close_vals[i]
        ema_val = ema_vals[i]

        # GREEN UP ARROW CONDITIONS (Score >= 8 AND Price > EMA AND 4-bar hold)
        if score >= 8 and price_close > ema_val and current_state != 1:
            if (i - last_signal_bar) >= 4:
                ml_signal[i] = 1
                current_state = 1
                last_signal_bar = i

        # RED DOWN ARROW CONDITIONS (Score <= -8 AND Price < EMA AND 4-bar hold)
        elif score <= -8 and price_close < ema_val and current_state != -1:
            if (i - last_signal_bar) >= 4:
                ml_signal[i] = -1
                current_state = -1
                last_signal_bar = i

    df_calc['ml_prediction'] = predictions
    df_calc['ml_signal'] = ml_signal
    return df_calc

# ==========================================
# 💡 TP BUBBLE CALCULATION ENGINE
# ==========================================
def calculate_suggested_tp_bubble(df, fast_len=9, slow_len=21, atr_len=14, tp1_val=1.0, tp2_val=2.0, tp3_val=3.0):
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
# CORE ALERT PROCESSOR
# ==========================================
def process_alert(alert_key, symbol_key, category_title, price=None, rsi_5m=None, rsi_15m=None, tp_bubble=None, cooldown_sec=14400):
    global tg_alert_cache, sms_alert_cache
    now = datetime.now(timezone.utc)
    
    if alert_key in tg_alert_cache and (now - tg_alert_cache[alert_key]).total_seconds() < cooldown_sec:
        return

    tg_alert_cache[alert_key] = now

    cfg = SYMBOL_CONFIG.get(symbol_key, {"display": symbol_key, "label": "15 Minutes"})
    display_name = cfg["display"]
    tf_label = cfg["label"]

    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A"
    rsi_5m_str = f"{rsi_5m:.2f}" if isinstance(rsi_5m, (int, float)) and not pd.isna(rsi_5m) else "N/A"
    rsi_15m_str = f"{rsi_15m:.2f}" if isinstance(rsi_15m, (int, float)) and not pd.isna(rsi_15m) else "N/A"
    bubble_str = f"`{tp_bubble}`" if tp_bubble else "N/A"

    if category_title == "DEMAND":
        header_text = "🟢 *[DEMAND]* 🟢\n\n"
    elif category_title == "SUPPLY":
        header_text = "🔴 *[SUPPLY]* 🔴\n\n"
    elif category_title == "IMPORTANT LEVEL":
        header_text = "🟡 *[IMPORTANT LEVEL]* 🟡\n\n"
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
def analyze_market(symbol_key):
    try:
        cfg = SYMBOL_CONFIG[symbol_key]
        target_tf = cfg["interval_tv"]

        df_main = fetch_candles(symbol_key, interval=target_tf, n_bars=1000)
        if df_main is None or len(df_main) < 50: return
        
        # Live and Confirmed RSIs
        df_main['rsi_15m_calc'] = ta.rsi(df_main['close'], length=14, mamode='rma')
        live_rsi_15m = float(df_main['rsi_15m_calc'].iloc[-1])

        df_5m_temp = fetch_candles(symbol_key, interval=Interval.in_5_minute, n_bars=100)
        if df_5m_temp is not None and not df_5m_temp.empty:
            df_5m_temp['rsi_5m_calc'] = ta.rsi(df_5m_temp['close'], length=14, mamode='rma')
            live_rsi_5m = float(df_5m_temp['rsi_5m_calc'].iloc[-1])
        else:
            live_rsi_5m = np.nan

        # REAL-TIME LIVE PRICES (iloc[-1]) -> INSTANT ZONE/LEVEL TOUCHES
        live_price = float(df_main['close'].iloc[-1])
        live_high = float(df_main['high'].iloc[-1])
        live_low = float(df_main['low'].iloc[-1])

        # CONFIRMED CANDLE CLOSE PRICES (iloc[-2]) -> NO-REPAINT ML ARROWS
        confirmed_close = float(df_main['close'].iloc[-2])

        tp_bubble_text, _, _ = calculate_suggested_tp_bubble(df_main)

        # ---------------------------------------------------------------------
        # ENGINE A: INSTANT DEMAND & SUPPLY ZONE TOUCHES (LIVE INTRABAR iloc[-1])
        # ---------------------------------------------------------------------
        all_zones = calculate_adaptive_zones(symbol_key)

        if 'Daily' in all_zones:
            z = all_zones['Daily']
            if live_low <= z['sd_high'] and live_price >= z['sd_low']:
                process_alert(
                    alert_key=f"{symbol_key}_INSTANT_DEMAND_{z['sd_high']}",
                    symbol_key=symbol_key, category_title="DEMAND",
                    price=live_price, rsi_5m=live_rsi_5m, rsi_15m=live_rsi_15m,
                    tp_bubble=tp_bubble_text, cooldown_sec=ZONE_COOLDOWN_SEC
                )
            elif live_high >= z['ws_low'] and live_price <= z['ws_high']:
                process_alert(
                    alert_key=f"{symbol_key}_INSTANT_SUPPLY_{z['ws_low']}",
                    symbol_key=symbol_key, category_title="SUPPLY",
                    price=live_price, rsi_5m=live_rsi_5m, rsi_15m=live_rsi_15m,
                    tp_bubble=tp_bubble_text, cooldown_sec=ZONE_COOLDOWN_SEC
                )

        # ---------------------------------------------------------------------
        # ENGINE B: INSTANT IMPORTANT LEVEL TOUCHES (PDH, PDL, PP, GANN BASE)
        # ---------------------------------------------------------------------
        htf_levels = calculate_htf_levels(symbol_key)
        if htf_levels:
            for lvl_name, lvl_val in htf_levels.items():
                if pd.isna(lvl_val): continue
                
                # Tight 0.03% tolerance for instant level touch
                if abs(live_price - lvl_val) / lvl_val <= 0.0003:
                    process_alert(
                        alert_key=f"{symbol_key}_INSTANT_LEVEL_{lvl_name}_{round(lvl_val)}",
                        symbol_key=symbol_key, category_title="IMPORTANT LEVEL",
                        price=live_price, rsi_5m=live_rsi_5m, rsi_15m=live_rsi_15m,
                        tp_bubble=tp_bubble_text, cooldown_sec=ZONE_COOLDOWN_SEC
                    )

        # ---------------------------------------------------------------------
        # ENGINE C: TREND CHANGING (CONFIRMED 15M CANDLE CLOSE ML ARROWS iloc[-2])
        # ---------------------------------------------------------------------
        df_ml = calculate_lorentzian_classification(df_main)
        if df_ml is not None and 'ml_signal' in df_ml.columns and len(df_ml) >= 3:
            ml_sig_curr = df_ml['ml_signal'].iloc[-2]

            if ml_sig_curr == 1:
                process_alert(
                    alert_key=f"{symbol_key}_GREEN_ARROW_CONFIRMED",
                    symbol_key=symbol_key, category_title="TREND CHANGING",
                    price=confirmed_close, rsi_5m=live_rsi_5m, rsi_15m=live_rsi_15m,
                    tp_bubble=tp_bubble_text, cooldown_sec=ARROW_COOLDOWN_SEC
                )
            elif ml_sig_curr == -1:
                process_alert(
                    alert_key=f"{symbol_key}_RED_ARROW_CONFIRMED",
                    symbol_key=symbol_key, category_title="TREND CHANGING",
                    price=confirmed_close, rsi_5m=live_rsi_5m, rsi_15m=live_rsi_15m,
                    tp_bubble=tp_bubble_text, cooldown_sec=ARROW_COOLDOWN_SEC
                )

    except Exception as e:
        print(f"Error in scanner for {symbol_key}: {e}")

# ==========================================
# RUNTIME LOOP
# ==========================================
def core_market_scanner_loop():
    print(f"BTC & GOLD Full Engine Scanner Online...")
    send_telegram_message("*BTC & GOLD Full Engine Scanner Online*")
    
    while True:
        try:
            for symbol_key in SYMBOL_CONFIG.keys():
                analyze_market(symbol_key)
                        
            time.sleep(30)
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    scanner_thread = threading.Thread(target=core_market_scanner_loop, daemon=True)
    scanner_thread.start()
    run_web_server()
