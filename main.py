import time
import json
import threading
import os
import gzip
import io
import pandas as pd
import pandas_ta as ta
import numpy as np
import requests
import websocket
from flask import Flask

# ==========================================
# 🔧 PANDAS-TA COMPATIBILITY LAYER
# ==========================================
for attr in ['int', 'float', 'bool']:
    if not hasattr(np, attr):
        setattr(np, attr, getattr(__builtins__, attr))

# ==========================================
# 🟢 FLASK SERVER FOR RENDER HEARTBEAT
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Matrix Status: REALTIME WEBSOCKET ACTIVE 24/7", 200

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# CONFIGURATION & PARAMETERS
# ==========================================
SYMBOLS = ["BTC-USDT", "ETH-USDT", "GOLD"] 
TIMEFRAMES = ["3m", "5m", "15m", "1h", "4h", "1d"]

TREND_LENGTH = 50
RSI_LENGTH = 14
PCT_THRESH = 0.5 / 100  

SWING_LENGTH = 3  
BOX_WIDTH = 6.0     

TELEGRAM_TOKEN = "8992095386:AAFexnI8IRh990PlwZtkn6WkjeOV0yHjkCE"
TELEGRAM_CHAT_ID = "1136613703"

# Memory Matrices
active_zones = {symbol: {tf: [] for tf in TIMEFRAMES} for symbol in SYMBOLS}
historical_candles = {symbol: {tf: None for tf in TIMEFRAMES} for symbol in SYMBOLS}
alert_state_cache = {}

# ==========================================
# TELEGRAM DISPATCH PIPELINE 
# ==========================================
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"[❌ TELEGRAM ERROR]: {e}")

# ==========================================
# SEEDING ENGINE (Pre-loads historical data)
# ==========================================
def seed_historical_data(symbol, tf):
    try:
        interval = tf
        if symbol == "GOLD":
            url = "https://open-api.bingx.com/openApi/swap/v1/market/kline"
            params = {"symbol": "GOLD-USDT", "interval": interval, "limit": 150}
        else:
            url = "https://open-api.bingx.com/openApi/swap/v3/market/kline"
            params = {"symbol": symbol, "interval": interval, "limit": 150}
            
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.status_code == 200:
            raw_candles = response.json().get("data", [])
            parsed_data = []
            for c in raw_candles:
                parsed_data.append({
                    "time_ms": int(c["time"]),
                    "timestamp": pd.to_datetime(int(c["time"]), unit='ms'),
                    "open": float(c["open"]), "high": float(c["high"]),
                    "low": float(c["low"]), "close": float(c["close"]), "volume": float(c["volume"])
                })
            df = pd.DataFrame(parsed_data).sort_values(by="time_ms", ascending=True).reset_index(drop=True)
            historical_candles[symbol][tf] = df
            print(f"[✅ SEEDED]: {symbol} {tf} cache built.")
    except Exception as e:
        print(f"[❌ SEEDING FAILED] For {symbol} {tf}: {e}")

