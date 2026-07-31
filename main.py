import time
import threading
import os
import datetime
import math
import pandas as pd
import pandas_ta as ta
import numpy as np
import requests
import yfinance as yf
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
    return f"Bot Matrix Status: ONLINE | Scanning {len(ACTIVE_SYMBOLS)} Macro Assets Under $150,000", 200

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# 🚨 CONFIGURE YOUR NEW BOT & CHAT ID HERE 🚨
# ==========================================
TELEGRAM_TOKEN = "8992095386:AAFexnI8IRh990PlwZtkn6WkjeOV0yHjkCE"
TELEGRAM_CHAT_ID = "1136613703"

STOCK_LIST = ["BTC-USD", "ETH-USD", "XAUT-USD"]

# ==========================================
# 🐘 ELEPHANT EDGE & GANN CONFIGURATION
# ==========================================
CUSTOM_ZONES = {
    "Supply 1": {"top": 65903.60, "bottom": 65640.56},
    "Supply 2": {"top": 65156.30, "bottom": 64999.83},
    "Demand 1": {"top": 64392.83, "bottom": 64236.36},
    "Demand 2": {"top": 63752.10, "bottom": 63489.06}
}
MID_LINE = 64429.00

DAILY_CACHE = {} 
LAST_DAILY_FETCH = None

# ==========================================
# 📈 STARTUP PRICE-FILTERING LOGIC 
# ==========================================
def filter_and_initialize_symbols():
    active_list = []
    display_names = {}
    
    print("\n🔍 Evaluating Global Watchlist. Filtering out assets above $150,000...")
    for symbol in STOCK_LIST:
        try:
            stock = yf.Ticker(symbol)
            price = stock.fast_info.last_price
            
            if price is None or price <= 0:
                history = stock.history(period="1d")
                if not history.empty:
                    price = history['Close'].iloc[-1]
            
            if price is not None and price > 0:
                if price <= 150000.0:
                    active_list.append(symbol)
                    
                    friendly_name = symbol
                    if symbol == "BTC-USD": friendly_name = "BITCOIN (BTC/USD)"
                    elif symbol == "ETH-USD": friendly_name = "ETHEREUM (ETH/USD)"
                    elif symbol == "XAUT-USD": friendly_name = "GOLD SPOT (XAUT/USD)"
                    
                    display_names[symbol] = friendly_name
                    print(f"✅ ACCEPTED: {symbol} (Price: ${price:.2f})")
            else:
                print(f"⚠️ SKIPPED: {symbol} (No pricing data)")
        except Exception as e:
            print(f"⚠️ ERROR evaluating {symbol}: {e}")
            
    print(f"\n🚀 Ready! Tracking {len(active_list)} Macro assets.\n")
    return active_list, display_names

ACTIVE_SYMBOLS, DISPLAY_NAMES = filter_and_initialize_symbols()

# ==========================================
# TECHNICAL PARAMETERS
# ==========================================
# Added "5m" to the array below
TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"] 

TREND_LENGTH = 50
RSI_LENGTH = 14
PCT_THRESH = 0.5 / 100  
SWING_LENGTH = 10
BOX_WIDTH = 2.0  
LDP_LENGTH = 15 

ST_LENGTH = 14
ST_MULT = 3.5
OB_PIVOT_LEN = 7

active_zones = {symbol: {tf: [] for tf in TIMEFRAMES} for symbol in ACTIVE_SYMBOLS}
ldp_zones = {symbol: {tf: [] for tf in TIMEFRAMES} for symbol in ACTIVE_SYMBOLS} 
alert_state_cache = {}

# ==========================================
# TELEGRAM DISPATCH PIPELINE
# ==========================================
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Network error sending Telegram notification: {e}")

# ==========================================
# MATHEMATICAL RESAMPLING ENGINE
# ==========================================
def resample_to_4h(df_1h):
    try:
        if df_1h is None or df_1h.empty:
            return None
            
        df_1h = df_1h.set_index('timestamp')
        resample_rules = {
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
        }
        
        df_4h = df_1h.resample('4h', closed='left', label='left').agg(resample_rules)
        df_4h = df_4h.dropna(subset=['close']).reset_index()
        return df_4h
    except Exception as e:
        return None

