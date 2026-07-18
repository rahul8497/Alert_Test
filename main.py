import time
import threading
import os
import datetime
import pandas as pd
import pandas_ta as ta
import numpy as np
import requests
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
# 🟢 FLASK HEARTBEAT WEB SERVER FOR RENDER FREE TIER
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Matrix Status: ONLINE & COINBASE-TELEGRAM-TRADINGVIEW CORE ENGINE ACTIVE 24/7", 200

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# CONFIGURATION & PARAMETERS
# ==========================================
# Coinbase API standardizes product symbols with hyphens (e.g., BTC-USD)
SYMBOLS = ["BTC-USD", "ETH-USD"] 
TIMEFRAMES = ["3m", "5m", "15m", "1h", "4h", "1d"]

TREND_LENGTH = 50
RSI_LENGTH = 14
PCT_THRESH = 0.5 / 100  
SWING_LENGTH = 10
BOX_WIDTH = 2.0  

TELEGRAM_TOKEN = "8992095386:AAFexnI8IRh990PlwZtkn6WkjeOV0yHjkCE"
TELEGRAM_CHAT_ID = "1136613703"

active_zones = {symbol: {tf: [] for tf in TIMEFRAMES} for symbol in SYMBOLS}
alert_state_cache = {}

# ==========================================
# TELEGRAM DISPATCH PIPELINE WITH TRADINGVIEW ENHANCEMENTS
# ==========================================
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
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
# COINBASE PUBLIC EXCHANGE DATA PIPELINE
# ==========================================
def fetch_candles(symbol, timeframe, limit=150):
    try:
        # Step A: Map out timeframes to Coinbase granularity (represented in seconds)
        cb_granularity_map = {
            "3m": 60,       # Base on 1m candles if 3m isn't native, or fetch next available
            "5m": 300,      # 5 minutes
            "15m": 900,     # 15 minutes
            "1h": 3600,     # 1 hour
            "4h": 3600,     # Pulled via 1h for resampler consistency
            "1d": 86400     # 1 day
        }
        
        # Adjust target timeframe to fetch raw data for the 4h math engine
        target_tf = "1h" if timeframe == "4h" else timeframe
        granularity = cb_granularity_map.get(target_tf, 300)
        
        # Step B: Query Public API (No authentication keys required)
        url = f"https://api.exchange.coinbase.com/products/{symbol}/candles"
        params = {"granularity": granularity}
        
        headers = {"User-Agent": "CryptoAlertBot/1.0"}
        response = requests.get(url, params=params, headers=headers)
        
        if response.status_code != 200:
            return None
            
        data = response.json() # Returns a list of arrays: [time, low, high, open, close, volume]
        if not data:
            return None
            
        # Step C: Parse data array into Structured Dataframe
        df = pd.DataFrame(data, columns=['timestamp', 'low', 'high', 'open', 'close', 'volume'])
        
        # Coinbase API returns data ordered from newest to oldest; reverse it for technical analysis
        df = df.iloc[::-1].reset_index(drop=True)
        
        # Convert raw unix time to standard datetime format
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        
        # Execute 4h math layer if targeted
        if timeframe == "4h":
            df = resample_to_4h(df)
            if df is None:
                return None
        
        # Force float parameters across the data array
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
            
        return df.tail(limit).copy()
    except Exception as e:
        print(f"Coinbase Engine Error for {symbol} ({timeframe}): {e}")
        return None

# ==========================================
# CORE STRATEGY ANALYSIS MATRIX (NO-REPAINT MODE)
# ==========================================
def process_alert(alert_key, current_timestamp, alert_type, symbol, timeframe, message, price=None):
    global alert_state_cache
    
    live_tracking_key = f"{alert_key}_{current_timestamp}"
    
    if alert_state_cache.get(live_tracking_key) == True:
        return  
        
    alert_state_cache[live_tracking_key] = True
    
    # Generate clean layout metrics for display
    clean_symbol = symbol.replace("-", "") # Format BTC-USD to BTCUSD for links
    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A"
    
    # 🔗 BUILD TRADINGVIEW DEEP LINK PROTOCOLS
    # This constructs deep links targeting the Coinbase specific spot layout on TradingView
    tv_chart_url = f"https://www.tradingview.com/chart/?symbol=COINBASE:{clean_symbol}"
    
    if "Support" in alert_type or "Bull" in alert_type:
        header = "🟢 *[LIVE BUY SIGNAL MATCHED]* 🟢"
    else:
        header = "🔴 *[LIVE SELL SIGNAL MATCHED]* 🔴"
    
    tg_message = (
        f"{header}\n\n"
        f"• *Asset:* [{symbol}]({tv_chart_url}) (Coinbase Spot Feed)\n"
        f"• *Price:* `{price_str}`\n"
        f"• *Timeframe:* [{timeframe.upper()}]({tv_chart_url})\n"
        f"• *Signal:* `{alert_type}`\n"
        f"• *Context:* {message}\n\n"
        f"📊 _Click the asset name to open this chart instantly on TradingView_"
    )
    send_telegram_message(tg_message)