# ==========================================
# CORE ALGO ENGINE (INSTANT CALCULATOR)
# ==========================================
def process_live_tick(symbol, tf, live_price, live_high, live_low, candle_timestamp):
    global active_zones, historical_candles
    
    df = historical_candles[symbol][tf]
    if df is None or len(df) < TREND_LENGTH:
        return
        
    # Inject live tick parameters into tracking metrics safely
    close_curr, open_curr, low_curr, high_curr = live_price, df['open'].iloc[-1], live_low, live_high
    close_prev, open_prev = df['close'].iloc[-2], df['open'].iloc[-2]
    
    target_candle_time = str(candle_timestamp)

    # Calculate indicators on historical dataframe sequence
    df_copy = df.copy()
    df_copy.loc[df_copy.index[-1], ['close', 'high', 'low']] = [live_price, live_high, live_low]
    
    df_copy['rsi'] = ta.rsi(df_copy['close'], length=RSI_LENGTH)
    df_copy['atr'] = ta.atr(df_copy['high'], df_copy['low'], df_copy['close'], length=50)
    
    atr_val = df_copy['atr'].iloc[-2] if not pd.isna(df_copy['atr'].iloc[-2]) else live_price * 0.002
    atr_buffer = atr_val * (BOX_WIDTH / 10.0)
    local_rsi = df_copy['rsi'].iloc[-2]

    # Reversal Candle Evaluation
    is_engulfing_bull = (open_curr <= close_prev) and (close_curr > open_prev)
    bull_reversal = (close_prev < open_prev) and (close_curr > open_curr) and is_engulfing_bull and ((close_curr - low_curr)/low_curr >= PCT_THRESH) and (35 < local_rsi < 75)

    is_engulfing_bear = (open_curr >= close_prev) and (close_curr < open_prev)
    bear_reversal = (close_prev > open_prev) and (close_curr < open_curr) and is_engulfing_bear and ((high_curr - close_curr)/high_curr >= PCT_THRESH) and (25 < local_rsi < 65)

    if bull_reversal:
        process_alert(f"{symbol}_{tf}_OC_Bull", target_candle_time, "Operator Bull Candle", symbol, tf, f"Instant confirmation. RSI: {local_rsi:.2f}", live_price)
    if bear_reversal:
        process_alert(f"{symbol}_{tf}_OC_Bear", target_candle_time, "Operator Bear Candle", symbol, tf, f"Instant confirmation. RSI: {local_rsi:.2f}", live_price)

    # Dynamic Zone Generator Realtime Checks
    idx = -(SWING_LENGTH + 2)
    is_swing_high, is_swing_low = True, True
    for check_i in range(1, SWING_LENGTH + 1):
        if df_copy['high'].iloc[idx] <= df_copy['high'].iloc[idx - check_i] or df_copy['high'].iloc[idx] <= df_copy['high'].iloc[idx + check_i]: is_swing_high = False; break
    for check_i in range(1, SWING_LENGTH + 1):
        if df_copy['low'].iloc[idx] >= df_copy['low'].iloc[idx - check_i] or df_copy['low'].iloc[idx] >= df_copy['low'].iloc[idx + check_i]: is_swing_low = False; break

    if is_swing_high:
        top_edge = df_copy['high'].iloc[idx]
        bottom_edge = top_edge - atr_buffer
        if not any(abs(z['top'] - top_edge) < atr_buffer for z in active_zones[symbol][tf]):
            active_zones[symbol][tf].append({"top": top_edge, "bottom": bottom_edge, "type": "supply"})
    if is_swing_low:
        bottom_edge = df_copy['low'].iloc[idx]
        top_edge = bottom_edge + atr_buffer
        if not any(abs(z['bottom'] - bottom_edge) < atr_buffer for z in active_zones[symbol][tf]):
            active_zones[symbol][tf].append({"top": top_edge, "bottom": bottom_edge, "type": "demand"})

    # Zone Hit Evaluation Engine
    remaining_zones = []
    for zone in active_zones[symbol][tf]:
        invalidated = False
        if zone['type'] == "demand":
            if live_low <= zone['top'] and live_high >= zone['bottom']:
                process_alert(f"{symbol}_{tf}_demand_touch_{zone['bottom']}", target_candle_time, "Demand Zone Touched (Support)", symbol, tf, f"Realtime Instant Touch: `[{zone['bottom']:.2f} - {zone['top']:.2f}]`", live_price)
            if live_price < zone['bottom']: invalidated = True
        elif zone['type'] == "supply":
            if live_high >= zone['bottom'] and live_low <= zone['top']:
                process_alert(f"{symbol}_{tf}_supply_touch_{zone['top']}", target_candle_time, "Supply Zone Touched (Resistance)", symbol, tf, f"Realtime Instant Touch: `[{zone['bottom']:.2f} - {zone['top']:.2f}]`", live_price)
            if live_price > zone['top']: invalidated = True
        if not invalidated: remaining_zones.append(zone)
    active_zones[symbol][tf] = remaining_zones