# ==========================================
# DATA FETCHING PIPELINE
# ==========================================
def fetch_candles(symbol, timeframe, limit=100):
    try:
        target_tf = "60m" if timeframe == "4h" else timeframe
        yf_tf_map = {"1m": "1m", "3m": "2m", "5m": "5m", "15m": "15m", "1h": "60m", "1d": "1d"}
        yf_tf = yf_tf_map.get(target_tf, "5m")
        
        # Updated "5m" and "15m" to fetch 5d to guarantee enough candles for indicators
        period_map = {"1m": "1d", "2m": "1d", "5m": "5d", "15m": "5d", "60m": "7d", "1d": "3mo"}
        fetch_period = "14d" if timeframe == "4h" else period_map.get(yf_tf, "5d")
        
        ticker = yf.Ticker(symbol)
        history = ticker.history(period=fetch_period, interval=yf_tf)
        
        if history.empty:
            return None
            
        df = history.reset_index()
        df.rename(columns={"Datetime": "timestamp", "Date": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}, inplace=True)
        
        if timeframe == "4h":
            df = resample_to_4h(df)
            if df is None: return None
                
        return df.tail(limit).copy()
    except Exception as e:
        return None

# ==========================================
# CORE STRATEGY ANALYSIS MATRIX 
# ==========================================
def process_alert(alert_key, current_timestamp, alert_type, symbol, timeframe, message, price=None):
    global alert_state_cache
    live_tracking_key = f"{alert_key}_{current_timestamp}"
    
    if alert_state_cache.get(live_tracking_key) == True:
        return  
        
    alert_state_cache[live_tracking_key] = True
    
    display_name = DISPLAY_NAMES.get(symbol, symbol)
    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A"
    
    if "Support" in alert_type or "Bull" in alert_type or "SSL" in alert_type or "Demand" in alert_type:
        header = "🟢 *[MACRO BUY SIGNAL MATCHED]* 🟢"
    else:
        header = "🔴 *[MACRO SELL SIGNAL MATCHED]* 🔴"
    
    tg_message = (
        f"{header}\n\n"
        f"• *Asset:* `{display_name}`\n"
        f"• *Price:* `{price_str}`\n"
        f"• *Timeframe:* `{timeframe.upper()}`\n"
        f"• *Signal:* `{alert_type}`\n"
        f"• *Context:* {message}"
    )
    send_telegram_message(tg_message)

