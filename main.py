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
# 🚨 CREDENTIALS & HOOKS (PERSONAL CHAT ONLY) 🚨
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8992095386:AAFexnI8IRh990PlwZtkn6WkjeOV0yHjkCE")
PERSONAL_CHAT_ID = os.environ.get("PERSONAL_CHAT_ID", "1136613703")
MAKE_WEBHOOK_URL = os.environ.get("MAKE_WEBHOOK_URL", "https://hook.us2.make.com/ztcvn6rzkkidnnwyn2c7imhtgz1yr3sw")

http_session = requests.Session()

# ==========================================
# 📋 WATCHLIST CONFIG (BTC, GOLD & NIFTY)
# ==========================================
SYMBOL_CONFIG = {
    "BTCUSDT": {
        "tv_symbol": "BTCUSDT",
        "exchange": "BINANCE",
        "display": "BITCOIN (BTC/USDT)",
        "interval_tv": Interval.in_15_minute,
        "label": "15 Minutes",
        "currency": "$",
        "is_24_7": True
    },
    "PAXGUSDT": {
        "tv_symbol": "PAXGUSDT",
        "exchange": "BINANCE",
        "display": "GOLD SPOT (PAXG/USDT)",
        "interval_tv": Interval.in_15_minute,
        "label": "15 Minutes",
        "currency": "$",
        "is_24_7": True
    },
    "NIFTY50": {
        "tv_symbol": "NIFTY",
        "exchange": "NSE",
        "display": "NIFTY 50 (NSE)",
        "interval_tv": Interval.in_15_minute,
        "label": "15 Minutes",
        "currency": "₹",
        "is_24_7": False
    }
}

# --- COOLDOWN TIMER (4 HOURS) ---
ZONE_COOLDOWN_SEC = 14400

tg_alert_cache = {}
sms_alert_cache = {}
ui_levels_cache = {}

tv_lock = threading.Lock()
tv = TvDatafeed()

def reconnect_tv():
    global tv
    with tv_lock:
        try:
            tv = TvDatafeed()
        except Exception as e:
            print(f"TvDatafeed reconnect failed: {e}")

# ==========================================
# 🕒 MARKET TIME & SCHEDULE ENGINE
# ==========================================
def is_market_open(symbol_key):
    cfg = SYMBOL_CONFIG.get(symbol_key)
    if not cfg:
        return False
    if cfg.get("is_24_7", False):
        return True

    if cfg.get("exchange") == "NSE":
        ist_tz = pytz.timezone('Asia/Kolkata')
        now_ist = datetime.now(timezone.utc).astimezone(ist_tz)
        if now_ist.weekday() >= 5:
            return False
        market_start = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
        market_end = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
        return market_start <= now_ist <= market_end

    return True

# ==========================================
# DISPATCH PIPELINES (PERSONAL CHAT + MAKE EMAIL)
# ==========================================
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": PERSONAL_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    for _ in range(2):
        try:
            resp = http_session.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                return
        except Exception as e:
            print(f"Error sending Telegram notification: {e}")
            time.sleep(1)

def send_make_webhook(alert_data):
    for _ in range(2):
        try:
            resp = http_session.post(MAKE_WEBHOOK_URL, json=alert_data, timeout=10)
            if resp.status_code < 300:
                return
        except Exception as e:
            print(f"Error sending Make Webhook: {e}")
            time.sleep(1)

# ==========================================
# 🟢 TRADINGVIEW CANDLE FETCHING ENGINE
# ==========================================
def fetch_candles(symbol_key, interval=Interval.in_15_minute, n_bars=150):
    cfg = SYMBOL_CONFIG.get(symbol_key)
    if not cfg:
        return None

    for _ in range(2):
        try:
            with tv_lock:
                df = tv.get_hist(
                    symbol=cfg["tv_symbol"],
                    exchange=cfg["exchange"],
                    interval=interval,
                    n_bars=n_bars
                )
            if df is not None and not df.empty:
                df.reset_index(inplace=True)
                df.rename(columns={c: str(c).lower() for c in df.columns}, inplace=True)
                return df
        except Exception as e:
            print(f"TradingView Candle fetch error for {symbol_key}: {e}")
        
        reconnect_tv()
        time.sleep(1)

    return None

