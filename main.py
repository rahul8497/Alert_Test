import time
import threading
import os
import datetime
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

# Macro tickers mapped exactly to standard Yahoo Finance formats
STOCK_LIST = ["BTC-USD", "ETH-USD", "GC=F"]

# ==========================================
# 📈 STARTUP PRICE-FILTERING LOGIC (ADAPTED FOR GLOBAL MACRO)
# ==========================================
def filter_and_initialize_symbols():
    """
    Scans the macro asset list and tracks them securely based on structural metrics.
    Capped upper bounds altered dynamically to accommodate high nominal value crypto indices.
    """
    active_list = []
    display_names = {}
    
    print("\n🔍 Evaluating Global Watchlist. Filtering out assets above $150,000...")
    for symbol in STOCK_LIST:
        try:
            stock = yf.Ticker(symbol)
            price = stock.fast_info.last_price
            
            # Use fallback if fast_info fails
            if price is None or price <= 0:
                history = stock.history(period="1d")
                if not history.empty:
                    price = history['Close'].iloc[-1]
            
            if price is not None and price > 0:
                if price <= 150000.0:  # Custom price filter ceiling for global macro tickers
                    active_list.append(symbol)
                    
                    friendly_name = symbol
                    if symbol == "BTC-USD": friendly_name = "BITCOIN (BTC/USD)"
                    elif symbol == "ETH-USD": friendly_name = "ETHEREUM (ETH/USD)"
                    elif symbol == "GC=F": friendly_name = "GOLD FUTURES"
                    
                    display_names[symbol] = friendly_name
                    print(f"✅ ACCEPTED: {symbol} (Price: ${price:.2f})")
            else:
                print(f"⚠️ SKIPPED: {symbol} (No pricing data)")
        except Exception as e:
            print(f"⚠️ ERROR evaluating {symbol}: {e}")
            
    print(f"\n🚀 Ready! Tracking {len(active_list)} Macro assets.\n")
    return active_list, display_names

# Run the initialization setup
ACTIVE_SYMBOLS, DISPLAY_NAMES = filter_and_initialize_symbols()

# ==========================================
# TECHNICAL PARAMETERS
# ==========================================
# Added 1m timeframe natively into the pipeline
TIMEFRAMES = ["1m", "3m", "5m", "15m", "1h", "4h", "1d"]

TREND_LENGTH = 50
RSI_LENGTH = 14
PCT_THRESH = 0.5 / 100  
SWING_LENGTH = 10
BOX_WIDTH = 2.0  

active_zones = {symbol: {tf: [] for tf in TIMEFRAMES} for symbol in ACTIVE_SYMBOLS}
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
# MATHEMATICAL RESAMPLING ENGINE FOR 4H ALIGNMENT
# ==========================================
def resample_to_4h(df_1h):
    try:
        if df_1h is None or df_1h.empty:
            return None
            
        df_1h = df_1h.set_index('timestamp')
        resample_rules = {
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }
        
        df_4h = df_1h.resample('4h', closed='left', label='left').agg(resample_rules)
        df_4h = df_4h.dropna(subset=['close']).reset_index()
        return df_4h
    except Exception as e:
        print(f"Mathematical resampling error: {e}")
        return None

# ==========================================
# DATA FETCHING PIPELINE
# ==========================================
def fetch_candles(symbol, timeframe, limit=100):
    try:
        target_tf = "60m" if timeframe == "4h" else timeframe
        # Mapped '1m' and '3m' correctly to valid yfinance parameters
        yf_tf_map = {"1m": "1m", "3m": "2m", "5m": "5m", "15m": "15m", "1h": "60m", "1d": "1d"}
        yf_tf = yf_tf_map.get(target_tf, "5m")
        
        # Pull plenty of historical tracking data frames depending on execution rate
        period_map = {"1m": "1d", "2m": "1d", "5m": "1d", "15m": "1d", "60m": "7d", "1d": "3mo"}
        fetch_period = "14d" if timeframe == "4h" else period_map.get(yf_tf, "5d")
        
        ticker = yf.Ticker(symbol)
        history = ticker.history(period=fetch_period, interval=yf_tf)
        
        if history.empty:
            return None
            
        df = history.reset_index()
        df.rename(columns={"Datetime": "timestamp", "Date": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}, inplace=True)
        
        if timeframe == "4h":
            df = resample_to_4h(df)
            if df is None:
                return None
                
        return df.tail(limit).copy()
    except Exception as e:
        return None

