import time
import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
import requests
import yfinance as yf

# ==========================================
# CONFIGURATION & PARAMETERS
# ==========================================
# Expanded asset universe. '^NSEI' represents the Nifty 50 index ticker
SYMBOLS = ["ETH/USDT", "BTC/USDT", "XAU/USD", "^NSEI"]
TIMEFRAMES = ["3m", "5m", "15m", "1h", "4h", "1d"]

TREND_LENGTH = 50
RSI_LENGTH = 14
PCT_THRESH = 0.5 / 100  # 0.5% threshold filter
SWING_LENGTH = 10
BOX_WIDTH = 2.5        

# 🔴 TELEGRAM CREDENTIALS
TELEGRAM_TOKEN = "8992095386:AAFexnI8IRh990PlwZtkn6WkjeOV0yHjkCE"
TELEGRAM_CHAT_ID = "1136613703"

# Global data stores for zone structures mapped by asset and timeframe
active_zones = {symbol: {tf: [] for tf in TIMEFRAMES} for symbol in SYMBOLS}
alert_state_cache = {}

# Initialize broker routers
binance_exchange = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
oanda_exchange = ccxt.oanda({'enableRateLimit': True})

def send_telegram_message(message):
    """Transmits real-time alert updates directly to Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload)
    except Exception as e:
        print(f"Network error sending Telegram notification: {e}")

def fetch_candles(symbol, timeframe, limit=100):
    """Intelligently routes requests to Binance, OANDA, or Yahoo Finance based on symbol."""
    try:
        # Route 1: Yahoo Finance for Nifty Index
        if symbol == "^NSEI":
            # Map timeframe terminology to yfinance parameters
            yf_tf_map = {"3m": "2m", "5m": "5m", "15m": "15m", "1h": "60m", "4h": "1h", "1d": "1d"}
            yf_tf = yf_tf_map.get(timeframe, "5m")
            
            ticker = yf.Ticker(symbol)
            # Fetch a brief window to minimize processing delay
            period_map = {"2m": "1d", "5m": "1d", "15m": "1d", "60m": "5d", "1h": "7d", "1d": "1mo"}
            history = ticker.history(period=period_map.get(yf_tf, "5d"), interval=yf_tf)
            
            if history.empty:
                return None
                
            df = history.reset_index()
            # Standardize column labeling conventions across datasets
            df.rename(columns={"Datetime": "timestamp", "Date": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}, inplace=True)
            df = df.tail(limit).copy()
            return df

        # Route 2: OANDA for Gold
        elif "XAU" in symbol:
            ohlcv = oanda_exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        
        # Route 3: Binance for Cryptocurrencies
        else:
            ohlcv = binance_exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"Error fetching data for {symbol} on {timeframe}: {e}")
        return None

def process_alert(alert_key, current_timestamp, alert_type, symbol, timeframe, message):
    """Enforces state constraints to prevent repetitive alert spamming."""
    global alert_state_cache
    if alert_state_cache.get(alert_key) == current_timestamp:
        return
        
    alert_state_cache[alert_key] = current_timestamp
    display_name = "NIFTY 50" if symbol == "^NSEI" else symbol
    
    tg_message = (
        f"🚨 *[SIGNAL MATCHED]* 🚨\n\n"
        f"• *Asset:* `{display_name}`\n"
        f"• *Timeframe:* `{timeframe.upper()}`\n"
        f"• *Signal:* `{alert_type}`\n"
        f"• *Context:* {message}"
    )
    print(f"Sending Alert: {alert_key}")
    send_telegram_message(tg_message)

# ==========================================
# INDICATOR ENGINE
# ==========================================
def analyze_market(df, symbol):
    global active_zones
    if len(df) < TREND_LENGTH + 10:
        return
    
    tf = df.timeframe_meta
    target_candle_time = str(df['timestamp'].iloc[-2])
    
    live_open = df['open'].iloc[-1]
    live_high = df['high'].iloc[-1]
    live_low = df['low'].iloc[-1]
    live_close = df['close'].iloc[-1]

    df['rsi'] = ta.rsi(df['close'], length=RSI_LENGTH)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=50)
    
    atr_val = df['atr'].iloc[-1] if not pd.isna(df['atr'].iloc[-1]) else df['close'].iloc[-1] * 0.002
    atr_buffer = atr_val * (BOX_WIDTH / 10.0)

    local_rsi = df['rsi'].iloc[-2]

    # --- Operator Candles Logic ---
    close_curr, open_curr, low_curr, high_curr = df['close'].iloc[-2], df['open'].iloc[-2], df['low'].iloc[-2], df['high'].iloc[-2]
    close_prev, open_prev = df['close'].iloc[-3], df['open'].iloc[-3]

    is_prev_red = close_prev < open_prev
    is_curr_green = close_curr > open_curr
    green_move_pct = (close_curr - low_curr) / low_curr if low_curr != 0 else 0
    is_engulfing_bull = (open_curr <= close_prev) and (close_curr > open_prev)
    
    bull_reversal = (is_prev_red and is_curr_green and is_engulfing_bull and 
                     (green_move_pct >= PCT_THRESH) and (50 < local_rsi < 70))

    is_prev_green = close_prev > open_prev
    is_curr_red = close_curr < open_curr
    red_move_pct = (high_curr - close_curr) / high_curr if high_curr != 0 else 0
    is_engulfing_bear = (open_curr >= close_prev) and (close_curr < open_prev)
    
    bear_reversal = (is_prev_green and is_curr_red and is_engulfing_bear and 
                     (red_move_pct >= PCT_THRESH) and (30 < local_rsi < 50))

    if bull_reversal:
        process_alert(f"{symbol}_{tf}_OC_Bull", target_candle_time, "Operator Bull Candle (OC)", symbol, tf, f"Buy structural configuration validated. RSI: {local_rsi:.2f}")
    if bear_reversal:
        process_alert(f"{symbol}_{tf}_OC_Bear", target_candle_time, "Operator Bear Candle (OC)", symbol, tf, f"Sell structural configuration validated. RSI: {local_rsi:.2f}")

    # --- Supply & Demand Box Generation ---
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

    # --- Live Candle Zone Touches Check ---
    remaining_zones = []
    for zone in active_zones[symbol][tf]:
        invalidated = False
        
        if zone['type'] == "demand":
            if live_low <= zone['top'] and live_high >= zone['bottom']:
                process_alert(f"{symbol}_{tf}_demand_touch_{zone['bottom']}", target_candle_time, "Demand Zone Touched (Support)", symbol, tf, 
                              f"Price retraced into support zone: `[{zone['bottom']:.2f} - {zone['top']:.2f}]`")
            if live_close < zone['bottom']:
                invalidated = True
                
        elif zone['type'] == "supply":
            if live_high >= zone['bottom'] and live_low <= zone['top']:
                process_alert(f"{symbol}_{tf}_supply_touch_{zone['top']}", target_candle_time, "Supply Zone Touched (Resistance)", symbol, tf, 
                              f"Price pushed into resistance zone: `[{zone['bottom']:.2f} - {zone['top']:.2f}]`")
            if live_close > zone['top']:
                invalidated = True

        if not invalidated:
            remaining_zones.append(zone)
            
    active_zones[symbol][tf] = remaining_zones

# ==========================================
# RUNTIME LOOP
# ==========================================
print(f"Unified Scanner Matrix Online for {SYMBOLS}")
send_telegram_message("🚀 *Multi-Exchange Strategic Scanner Activated* 🚀\nMonitoring setups for `ETH`, `BTC`, `GOLD`, and `NIFTY 50` across all intervals.")

while True:
    try:
        for symbol in SYMBOLS:
            # Skip checking Nifty entirely if Indian markets are closed for the weekend/night
            if symbol == "^NSEI":
                current_utc_hour = time.gmtime().tm_hour
                current_utc_day = time.gmtime().tm_wday
                # Filter out market downtime (Weekend filtering check)
                if current_utc_day >= 5:
                    continue

            for tf in TIMEFRAMES:
                df = fetch_candles(symbol, tf, limit=100)
                if df is not None and not df.empty:
                    df.timeframe_meta = tf
                    analyze_market(df, symbol)
                    
        time.sleep(15)
    except Exception as e:
        print(f"Loop runtime tracking anomaly: {e}")
        time.sleep(5)
