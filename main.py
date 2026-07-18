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
# 🟢 FLASK HEARTBEAT WEB SERVER FOR RENDER
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Matrix Status: BINGX MULTI-THREADED ENGINE ACTIVE 24/7", 200

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# CONFIGURATION & PARAMETERS
# ==========================================
SYMBOLS = ["BTC-USDT", "ETH-USDT", "GOLD"]
TIMEFRAMES = ["1m", "3m", "5m", "15m", "1h", "4h", "1d"]

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
# TELEGRAM DISPATCH PIPELINE
# ==========================================
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
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
            'time_ms': 'first',
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
# NATIVE BINGX REST DATA PIPELINE
# ==========================================
def fetch_candles(symbol, timeframe, limit=1000):
    try:
        target_tf = "1h" if timeframe == "4h" else timeframe

        if symbol == "GOLD":
            url = "https://open-api.bingx.com/openApi/swap/v1/market/kline"
            api_symbol = "GOLD-USDT"
        else:
            url = "https://open-api.bingx.com/openApi/swap/v3/market/kline"
            api_symbol = symbol

        fetch_limit = 1000 if timeframe in ["1m", "3m", "5m", "4h"] else 200
        
        params = {
            "symbol": api_symbol,
            "interval": target_tf,
            "limit": fetch_limit
        }
        
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, params=params, headers=headers, timeout=10)
        
        if response.status_code == 200:
            raw_candles = response.json().get("data", [])
            if not raw_candles:
                return None
                
            parsed_data = []
            for c in raw_candles:
                parsed_data.append({
                    "time_ms": int(c["time"]),
                    "timestamp": pd.to_datetime(int(c["time"]), unit='ms'),
                    "open": float(c["open"]), 
                    "high": float(c["high"]),
                    "low": float(c["low"]), 
                    "close": float(c["close"]), 
                    "volume": float(c["volume"])
                })
            
            df = pd.DataFrame(parsed_data).sort_values(by="time_ms", ascending=True).reset_index(drop=True)
            
            if timeframe == "4h":
                df = resample_to_4h(df)
                if df is None:
                    return None
                    
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

    display_names = {
        "BTC-USDT": "BITCOIN (BTC/USDT)", 
        "ETH-USDT": "ETHEREUM (ETH/USDT)", 
        "GOLD": "GOLD FUTURES"
    }
    display_name = display_names.get(symbol, symbol)
    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A"

    if "Support" in alert_type or "Bull" in alert_type:
        header = "🟢 *[LIVE BUY SIGNAL MATCHED]* 🟢"
    else:
        header = "🔴 *[LIVE SELL SIGNAL MATCHED]* 🔴"

    tg_message = (
        f"{header}\n\n"
        f"• *Asset:* `{display_name}`\n"
        f"• *Price:* `{price_str}`\n"
        f"• *Timeframe:* `{timeframe.upper()}`\n"
        f"• *Signal:* `{alert_type}`\n"
        f"• *Context:* {message}"
    )
    send_telegram_message(tg_message)