def analyze_market(df, symbol):
    global active_zones
    if len(df) < TREND_LENGTH + 10:
        return
    
    tf = df.timeframe_meta
    
    # ----------------------------------------------------
    # 🛡️ NO-REPAINT BOUNDARY LAYER RULES (ILOC[-2])
    # ----------------------------------------------------
    close_curr, open_curr, low_curr, high_curr = df['close'].iloc[-2], df['open'].iloc[-2], df['low'].iloc[-2], df['high'].iloc[-2]
    close_prev, open_prev = df['close'].iloc[-3], df['open'].iloc[-3]
    
    live_market_price = df['close'].iloc[-1]
    target_candle_time = str(df['timestamp'].iloc[-2])

    df['rsi'] = ta.rsi(df['close'], length=RSI_LENGTH)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=50)
    
    atr_val = df['atr'].iloc[-2] if not pd.isna(df['atr'].iloc[-2]) else df['close'].iloc[-2] * 0.002
    atr_buffer = atr_val * (BOX_WIDTH / 10.0)
    local_rsi = df['rsi'].iloc[-2]

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
        process_alert(f"{symbol}_{tf}_OC_Bull", target_candle_time, "Operator Bull Candle (OC)", symbol, tf, f"Confirmed Bull engulfing pattern validated on candle close. RSI: {local_rsi:.2f}", live_market_price)
    if bear_reversal:
        process_alert(f"{symbol}_{tf}_OC_Bear", target_candle_time, "Operator Bear Candle (OC)", symbol, tf, f"Confirmed Bear engulfing pattern validated on candle close. RSI: {local_rsi:.2f}", live_market_price)

    # Zone calculation arrays shift safe boundary offsets
    idx = -(SWING_LENGTH + 3)
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
                              f"Confirmed price pulled into support zone: `[{zone['bottom']:.2f} - {zone['top']:.2f}]`", live_market_price)
            if close_curr < zone['bottom']:
                invalidated = True
                
        elif zone['type'] == "supply":
            if high_curr >= zone['bottom'] and low_curr <= zone['top']:
                process_alert(f"{symbol}_{tf}_supply_touch_{zone['top']}", target_candle_time, "Supply Zone Touched (Resistance)", symbol, tf, 
                              f"Confirmed price pushed into resistance zone: `[{zone['bottom']:.2f} - {zone['top']:.2f}]`", live_market_price)
            if close_curr > zone['top']:
                invalidated = True

        if not invalidated:
            remaining_zones.append(zone)
            
    active_zones[symbol][tf] = remaining_zones

# ==========================================
# RUNTIME SCANNER LIFECYCLE
# ==========================================
def core_market_scanner_loop():
    print(f"Resampled Macro Asset Matrix Processing Engine Online via Coinbase API...")
    send_telegram_message("🚀 *Macro Watchlist Engine Online* 🚀\nTracking Coinbase API Spot pairs 24/7. TradingView Cross-Links operational.")
    
    while True:
        try:
            for symbol in SYMBOLS:
                for tf in TIMEFRAMES:
                    df = fetch_candles(symbol, tf)
                    if df is not None and not df.empty:
                        df.timeframe_meta = tf
                        analyze_market(df, symbol)
                    
                    # Small rest gap to respect Coinbase API public rate-limiting limits
                    time.sleep(1.5)
                        
            time.sleep(15)
        except Exception as e:
            print(f"Loop Engine Fault Trace: {e}")
            time.sleep(5)

if __name__ == "__main__":
    scanner_thread = threading.Thread(target=core_market_scanner_loop, daemon=True)
    scanner_thread.start()
    run_web_server()