# ==========================================
# 📈 HTF & PIVOT BADGES + 2 SUPPORT & 2 RESISTANCE BANDS
# ==========================================
def get_ui_levels(symbol_key):
    now_utc = datetime.now(timezone.utc)
    cached = ui_levels_cache.get(symbol_key)
    
    # Refresh HTF & S/R zones every 15 minutes
    if cached and (now_utc - cached["timestamp"]).total_seconds() < 900:
        return cached["htf"], cached["supports"], cached["resistances"]

    htf = {}
    supports = {}
    resistances = {}
    phi = 1.618034
    sqrt2 = math.sqrt(2)
    sqrt252 = math.sqrt(252)

    # 1. DAILY HTF (PDH, PDL, PP, Gann Base) + TWO SUPPORT & TWO RESISTANCE BANDS
    df_d = fetch_candles(symbol_key, interval=Interval.in_daily, n_bars=40)
    if df_d is not None and len(df_d) >= 22:
        pdc = float(df_d['close'].iloc[-2])
        pdh = float(df_d['high'].iloc[-2])
        pdl = float(df_d['low'].iloc[-2])
        pdp = (pdc + pdh + pdl) / 3.0
        gann_base = float(round(math.sqrt(pdc)) ** 2)

        htf["PDH"] = pdh
        htf["PDL"] = pdl
        htf["PP"] = pdp
        htf["Gann Base"] = gann_base

        df_d['atr'] = ta.atr(df_d['high'], df_d['low'], df_d['close'], length=20)
        day_open = float(df_d['open'].iloc[-1])
        day_atr = float(df_d['atr'].iloc[-2])
        
        if not pd.isna(day_atr) and pdc > 0:
            atr_ann_pct = (day_atr / pdc) * sqrt252 * 100.0
            effvol = 0.69 * atr_ann_pct
            P = round(day_open)
            sigma = P * effvol / (100.0 * sqrt252)
            dist_strong = sigma
            dist_weak = sigma / (2.0 * sqrt2)
            ws = round(sigma / 4.0)
            ww = round(sigma / (4.0 * phi))

            supports = {
                "Weak Demand":   (round(P - dist_weak   - ww / 2), round(P - dist_weak   + ww / 2)),
                "Strong Demand": (round(P - dist_strong - ws / 2), round(P - dist_strong + ws / 2)),
            }

            resistances = {
                "Weak Supply":   (round(P + dist_weak   - ww / 2), round(P + dist_weak   + ww / 2)),
                "Strong Supply": (round(P + dist_strong - ws / 2), round(P + dist_strong + ws / 2)),
            }

    # 2. WEEKLY HTF (PWH, PWL)
    df_w = fetch_candles(symbol_key, interval=Interval.in_weekly, n_bars=5)
    if df_w is not None and len(df_w) >= 2:
        htf["PWH"] = float(df_w['high'].iloc[-2])
        htf["PWL"] = float(df_w['low'].iloc[-2])

    # 3. MONTHLY HTF (PMH, PML)
    df_m = fetch_candles(symbol_key, interval=Interval.in_monthly, n_bars=5)
    if df_m is not None and len(df_m) >= 2:
        htf["PMH"] = float(df_m['high'].iloc[-2])
        htf["PML"] = float(df_m['low'].iloc[-2])

    if htf or supports or resistances:
        ui_levels_cache[symbol_key] = {
            "timestamp": now_utc,
            "htf": htf,
            "supports": supports,
            "resistances": resistances
        }
    return htf, supports, resistances

# ==========================================
# 💡 TP BUBBLE CALCULATION ENGINE (VECTORIZED)
# ==========================================
def calculate_suggested_tp_bubble(df, fast_len=9, slow_len=21, atr_len=14, tp1_val=1.0, tp2_val=2.0, tp3_val=3.0):
    if df is None or len(df) < slow_len + atr_len + 20:
        return "TP1 50.0%", 1, 50.0

    fast_ema = ta.ema(df['close'], length=fast_len).to_numpy()
    slow_ema = ta.ema(df['close'], length=slow_len).to_numpy()
    atr = ta.atr(df['high'], df['low'], df['close'], length=atr_len).to_numpy()
    closes = df['close'].to_numpy()
    highs = df['high'].to_numpy()
    lows = df['low'].to_numpy()

    n = len(df)
    prev_f, curr_f = fast_ema[slow_len-1:n-21], fast_ema[slow_len:n-20]
    prev_s, curr_s = slow_ema[slow_len-1:n-21], slow_ema[slow_len:n-20]

    crossovers = (prev_f <= prev_s) & (curr_f > curr_s)
    crossunders = (prev_f >= prev_s) & (curr_f < curr_s)
    signal_indices = np.where(crossovers | crossunders)[0] + slow_len

    total_trades, tp1_hits, tp2_hits, tp3_hits = 0, 0, 0, 0

    for i in signal_indices:
        atr_v = atr[i]
        if np.isnan(atr_v) or atr_v == 0:
            continue

        direction = 1 if fast_ema[i] > slow_ema[i] else -1
        entry_price = closes[i]
        total_trades += 1

        end_j = min(i + 30, n)
        if direction == 1:
            max_h = np.max(highs[i+1:end_j])
            if max_h >= entry_price + tp1_val * atr_v: tp1_hits += 1
            if max_h >= entry_price + tp2_val * atr_v: tp2_hits += 1
            if max_h >= entry_price + tp3_val * atr_v: tp3_hits += 1
        else:
            min_l = np.min(lows[i+1:end_j])
            if min_l <= entry_price - tp1_val * atr_v: tp1_hits += 1
            if min_l <= entry_price - tp2_val * atr_v: tp2_hits += 1
            if min_l <= entry_price - tp3_val * atr_v: tp3_hits += 1

    tr = max(1, total_trades)
    rates = [(1, (tp1_hits / tr) * 100), (2, (tp2_hits / tr) * 100), (3, (tp3_hits / tr) * 100)]
    best_tp, best_rate = max(rates, key=lambda x: x[1])

    return f"TP{best_tp} {best_rate:.1f}%", best_tp, best_rate