# ==========================================
# CORE STRATEGY ANALYSIS MATRIX (LIVE ALIGNED)
# ==========================================
def process_alert(alert_key, current_timestamp, alert_type, symbol, timeframe, message, price=None):
    global alert_state_cache
    live_tracking_key = f"{alert_key}_{current_timestamp}"
    
    if alert_state_cache.get(live_tracking_key) == True:
        return  
        
    alert_state_cache[live_tracking_key] = True
    
    display_name = DISPLAY_NAMES.get(symbol, symbol)
    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A"
    
    if "Support" in alert_type or "Bull" in alert_type:
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
    global active_zones
    if len(df) < TREND_LENGTH + 10:
        return
    
    tf = df.timeframe_meta
    
    close_curr, open_curr, low_curr, high_curr = df['close'].iloc[-1], df['open'].iloc[-1], df['low'].iloc[-1], df['high'].iloc[-1]
    close_prev, open_prev = df['close'].iloc[-2], df['open'].iloc[-2]
    target_candle_time = str(df['timestamp'].iloc[-1])

    df['rsi'] = ta.rsi(df['close'], length=RSI_LENGTH)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=50)
    
    atr_val = df['atr'].iloc[-1] if not pd.isna(df['atr'].iloc[-1]) else df['close'].iloc[-1] * 0.002
    atr_buffer = atr_val * (BOX_WIDTH / 10.0)
    local_rsi = df['rsi'].iloc[-1]

    # Bullish Operator Candle Logic Math
    is_prev_red = close_prev < open_prev
    is_curr_green = close_curr > open_curr
    green_move_pct = (close_curr - low_curr) / low_curr if low_curr != 0 else 0
    is_engulfing_bull = (open_curr <= close_prev) and (close_curr > open_prev)
    
    bull_reversal = (is_prev_red and is_curr_green and is_engulfing_bull and 
                     (green_move_pct >= PCT_THRESH) and (35 < local_rsi < 75))

    # Bearish Operator Candle Logic Math
    is_prev_green = close_prev > open_prev
    is_curr_red = close_curr < open_curr
    red_move_pct = (high_curr - close_curr) / high_curr if high_curr != 0 else 0
    is_engulfing_bear = (open_curr >= close_prev) and (close_curr < open_prev)
    
    bear_reversal = (is_prev_green and is_curr_red and is_engulfing_bear and 
                     (red_move_pct >= PCT_THRESH) and (25 < local_rsi < 65))

    if bull_reversal:
        process_alert(f"{symbol}_{tf}_OC_Bull", target_candle_time, "Operator Bull Candle (OC)", symbol, tf, f"Live Bull engulfing pattern validated. RSI: {local_rsi:.2f}", close_curr)
    if bear_reversal:
        process_alert(f"{symbol}_{tf}_OC_Bear", target_candle_time, "Operator Bear Candle (OC)", symbol, tf, f"Live Bear engulfing pattern validated. RSI: {local_rsi:.2f}", close_curr)

    # Zone calculation arrays
    idx = -(SWING_LENGTH + 2)
    is_swing_high, is_swing_low = True, True
    
    for check_i in range(1, SWING_LENGTH + 1):
        if df['high'].iloc[idx] <= df['high'].iloc[idx - check_i] or df['high'].iloc[idx] <= df['high'].iloc[idx + check_i]:
            is_swing_high = False
            break
    for check_i in range(1, SWING_LENGTH + 1):
        if df['low'].iloc[idx] >= df['low'].iloc[idx - check_i] or df['low'].iloc[idx] >= df['low'].iloc[idx + check_i]:
            is_swing_low = False
            break

    if is_swing_high:
        top_edge = df['high'].iloc[idx]
        bottom_edge = top_edge - atr_buffer
        if not any(abs(z['top'] - top_edge) < atr_buffer for z in active_zones[symbol][tf]):
            active_zones[symbol][tf].append({"top": top_edge, "bottom": bottom_edge, "type": "supply"})
            
    if is_swing_low:
        bottom_edge = df['low'].iloc[idx]
        top_edge = bottom_edge + atr_buffer
        if not any(abs(z['bottom'] - bottom_edge) < atr_buffer for z in active_zones[symbol][tf]):
            active_zones[symbol][tf].append({"top": top_edge, "bottom": bottom_edge, "type": "demand"})

    remaining_zones = []
    for zone in active_zones[symbol][tf]:
        invalidated = False
        
        if zone['type'] == "demand":
            if low_curr <= zone['top'] and high_curr >= zone['bottom']:
                process_alert(f"{symbol}_{tf}_demand_touch_{zone['bottom']}", target_candle_time, "Demand Zone Touched (Support)", symbol, tf, 
                              f"Live price pulled into support zone: `[${zone['bottom']:.2f} - ${zone['top']:.2f}]`", close_curr)
            if close_curr < zone['bottom']:
                invalidated = True
                
        elif zone['type'] == "supply":
            if high_curr >= zone['bottom'] and low_curr <= zone['top']:
                process_alert(f"{symbol}_{tf}_supply_touch_{zone['top']}", target_candle_time, "Supply Zone Touched (Resistance)", symbol, tf, 
                              f"Live price pushed into resistance zone: `[${zone['bottom']:.2f} - ${zone['top']:.2f}]`", close_curr)
            if close_curr > zone['top']:
                invalidated = True

        if not invalidated:
            remaining_zones.append(zone)
            
    active_zones[symbol][tf] = remaining_zones

# ==========================================
# RUNTIME SCANNER LIFECYCLE
# ==========================================
def core_market_scanner_loop():
    print(f"Global Macro Market Scanner Online...")
    send_telegram_message(
        f"🚀 *Macro Watchlist Engine Online* 🚀\n"
        f"• Monitoring dedicated bot feed via yfinance.\n"
        f"• Active watchlist assets: {len(ACTIVE_SYMBOLS)} (BTC, ETH, GOLD)"
    )
    
    while True:
        try:
            # Macro markets run 24/7/365, so we bypass traditional stock session parameters
            for symbol in ACTIVE_SYMBOLS:
                for tf in TIMEFRAMES:
                    df = fetch_candles(symbol, tf)
                    if df is not None and not df.empty:
                        df.timeframe_meta = tf
                        analyze_market(df, symbol)
                        
            time.sleep(15)
        except Exception as e:
            time.sleep(5)

if __name__ == "__main__":
    scanner_thread = threading.Thread(target=core_market_scanner_loop, daemon=True)
    scanner_thread.start()
    run_web_server()
