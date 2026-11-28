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
# 🚨 CREDENTIALS (GROUP + PERSONAL TELEGRAM) 🚨
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8992095386:AAFexnI8IRh990PlwZtkn6WkjeOV0yHjkCE")
GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID", "-5385748601")
PERSONAL_CHAT_ID = os.environ.get("PERSONAL_CHAT_ID", "1136613703")

TELEGRAM_CHAT_IDS = [cid.strip() for cid in [GROUP_CHAT_ID, PERSONAL_CHAT_ID] if cid and cid.strip()]

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
# TELEGRAM DISPATCH PIPELINE
# ==========================================
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        for _ in range(2):
            try:
                resp = http_session.post(url, json=payload, timeout=10)
                if resp.status_code == 200:
                    break
            except Exception as e:
                print(f"Error sending Telegram notification to {chat_id}: {e}")
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
                df.rename(columns={"datetime": "timestamp", "date": "timestamp"}, inplace=True)
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
# CORE ALERT PROCESSOR (TV UI COLOR-MATCHED)
# ==========================================
def process_alert(alert_key, symbol_key, category_title, price=None, rsi_5m=None, rsi_15m=None, cooldown_sec=14400, level_name=None):
    global tg_alert_cache
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

    # Match Telegram Header Color Emoji to TradingView Chart Badge Colors
    if category_title == "DEMAND":
        header_text = f"🟢 *[DEMAND: {level_name}]* 🟢\n\n" if level_name else "🟢 *[DEMAND]* 🟢\n\n"
    elif category_title == "SUPPLY":
        header_text = f"🔴 *[SUPPLY: {level_name}]* 🔴\n\n" if level_name else "🔴 *[SUPPLY]* 🔴\n\n"
    elif category_title == "IMPORTANT LEVEL":
        if level_name in ["PDH", "PDL"]:
            badge_icon = "🟡"  # Yellow badge on TV chart
        elif level_name in ["PWH", "PWL"]:
            badge_icon = "🟠"  # Orange badge on TV chart
        elif level_name in ["PMH", "PML"]:
            badge_icon = "🟣"  # Purple badge on TV chart
        elif level_name == "PP":
            badge_icon = "🩵"  # Light Blue badge on TV chart
        elif level_name == "Gann Base":
            badge_icon = "🔵"  # Dark Blue badge on TV chart
        else:
            badge_icon = "🟡"
            
        header_text = f"{badge_icon} *[IMPORTANT LEVEL: {level_name}]* {badge_icon}\n\n" if level_name else f"{badge_icon} *[IMPORTANT LEVEL]* {badge_icon}\n\n"
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
        f"• *Time (IST):* `{ist_time_str}`"
    )

    send_telegram_message(tg_message)

# ==========================================
# MAIN SCANNER ROUTINE
# ==========================================
def analyze_market(symbol_key):
    try:
        if not is_market_open(symbol_key):
            return

        cfg = SYMBOL_CONFIG[symbol_key]
        df_main = fetch_candles(symbol_key, interval=cfg["interval_tv"], n_bars=150)
        if df_main is None or len(df_main) < 20:
            return

        live_price = float(df_main['close'].iloc[-1])
        live_high = float(df_main['high'].iloc[-1])
        live_low = float(df_main['low'].iloc[-1])

        htf_levels, support_bands, resistance_bands = get_ui_levels(symbol_key)

        def get_rsi_metrics():
            df_main['rsi_15m_calc'] = ta.rsi(df_main['close'], length=14, mamode='rma')
            rsi_15m = float(df_main['rsi_15m_calc'].iloc[-1])

            df_5m_temp = fetch_candles(symbol_key, interval=Interval.in_5_minute, n_bars=150)
            if df_5m_temp is not None and len(df_5m_temp) >= 20:
                df_5m_temp['rsi_5m_calc'] = ta.rsi(df_5m_temp['close'], length=14, mamode='rma')
                rsi_5m = float(df_5m_temp['rsi_5m_calc'].iloc[-1])
            else:
                rsi_5m = np.nan

            return rsi_5m, rsi_15m

        rsi_cache = None

        # 1. TWO SUPPORT BANDS (Daily Weak Demand & Daily Strong Demand)
        for band_name, (z_low, z_high) in support_bands.items():
            if live_low <= z_high and live_price >= z_low:
                if rsi_cache is None:
                    rsi_cache = get_rsi_metrics()
                rsi_5m, rsi_15m = rsi_cache
                process_alert(
                    alert_key=f"{symbol_key}_INSTANT_DEMAND_{band_name}_{z_high}",
                    symbol_key=symbol_key,
                    category_title="DEMAND",
                    price=live_price,
                    rsi_5m=rsi_5m,
                    rsi_15m=rsi_15m,
                    cooldown_sec=ZONE_COOLDOWN_SEC,
                    level_name=band_name
                )

        # 2. TWO RESISTANCE BANDS (Daily Weak Supply & Daily Strong Supply)
        for band_name, (z_low, z_high) in resistance_bands.items():
            if live_high >= z_low and live_price <= z_high:
                if rsi_cache is None:
                    rsi_cache = get_rsi_metrics()
                rsi_5m, rsi_15m = rsi_cache
                process_alert(
                    alert_key=f"{symbol_key}_INSTANT_SUPPLY_{band_name}_{z_low}",
                    symbol_key=symbol_key,
                    category_title="SUPPLY",
                    price=live_price,
                    rsi_5m=rsi_5m,
                    rsi_15m=rsi_15m,
                    cooldown_sec=ZONE_COOLDOWN_SEC,
                    level_name=band_name
                )

        # 3. HTF & PIVOT BADGES (PDH, PDL, PWH, PWL, PMH, PML, PP, Gann Base)
        for lvl_name, lvl_val in htf_levels.items():
            if pd.isna(lvl_val) or lvl_val == 0:
                continue
            touched_intrabar = (live_low <= lvl_val <= live_high)
            near_level = (abs(live_price - lvl_val) / lvl_val <= 0.0003)

            if touched_intrabar or near_level:
                if rsi_cache is None:
                    rsi_cache = get_rsi_metrics()
                rsi_5m, rsi_15m = rsi_cache
                process_alert(
                    alert_key=f"{symbol_key}_INSTANT_LEVEL_{lvl_name}_{round(lvl_val)}",
                    symbol_key=symbol_key,
                    category_title="IMPORTANT LEVEL",
                    price=live_price,
                    rsi_5m=rsi_5m,
                    rsi_15m=rsi_15m,
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
    return "Bot Status: ONLINE | HTF, Support & Resistance Engine Active", 200

if __name__ == "__main__":
    ensure_scanner_running()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
