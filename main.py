import time
import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
import requests

# ==========================================
# CONFIGURATION & PARAMETERS
# ==========================================
SYMBOL = "BTC/USDT"
TIMEFRAMES = ["3m", "5m", "15m", "1h", "4h", "1d"]
TREND_LENGTH = 50
RSI_LENGTH = 14
PCT_THRESH = 0.5 / 100  # 0.5%
SWING_LENGTH = 10

# 🔴 TELEGRAM CREDENTIALS (REPLACE THESE WITH YOURS)
TELEGRAM_TOKEN = "8992095386:AAFexnI8IRh990PlwZtkn6WkjeOV0yHjkCE"
TELEGRAM_CHAT_ID = "1136613703"

# State cache tracking to avoid duplicate alert spamming
# Structure: { "3m_Operator_Bull": Timestamp, ... }
alert_state_cache = {}

# Initialize exchange connection
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}  # Uses perpetual data
})

def send_telegram_message(message):
    """Sends a real-time markdown message to the assigned Telegram Chat ID."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            print(f"Telegram API Error: {response.text}")
    except Exception as e:
        print(f"Failed to transmit Telegram network request: {e}")

def fetch_candles(symbol, timeframe, limit=100):
    """Fetches historical candlestick data from the exchange."""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"Error fetching data for {timeframe}: {e}")
        return None

def process_alert(alert_key, current_timestamp, alert_type, symbol, timeframe, message):
    """Checks the global state cache and triggers an alert if this is a fresh occurrence."""
    global alert_state_cache
    
    # If this specific candle has already triggered this specific alert, skip it
    if alert_state_cache.get(alert_key) == current_timestamp:
        return
        
    # Update cache state
    alert_state_cache[alert_key] = current_timestamp
    
    # Format Telegram payload string using clean markdown formatting
    tg_message = (
        f"🚨 *[ALERT] [{timeframe.upper()}]* 🚨\n\n"
        f"• *Asset:* `{symbol}`\n"
        f"• *Signal Type:* `{alert_type}`\n"
        f"• *Details:* {message}"
    )
    
    print(f"Triggering Alert: {alert_key} for candle time {current_timestamp}")
    send_telegram_message(tg_message)

# ==========================================
# INDICATOR CORE ENGINE
# ==========================================
def analyze_market(df, df_15m=None):
    """Processes indicator signals and routes live alerts."""
    if len(df) < TREND_LENGTH + 10:
        return
    
    tf = df.timeframe_meta
    
    # Target the most recently completed/closed candle [-2] for matrix analysis
    # Target index [-1] is the incomplete live candle, which will generate duplicate alerts
    target_candle_time = str(df['timestamp'].iloc[-2])

    # --- 1. Linear Regression Trend Line ---
    linreg_series = ta.linreg(df['close'], length=TREND_LENGTH)

    # --- 2. RSI Execution ---
    df['rsi'] = ta.rsi(df['close'], length=RSI_LENGTH)
    
    # --- 3. Operator Candles Logic ---
    if df_15m is not None and not df_15m.empty:
        df_15m['rsi'] = ta.rsi(df_15m['close'], length=RSI_LENGTH)
        rsi_15m = df_15m['rsi'].iloc[-1]
    else:
        rsi_15m = df['rsi'].iloc[-2]

    close_curr, open_curr, low_curr, high_curr = df['close'].iloc[-2], df['open'].iloc[-2], df['low'].iloc[-2], df['high'].iloc[-2]
    close_prev, open_prev = df['close'].iloc[-3], df['open'].iloc[-3]

    is_prev_red = close_prev < open_prev
    is_curr_green = close_curr > open_curr
    green_move_pct = (close_curr - low_curr) / low_curr if low_curr != 0 else 0
    is_engulfing_bull = (open_curr <= close_prev) and (close_curr > open_prev)
    
    bull_reversal = (is_prev_red and is_curr_green and is_engulfing_bull and 
                     (green_move_pct >= PCT_THRESH) and (50 < rsi_15m < 70))

    is_prev_green = close_prev > open_prev
    is_curr_red = close_curr < open_curr
    red_move_pct = (high_curr - close_curr) / high_curr if high_curr != 0 else 0
    is_engulfing_bear = (open_curr >= close_prev) and (close_curr < open_prev)
    
    bear_reversal = (is_prev_green and is_curr_red and is_engulfing_bear and 
                     (red_move_pct >= PCT_THRESH) and (30 < rsi_15m < 50))

    # --- 4. Supply & Demand Zone Structural Pivot Logic ---
    idx = -(SWING_LENGTH + 2) # Check standard fixed historical displacement window
    
    is_swing_high = True
    is_swing_low = True
    
    # Pivot High verification loop
    for check_i in range(1, SWING_LENGTH + 1):
        if df['high'].iloc[idx] <= df['high'].iloc[idx - check_i] or df['high'].iloc[idx] <= df['high'].iloc[idx + check_i]:
            is_swing_high = False
            break
            
    # Pivot Low verification loop
    for check_i in range(1, SWING_LENGTH + 1):
        if df['low'].iloc[idx] >= df['low'].iloc[idx - check_i] or df['low'].iloc[idx] >= df['low'].iloc[idx + check_i]:
            is_swing_low = False
            break

    # --- 5. Routing Match System ---
    if bull_reversal:
        process_alert(f"{tf}_operator_bull", target_candle_time, "Operator Bull Candle", SYMBOL, tf, "Reversal pattern verified with 15m RSI cross confirmation filters.")
        
    if bear_reversal:
        process_alert(f"{tf}_operator_bear", target_candle_time, "Operator Bear Candle", SYMBOL, tf, "Reversal pattern verified with 15m RSI cross confirmation filters.")
        
    if is_swing_high:
        pivot_time = str(df['timestamp'].iloc[idx])
        process_alert(f"{tf}_supply_zone", pivot_time, "New Supply Zone Established", SYMBOL, tf, f"Structural peak point registered at price level {df['high'].iloc[idx]}")
        
    if is_swing_low:
        pivot_time = str(df['timestamp'].iloc[idx])
        process_alert(f"{tf}_demand_zone", pivot_time, "New Demand Zone Established", SYMBOL, tf, f"Structural trough point registered at price level {df['low'].iloc[idx]}")

# ==========================================
# SYSTEM RUNTIME EXECUTION LOOP
# ==========================================
print(f"Starting Multi-Timeframe Telegram Bot Engine for {SYMBOL}...")
send_telegram_message(f"🚀 *Algorithmic Trading Bot Scanner Online* for `{SYMBOL}`. Monitoring 3m, 5m, 15m, 1h, 4h, and 1d timeframes...")

while True:
    try:
        # Pre-fetch context structural tracking metrics
        df_15m = fetch_candles(SYMBOL, "15m", limit=100)
        
        for tf in TIMEFRAMES:
            df = fetch_candles(SYMBOL, tf, limit=100)
            if df is not None:
                df.timeframe_meta = tf
                analyze_market(df, df_15m)
                
        # Scans the tickers every 15 seconds for rapid state detection
        time.sleep(15)
        
    except Exception as e:
        print(f"System Loop Failure Context Exception: {e}")
        time.sleep(5)