def analyze_market(df, symbol, tf):
    global active_zones
    if len(df) < TREND_LENGTH + 10:
        return

    live_close = df['close'].iloc[-1]
    live_high = df['high'].iloc[-1]
    live_low = df['low'].iloc[-1]
    live_candle_time = str(df['timestamp'].iloc[-1])

    close_curr, open_curr, low_curr, high_curr = df['close'].iloc[-2], df['open'].iloc[-2], df['low'].iloc[-2], df['high'].iloc[-2]
    close_prev, open_prev = df['close'].iloc[-3], df['open'].iloc[-3]
    closed_candle_time = str(df['timestamp'].iloc[-2])

    df['rsi'] = ta.rsi(df['close'], length=RSI_LENGTH)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=50)

    atr_val = df['atr'].iloc[-2] if not pd.isna(df['atr'].iloc[-2]) else df['close'].iloc[-2] * 0.002
    atr_buffer = atr_val * (BOX_WIDTH / 10.0)
    local_rsi = df['rsi'].iloc[-2]

    # 1. Closed Body Operator Candle triggers
    is_prev_red = close_prev < open_prev
    is_curr_green = close_curr > open_curr
    green_move_pct = (close_curr - low_curr) / low_curr if low_curr != 0 else 0
    is_engulfing_bull = (open_curr <= close_prev) and (close_curr > open_prev)

    bull_reversal = (is_prev_red and is_curr_green and is_engulfing_bull and 
                     (green_move_pct >= PCT_THRESH) and (35 < local_rsi < 75))

    is_prev_green = close_prev > open_prev
    is_curr_red = close_curr < open_curr
    red_move_pct = (high_curr - close_curr) / high_curr if high_curr != 0 else 0
    is_engulfing_bear = (open_curr >= close_prev) and (close_curr < open_prev)

    bear_reversal = (is_prev_green and is_curr_red and is_engulfing_bear and 
                     (red_move_pct >= PCT_THRESH) and (25 < local_rsi < 65))

    if bull_reversal:
        process_alert(f"{symbol}_{tf}_OC_Bull", closed_candle_time, "Operator Bull Candle (OC)", symbol, tf, f"CLOSED BODY VALIDATION: Confirmed on close. RSI: {local_rsi:.2f}", close_curr)
    if bear_reversal:
        process_alert(f"{symbol}_{tf}_OC_Bear", closed_candle_time, "Operator Bear Candle (OC)", symbol, tf, f"CLOSED BODY VALIDATION: Confirmed on close. RSI: {local_rsi:.2f}", close_curr)

    # 2. Dynamic Structural Zone Generation Arrays
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

    # 3. Instant Wick Zone Touch Triggers
    remaining_zones = []
    for zone in active_zones[symbol][tf]:
        invalidated = False

        if zone['type'] == "demand":
            if live_low <= zone['top'] and live_high >= zone['bottom']:
                process_alert(f"{symbol}_{tf}_demand_touch_{zone['bottom']}", live_candle_time, "Demand Zone Touched (Support)", symbol, tf, 
                              f"INSTANT WICK TRIGGER: Level coordinate hit: `[{zone['bottom']:.2f} - {zone['top']:.2f}]`", live_close)
            if close_curr < zone['bottom']:
                invalidated = True

        elif zone['type'] == "supply":
            if live_high >= zone['bottom'] and live_low <= zone['top']:
                process_alert(f"{symbol}_{tf}_supply_touch_{zone['top']}", live_candle_time, "Supply Zone Touched (Resistance)", symbol, tf, 
                              f"INSTANT WICK TRIGGER: Level coordinate hit: `[{zone['bottom']:.2f} - {zone['top']:.2f}]`", live_close)
            if close_curr > zone['top']:
                invalidated = True

        if not invalidated:
            remaining_zones.append(zone)

    active_zones[symbol][tf] = remaining_zones

# ==========================================
# ⚡ TIME-ISOLATED THREAD POOL SCANNER ENGINE
# ==========================================
def start_timeframe_worker(tf, loop_delay):
    """
    Spawns an isolated tracker channel loop focused strictly on a single timeframe interval.
    """
    print(f"Deploying background scanning worker thread for interval: {tf.upper()}")
    while True:
        try:
            for symbol in SYMBOLS:
                df = fetch_candles(symbol, tf)
                if df is not None and not df.empty:
                    analyze_market(df, symbol, tf)
                time.sleep(0.5) 
            time.sleep(loop_delay)
        except Exception as e:
            print(f"Exception encountered on worker thread ({tf}): {e}")
            time.sleep(5)

if __name__ == "__main__":
    # Launch core initialization alert card to Telegram channel
    send_telegram_message("🚀 *Multi-Threaded Macro Engine Online* 🚀\nTimeframe worker isolation active. Realtime monitoring engaged.")

    # Timeframe processing distribution map (Fast charts loop rapidly, slow charts rest)
    tf_distribution = {
        "1m": 2,    # 1-Minute chart loops continuously every 2 seconds
        "3m": 5,    # 3-Minute chart loops every 5 seconds
        "5m": 10,   # 5-Minute chart loops every 10 seconds
        "15m": 15,  
        "1h": 30,   
        "4h": 45,   
        "1d": 60    
    }

    # Spin up isolated threads for each tracking window matrix
    for timeframe, delay in tf_distribution.items():
        worker = threading.Thread(target=start_timeframe_worker, args=(timeframe, delay), daemon=True)
        worker.start()
        time.sleep(0.2) # Thread spawning cushion

    run_web_server()