# ==========================================
# CORE ALERT PROCESSOR (EXACT ORIGINAL MESSAGE FORMAT)
# ==========================================
def process_alert(alert_key, symbol_key, category_title, price=None, rsi_5m=None, rsi_15m=None, tp_bubble=None, cooldown_sec=14400, level_name=None):
    global tg_alert_cache, sms_alert_cache
    now_utc = datetime.now(timezone.utc)
    
    # Convert UTC to Indian Standard Time (IST)
    ist_tz = pytz.timezone('Asia/Kolkata')
    now_ist = now_utc.astimezone(ist_tz)
    ist_time_str = now_ist.strftime("%d-%b-%Y %I:%M:%S %p IST")
    
    if alert_key in tg_alert_cache and (now_utc - tg_alert_cache[alert_key]).total_seconds() < cooldown_sec:
        return

    tg_alert_cache[alert_key] = now_utc

    cfg = SYMBOL_CONFIG.get(symbol_key, {"display": symbol_key, "label": "15 Minutes", "currency": "$"})
    display_name = cfg["display"]
    tf_label = cfg["label"]
    currency_symbol = cfg.get("currency", "$")

    price_str = f"{currency_symbol}{price:,.2f}" if isinstance(price, (int, float)) else "N/A"
    rsi_5m_str = f"{rsi_5m:.2f}" if isinstance(rsi_5m, (int, float)) and not pd.isna(rsi_5m) else "N/A"
    rsi_15m_str = f"{rsi_15m:.2f}" if isinstance(rsi_15m, (int, float)) and not pd.isna(rsi_15m) else "N/A"
    bubble_str = f"`{tp_bubble}`" if tp_bubble else "N/A"

    if category_title == "DEMAND":
        header_text = "🟢 *[DEMAND]* 🟢\n\n"
    elif category_title == "SUPPLY":
        header_text = "🔴 *[SUPPLY]* 🔴\n\n"
    elif category_title == "IMPORTANT LEVEL":
        header_text = f"🟡 *[IMPORTANT LEVEL: {level_name}]* 🟡\n\n" if level_name else "🟡 *[IMPORTANT LEVEL]* 🟡\n\n"
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
        f"• *Suggested TP Bubble:* {bubble_str}\n"
        f"• *Time (IST):* `{ist_time_str}`"
    )

    send_telegram_message(tg_message)

    if alert_key not in sms_alert_cache or (now_utc - sms_alert_cache[alert_key]).total_seconds() >= cooldown_sec:
        sms_alert_cache[alert_key] = now_utc
        label_info = f"IMPORTANT LEVEL ({level_name})" if level_name else category_title
        alert_text = f"ALERT ({tf_label}): {display_name} | {label_info} | Price: {price_str} | Bubble: {tp_bubble if tp_bubble else 'N/A'} | Time: {ist_time_str}"
        send_make_webhook({"body": alert_text, "text": alert_text, "message": alert_text})