def process_alert(alert_key, current_timestamp, alert_type, symbol, timeframe, message, price=None):
    global alert_state_cache
    live_tracking_key = f"{alert_key}_{current_timestamp}"
    if alert_state_cache.get(live_tracking_key): return  
    alert_state_cache[live_tracking_key] = True
    
    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A"
    tv_chart_url = "https://www.tradingview.com/chart/?symbol=OANDA:XAUUSD" if symbol == "GOLD" else f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol.replace('-', '')}"
    header = "🟢 *[LIVE BUY SIGNAL MATCHED]* 🟢" if ("Support" in alert_type or "Bull" in alert_type) else "🔴 *[LIVE SELL SIGNAL MATCHED]* 🔴"
    
    tg_message = f"{header}\n\n• *Asset:* [{symbol}]({tv_chart_url})\n• *Price:* `{price_str}`\n• *Timeframe:* {timeframe.upper()}\n• *Signal:* `{alert_type}`\n• *Context:* {message}"
    send_telegram_message(tg_message)

# ==========================================
# ⚡ LIVE WEBSOCKET PIPELINE ENGINE
# ==========================================
def on_message(ws, message):
    try:
        # BingX WebSocket payloads are always compressed in gzip format
        compressed_data = gzip.GzipFile(fileobj=io.BytesIO(message)).read()
        data = json.loads(compressed_data.decode('utf-8'))
        
        # Keep connection alive
        if data.get("ping"):
            ws.send(json.dumps({"pong": data["ping"]}))
            return

        # Parse live incoming K-Line stream data packet
        if "kline" in data.get("dataType", ""):
            event_data = data.get("data", [])
            if not event_data: return
            
            c = event_data[0]
            symbol = data["dataType"].split("@")[0]
            # Normalize symbol name back to framework standards
            if symbol == "GOLD-USDT": symbol = "GOLD"
            
            tf = c["i"] # Timeframe string channel matching descriptor
            live_close = float(c["c"])
            live_high = float(c["h"])
            live_low = float(c["l"])
            candle_time = pd.to_datetime(int(c["t"]), unit='ms')
            
            # Process calculations instantly on the incoming price tick
            process_live_tick(symbol, tf, live_close, live_high, live_low, candle_time)
            
    except Exception as e:
        pass

def on_open(ws):
    print("WebSocket pipeline verified. Initializing data channel mapping subscriptions...")
    for symbol in SYMBOLS:
        for tf in TIMEFRAMES:
            # Seed the lookup array context first
            seed_historical_data(symbol, tf)
            
            # Subscribe to the target channel streaming feed
            sub_symbol = "GOLD-USDT" if symbol == "GOLD" else symbol
            sub_msg = {"id": f"sub_{symbol}_{tf}", "reqType": "sub", "dataType": f"{sub_symbol}@kline_{tf}"}
            ws.send(json.dumps(sub_msg))
            time.sleep(0.1)

def run_websocket_pipeline():
    websocket.setdefaulttimeout(15)
    # Open continuous stream link via BingX public socket router gateway
    ws_url = "wss://open-api-swap.bingx.com/swap-market"
    
    while True:
        try:
            ws = websocket.WebSocketApp(
                ws_url,
                on_message=on_message,
                on_open=on_open,
                on_error=lambda ws, err: print(f"[⚠️ WS TIMEOUT/ERROR]: {err}"),
                on_close=lambda ws, stat, msg: print("Stream disconnected. Restarting routing loop...")
            )
            ws.run_forever()
        except Exception as e:
            time.sleep(5)

if __name__ == "__main__":
    # Start live calculations engine
    ws_thread = threading.Thread(target=run_websocket_pipeline, daemon=True)
    ws_thread.start()
    
    # Run the background heartbeat dashboard web server
    run_web_server()