def analyze_market(df, symbol):
    global active_zones, ldp_zones, DAILY_CACHE
    
    if len(df) < TREND_LENGTH + max(SWING_LENGTH, LDP_LENGTH, OB_PIVOT_LEN*2) + 5:
        return
    
    tf = df.timeframe_meta
    
    df['rsi'] = ta.rsi(df['close'], length=RSI_LENGTH)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=50)

    st_df = ta.supertrend(df['high'], df['low'], df['close'], length=ST_LENGTH, multiplier=ST_MULT)
    if st_df is not None and not st_df.empty:
        st_dir_col = [col for col in st_df.columns if 'SUPERTd' in col][0]
        df['st_dir'] = st_df[st_dir_col]
    else:
        df['st_dir'] = 1 
    
    close_curr, open_curr, low_curr, high_curr = df['close'].iloc[-2], df['open'].iloc[-2], df['low'].iloc[-2], df['high'].iloc[-2]
    close_prev, open_prev = df['close'].iloc[-3], df['open'].iloc[-3]
    
    target_candle_time = str(df['timestamp'].iloc[-2])
    
    atr_val = df['atr'].iloc[-2] if not pd.isna(df['atr'].iloc[-2]) else df['close'].iloc[-2] * 0.002
    atr_buffer = atr_val * (BOX_WIDTH / 10.0)
    local_rsi = df['rsi'].iloc[-2]

    # --- 1. Operator Candle Alerts ---
    is_prev_red = close_prev < open_prev
    is_curr_green = close_curr > open_curr
    green_move_pct = (close_curr - low_curr) / low_curr if low_curr != 0 else 0
    is_engulfing_bull = (open_curr <= close_prev) and (close_curr > open_prev)
    bull_reversal = (is_prev_red and is_curr_green and is_engulfing_bull and (green_move_pct >= PCT_THRESH) and (35 < local_rsi < 75))

    is_prev_green = close_prev > open_prev
    is_curr_red = close_curr < open_curr
    red_move_pct = (high_curr - close_curr) / high_curr if high_curr != 0 else 0
    is_engulfing_bear = (open_curr >= close_prev) and (close_curr < open_prev)
    bear_reversal = (is_prev_green and is_curr_red and is_engulfing_bear and (red_move_pct >= PCT_THRESH) and (25 < local_rsi < 65))

    if bull_reversal:
        process_alert(f"{symbol}_{tf}_OC_Bull", target_candle_time, "Operator Bull Candle (OC)", symbol, tf, f"Confirmed Bull engulfing pattern validated at candle close. RSI: {local_rsi:.2f}", close_curr)
    if bear_reversal:
        process_alert(f"{symbol}_{tf}_OC_Bear", target_candle_time, "Operator Bear Candle (OC)", symbol, tf, f"Confirmed Bear engulfing pattern validated at candle close. RSI: {local_rsi:.2f}", close_curr)

    # --- 2. Supertrend Core/Glow Flip Alerts ---
    st_dir_curr = df['st_dir'].iloc[-2]
    st_dir_prev = df['st_dir'].iloc[-3]
    
    st_bull_flip = (st_dir_curr == 1 and st_dir_prev == -1)
    st_bear_flip = (st_dir_curr == -1 and st_dir_prev == 1)
    
    if st_bull_flip:
        process_alert(f"{symbol}_{tf}_ST_Bull_Glow", target_candle_time, "ATR Supertrend Bullish", symbol, tf, f"Bullish Supertrend Reversal activated at ${close_curr:.2f}.", close_curr)
    if st_bear_flip:
        process_alert(f"{symbol}_{tf}_ST_Bear_Glow", target_candle_time, "ATR Supertrend Bearish", symbol, tf, f"Bearish Supertrend Reversal activated at ${close_curr:.2f}.", close_curr)

    # --- 3. Live Touches (Elephant Edge Custom Zones & Midline) ---
    live_low, live_high, live_close = df['low'].iloc[-1], df['high'].iloc[-1], df['close'].iloc[-1]
    
    for zone_name, limits in CUSTOM_ZONES.items():
        if live_high >= limits["bottom"] and live_low <= limits["top"]:
            process_alert(
                f"{symbol}_{tf}_{zone_name.replace(' ', '_')}_Touch", 
                str(df['timestamp'].iloc[-1]), 
                f"{zone_name} Tested", 
                symbol, tf, 
                f"Price interacted with {zone_name}: `[${limits['bottom']:.2f} - ${limits['top']:.2f}]`", 
                live_close
            )

    if live_high >= MID_LINE and live_low <= MID_LINE:
        process_alert(
            f"{symbol}_{tf}_Midline_Touch", 
            str(df['timestamp'].iloc[-1]), 
            "Elephant Edge Midline Tested", 
            symbol, tf, 
            f"Price touched the Dotted Midline at `${MID_LINE:.2f}`", 
            live_close
        )

    # --- 4. Gann Square of 9 Alerts ---
    prev_close = DAILY_CACHE.get(symbol)
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
        
        buffer = live_close * 0.0005 
        
        for g_name, g_level in gann_levels.items():
            if live_high >= (g_level - buffer) and live_low <= (g_level + buffer):
                process_alert(
                    f"{symbol}_{tf}_Gann_{g_name.replace(' ', '_')}", 
                    str(df['timestamp'].iloc[-1]), 
                    f"Gann Level Tested", 
                    symbol, tf, 
                    f"Price tested Gann {g_name} at `${g_level:.2f}`", 
                    live_close
                )

# ==========================================
# RUNTIME SCANNER LIFECYCLE
# ==========================================
def core_market_scanner_loop():
    global LAST_DAILY_FETCH, DAILY_CACHE
    print(f"Global Macro Market Scanner Online...")
    send_telegram_message(
        f"🚀 *Macro Watchlist Engine Online* 🚀\n"
        f"• Monitoring dedicated bot feed via yfinance.\n"
        f"• Active watchlist assets: {len(ACTIVE_SYMBOLS)}\n"
        f"• Scanning Elephant Edge, Gann Levels, OC Candles, and Supertrend."
    )
    
    while True:
        try:
            current_date = datetime.datetime.utcnow().date()
            if current_date != LAST_DAILY_FETCH:
                print("Fetching Daily closes for Gann Math...")
                for symbol in ACTIVE_SYMBOLS:
                    daily_df = fetch_candles(symbol, "1d", limit=2)
                    if daily_df is not None and len(daily_df) > 1:
                        DAILY_CACHE[symbol] = daily_df['close'].iloc[-2] 
                LAST_DAILY_FETCH = current_date

            for symbol in ACTIVE_SYMBOLS:
                for tf in TIMEFRAMES:
                    df = fetch_candles(symbol, tf)
                    if df is not None and not df.empty:
                        df.timeframe_meta = tf
                        analyze_market(df, symbol)
                        
            time.sleep(15)
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    scanner_thread = threading.Thread(target=core_market_scanner_loop, daemon=True)
    scanner_thread.start()
    run_web_server()