# ==========================================
# MAIN SCANNER ROUTINE
# ==========================================
def analyze_market(symbol_key):
    try:
        if not is_market_open(symbol_key):
            return

        cfg = SYMBOL_CONFIG[symbol_key]
        df_main = fetch_candles(symbol_key, interval=cfg["interval_tv"], n_bars=150)
        if df_main is None or len(df_main) < 50:
            return

        live_price = float(df_main['close'].iloc[-1])
        live_high = float(df_main['high'].iloc[-1])
        live_low = float(df_main['low'].iloc[-1])

        htf_levels, support_bands, resistance_bands = get_ui_levels(symbol_key)

        # Helper to compute RSI & TP Bubble only when an alert triggers
        def get_alert_metrics():
            df_main['rsi_15m_calc'] = ta.rsi(df_main['close'], length=14, mamode='rma')
            rsi_15m = float(df_main['rsi_15m_calc'].iloc[-1])

            df_5m_temp = fetch_candles(symbol_key, interval=Interval.in_5_minute, n_bars=50)
            if df_5m_temp is not None and len(df_5m_temp) >= 15:
                df_5m_temp['rsi_5m_calc'] = ta.rsi(df_5m_temp['close'], length=14, mamode='rma')
                rsi_5m = float(df_5m_temp['rsi_5m_calc'].iloc[-1])
            else:
                rsi_5m = np.nan

            tp_bubble, _, _ = calculate_suggested_tp_bubble(df_main)
            return rsi_5m, rsi_15m, tp_bubble

        metrics_cache = None

        # 1. TWO SUPPORT BANDS (Daily Weak Demand & Daily Strong Demand)
        for band_name, (z_low, z_high) in support_bands.items():
            if live_low <= z_high and live_price >= z_low:
                if metrics_cache is None:
                    metrics_cache = get_alert_metrics()
                rsi_5m, rsi_15m, tp_bubble = metrics_cache
                process_alert(
                    alert_key=f"{symbol_key}_INSTANT_DEMAND_{band_name}_{z_high}",
                    symbol_key=symbol_key,
                    category_title="DEMAND",
                    price=live_price,
                    rsi_5m=rsi_5m,
                    rsi_15m=rsi_15m,
                    tp_bubble=tp_bubble,
                    cooldown_sec=ZONE_COOLDOWN_SEC
                )

        # 2. TWO RESISTANCE BANDS (Daily Weak Supply & Daily Strong Supply)
        for band_name, (z_low, z_high) in resistance_bands.items():
            if live_high >= z_low and live_price <= z_high:
                if metrics_cache is None:
                    metrics_cache = get_alert_metrics()
                rsi_5m, rsi_15m, tp_bubble = metrics_cache
                process_alert(
                    alert_key=f"{symbol_key}_INSTANT_SUPPLY_{band_name}_{z_low}",
                    symbol_key=symbol_key,
                    category_title="SUPPLY",
                    price=live_price,
                    rsi_5m=rsi_5m,
                    rsi_15m=rsi_15m,
                    tp_bubble=tp_bubble,
                    cooldown_sec=ZONE_COOLDOWN_SEC
                )

        # 3. HTF & PIVOT BADGES (PDH, PDL, PWH, PWL, PMH, PML, PP, Gann Base)
        for lvl_name, lvl_val in htf_levels.items():
            if pd.isna(lvl_val) or lvl_val == 0:
                continue
            touched_intrabar = (live_low <= lvl_val <= live_high)
            near_level = (abs(live_price - lvl_val) / lvl_val <= 0.0003)

            if touched_intrabar or near_level:
                if metrics_cache is None:
                    metrics_cache = get_alert_metrics()
                rsi_5m, rsi_15m, tp_bubble = metrics_cache
                process_alert(
                    alert_key=f"{symbol_key}_INSTANT_LEVEL_{lvl_name}_{round(lvl_val)}",
                    symbol_key=symbol_key,
                    category_title="IMPORTANT LEVEL",
                    price=live_price,
                    rsi_5m=rsi_5m,
                    rsi_15m=rsi_15m,
                    tp_bubble=tp_bubble,
                    cooldown_sec=ZONE_COOLDOWN_SEC,
                    level_name=lvl_name
                )

    except Exception as e:
        print(f"Error in scanner for {symbol_key}: {e}")

# ==========================================
# RUNTIME LOOP & FLASK SERVER
# ==========================================
scanner_started = False
scanner_start_lock = threading.Lock()

def core_market_scanner_loop():
    print("BTC, GOLD & NIFTY50 Full Engine Scanner Online...")
    send_telegram_message("*BTC, GOLD & NIFTY50 Full Engine Scanner Online*")
    
    while True:
        try:
            for symbol_key in SYMBOL_CONFIG.keys():
                analyze_market(symbol_key)
                time.sleep(1)
            time.sleep(30)
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(10)

def ensure_scanner_running():
    global scanner_started
    with scanner_start_lock:
        if not scanner_started:
            t = threading.Thread(target=core_market_scanner_loop, daemon=True)
            t.start()
            scanner_started = True

app = Flask(__name__)

@app.route('/')
@app.route('/health')
def home():
    ensure_scanner_running()
    return "Bot Status: ONLINE | Complete Engine (PDH, PDL, PP, Gann + Strict ML) Active", 200

if __name__ == "__main__":
    ensure_scanner_running()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
