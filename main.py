import time
import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
import requests

# ==========================================
# CONFIGURATION & PARAMETERS
# ==========================================
SYMBOL = "ETH/USDT"  # Tracked asset matching your chart
TIMEFRAMES = ["3m", "5m", "15m", "1h", "4h", "1d"]
TREND_LENGTH = 50
RSI_LENGTH = 14
PCT_THRESH = 0.5 / 100  # 0.5%
SWING_LENGTH = 10
BOX_WIDTH = 2.5        # Replicates the Pine Script 'Supply/Demand Box Width' multiplier

# 🔴 TELEGRAM CREDENTIALS
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"

# Global data stores for zone structures
# Format: {"3m": [{"top": x, "bottom": y, "type": "demand"}, ...]}
active_zones = {tf: [] for tf in TIMEFRAMES}
alert_state_cache = {}

# Initialize exchange connection
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})

def send_telegram_message(message):
    """Transmits real-time alert updates directly to Telegram."""
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
        print(f"Network error sending Telegram notification: {e}")

def fetch_candles(symbol, timeframe, limit=100):
    """Fetches clean OHLCV structural tracking metrics from the API."""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        print(f"Error fetching data for {timeframe}: {e}")
        return None

def process_alert(alert_key, current_timestamp, alert_type, symbol, timeframe, message):
    """Enforces state constraints to prevent repetitive alert spamming."""
    global alert_state_cache
    if alert_state_cache.get(alert_key) == current_timestamp:
        return
        
    alert_state_cache[alert_key] = current_timestamp
    
    tg_message = (
        f"🚨 *[SIGNAL MATCHED] [{timeframe.upper()}]* 🚨\n\n"
        f"• *Asset:* `{symbol}`\n"
        f"• *Signal:* `{alert_type}`\n"
        f"• *Context:* {message}"
    )
    print(f"Sending Alert: {alert_key}")
    send_telegram_message(tg_message)

# ==========================================
# INDICATOR ENGINE WITH DYNAMIC BOX MATCHING
# ==========================================
def analyze_market(df, df_15m=None):
    global active_zones
    if len(df) < TREND_LENGTH + 10:
        return
    
    tf = df.timeframe_meta
    target_candle_time = str(df['timestamp'].iloc[-2])
    
    # Live running candle stats (Index -1)
    live_open = df['open'].iloc[-1]
    live_high = df['high'].iloc[-1]
    live_low = df['low'].iloc[-1]
    live_close = df['close'].iloc[-1]

    # --- 1. Technical Framework Calculations ---
    df['rsi'] = ta.rsi(df['close'], length=RSI_LENGTH)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=50)
    
    atr_val = df['atr'].iloc[-1] if not pd.isna(df['atr'].iloc[-1]) else df['close'].iloc[-1] * 0.002
    atr_buffer = atr_val * (BOX_WIDTH / 10.0)

    # --- 2. Multi-Timeframe 15m RSI Logic ---
    if df_15m is not None and not df_15m.empty:
        df_15m['rsi'] = ta.rsi(df_15m['close'], length=RSI_LENGTH)
        rsi_15m = df_15m['rsi'].iloc[-1]
    else:
        rsi_15m = df['rsi'].iloc[-2]

    # --- 3. Operator Candles Logic ---
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

    if bull_reversal:
        process_alert(f"{tf}_OC_Bull", target_candle_time, "Operator Bull Candle (OC)", SYMBOL, tf, "Institutional buying footprint established with 15m RSI verification.")
    if bear_reversal:
        process_alert(f"{tf}_OC_Bear", target_candle_time, "Operator Bear Candle (OC)", SYMBOL, tf, "Institutional selling footprint established with 15m RSI verification.")

    # --- 4. Supply & Demand Box Generation ---
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

    # Add verified swing highs as Supply Box structures
    if is_swing_high:
        top_edge = df['high'].iloc[idx]
        bottom_edge = top_edge - atr_buffer
        # Prevent overlapping duplicate zone tracking entries
        if not any(abs(z['top'] - top_edge) < atr_buffer for z in active_zones[tf]):
            active_zones[tf].append({"top": top_edge, "bottom": bottom_edge, "type": "supply"})
            
    # Add verified swing lows as Demand Box structures
    if is_swing_low:
        bottom_edge = df['low'].iloc[idx]
        top_edge = bottom_edge + atr_buffer
        if not any(abs(z['bottom'] - bottom_edge) < atr_buffer for z in active_zones[tf]):
            active_zones[tf].append({"top": top_edge, "bottom": bottom_edge, "type": "demand"})

    # --- 5. Live Candle Interaction Check (Zone Touches) ---
    remaining_zones = []
    for zone in active_zones[tf]:
        invalidated = False
        
        if zone['type'] == "demand":
            # Re-test match condition: Candle dips low enough to enter the box area
            if live_low <= zone['top'] and live_high >= zone['bottom']:
                process_alert(f"{tf}_demand_touch_{zone['bottom']}", target_candle_time, "Demand Zone Touched (Support)", SYMBOL, tf, 
                              f"Price retraced down into historical structural support window: `[{zone['bottom']:.2f} - {zone['top']:.2f}]`")
            
            # Break of Structure (BOS) mitigation check
            if live_close < zone['bottom']:
                invalidated = True
                
        elif zone['type'] == "supply":
            # Re-test match condition: Candle spikes high enough to enter the box area
            if live_high >= zone['bottom'] and live_low <= zone['top']:
                process_alert(f"{tf}_supply_touch_{zone['top']}", target_candle_time, "Supply Zone Touched (Resistance)", SYMBOL, tf, 
                              f"Price pushed up into historical structural resistance window: `[{zone['bottom']:.2f} - {zone['top']:.2f}]`")
            
            if live_close > zone['top']:
                invalidated = True

        if not invalidated:
            remaining_zones.append(zone)
            
    active_zones[tf] = remaining_zones

# ==========================================
# CORE LOOP ENGINE
# ==========================================
print(f"Scanning engine initializing for {SYMBOL}...")
send_telegram_message(f"✅ *Scanner Matrix Live* for `{SYMBOL}`. Actively tracking OCs and Zone Touches across all timeframes.")

while True:
    try:
        df_15m = fetch_candles(SYMBOL, "15m", limit=100)
        for tf in TIMEFRAMES:
            df = fetch_candles(SYMBOL, tf, limit=100)
            if df is not None:
                df.timeframe_meta = tf
                analyze_market(df, df_15m)
        time.sleep(10)
    except Exception as e:
        print(f"Loop runtime exception encounter: {e}")
        time.sleep(5)
