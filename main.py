import time
import threading
import os
import pandas as pd
import pandas_ta as ta
import numpy as np
import requests
from flask import Flask

# ==========================================
# 🔧 PANDAS-TA COMPATIBILITY LAYER
# ==========================================
for attr in ['int', 'float', 'bool']:
    if not hasattr(np, attr):
        setattr(np, attr, getattr(__builtins__, attr))

# ==========================================
# 🟢 FLASK SERVER
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Matrix Status: ONLINE & BUG-FREE ENGINE ACTIVE", 200

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

# Responsive execution parameters
SWING_LENGTH = 3  
BOX_WIDTH = 6.0     

TELEGRAM_TOKEN = "8992095386:AAFexnI8IRh990PlwZtkn6WkjeOV0yHjkCE"
TELEGRAM_CHAT_ID = "1136613703"

active_zones = {symbol: {tf: [] for tf in TIMEFRAMES} for symbol in SYMBOLS}
alert_state_cache = {}

# ==========================================
# TELEGRAM DISPATCH PIPELINE 
# ==========================================
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[❌ TELEGRAM ERROR]: {e}")

# ==========================================
# BINGX UNIFIED DATA PIPELINE (EXPLICITLY SORTED)
# ==========================================
def fetch_candles(symbol, timeframe, limit=150):
    try:
        interval = timeframe
        if symbol == "GOLD":
            url = "https://open-api.bingx.com/openApi/swap/v1/market/kline"
            params = {"symbol": "GOLD-USDT", "interval": interval, "limit": limit}
        else:
            url = "https://open-api.bingx.com/openApi/swap/v3/market/kline"
            params = {"symbol": symbol, "interval": interval, "limit": limit}
            
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, params=params, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return None
            
        res_data = response.json()
        raw_candles = res_data.get("data", [])
        
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
            
        df = pd.DataFrame(parsed_data)
        
        # 🔥 ANTI-BUG FIX 1: Explicitly sort by time ascending so index positions never flip
        df = df.sort_values(by="time_ms", ascending=True).reset_index(drop=True)
        return df
        
    except Exception as e:
        print(f"[❌ DATA ERROR] {symbol} ({timeframe}): {e}")
        return None

# ==========================================
# ALERT COMPILER
# ==========================================
def process_alert(alert_key, current_timestamp, alert_type, symbol, timeframe, message, price=None):
    global alert_state_cache
    
    live_tracking_key = f"{alert_key}_{current_timestamp}"
    if alert_state_cache.get(live_tracking_key):
        return  
        
    alert_state_cache[live_tracking_key] = True
    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A"
    
    tv_chart_url = "https://www.tradingview.com/chart/?symbol=OANDA:XAUUSD" if symbol == "GOLD" else f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol.replace('-', '')}"
    feed_label = "Gold Spot Feed" if symbol == "GOLD" else "Crypto Spot Feed"
    header = "🟢 *[LIVE BUY SIGNAL MATCHED]* 🟢" if ("Support" in alert_type or "Bull" in alert_type) else "🔴 *[LIVE SELL SIGNAL MATCHED]* 🔴"
    
    tg_message = (
        f"{header}\n\n"
        f"• *Asset:* [{symbol}]({tv_chart_url}) ({feed_label})\n"
        f"• *Price:* `{price_str}`\n"
        f"• *Timeframe:* [{timeframe.upper()}]({tv_chart_url})\n"
        f"• *Signal:* `{alert_type}`\n"
        f"• *Context:* {message}\n\n"
        f"📊 _Click the asset name to open this chart instantly on TradingView_"
    )
    send_telegram_message(tg_message)

# ==========================================
# STABLE MATH CORE ENGINE
# ==========================================
def analyze_market(df, symbol, tf):
    global active_zones
    if len(df) < TREND_LENGTH + 10:
        return
    
    # Precise extraction of closed and forming candles
    close_curr, open_curr, low_curr, high_curr = df['close'].iloc[-2], df['open'].iloc[-2], df['low'].iloc[-2], df['high'].iloc[-2]
    close_prev, open_prev = df['close'].iloc[-3], df['open'].iloc[-3]
    
    live_market_price = df['close'].iloc[-1]
    target_candle_time = str(df['timestamp'].iloc[-2])

    df['rsi'] = ta.rsi(df['close'], length=RSI_LENGTH)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=50)
    
    atr_val = df['atr'].iloc[-2] if not pd.isna(df['atr'].iloc[-2]) else df['close'].iloc[-2] * 0.002
    atr_buffer = atr_val * (BOX_WIDTH / 10.0)
    local_rsi = df['rsi'].iloc[-2]

    # Bullish Operator Candle Logic
    is_prev_red = close_prev < open_prev
    is_curr_green = close_curr > open_curr
    green_move_pct = (close_curr - low_curr) / low_curr if low_curr != 0 else 0
    is_engulfing_bull = (open_curr <= close_prev) and (close_curr > open_prev)
    
    bull_reversal = (is_prev_red and is_curr_green and is_engulfing_bull and 
                     (green_move_pct >= PCT_THRESH) and (35 < local_rsi < 75))

    # Bearish Operator Candle Logic
    is_prev_green = close_prev > open_prev
    is_curr_red = close_curr < open_curr
    red_move_pct = (high_curr - close_curr) / high_curr if high_curr != 0 else 0
    is_engulfing_bear = (open_curr >= close_prev) and (close_curr < open_prev)
    
    bear_reversal = (is_prev_green and is_curr_red and is_engulfing_bear and 
                     (red_move_pct >= PCT_THRESH) and (25 < local_rsi < 65))

    if bull_reversal:
        process_alert(f"{symbol}_{tf}_OC_Bull", target_candle_time, "Operator Bull Candle (OC)", symbol, tf, f"Bull engulfing valid on close. RSI: {local_rsi:.2f}", live_market_price)
    if bear_reversal:
        process_alert(f"{symbol}_{tf}_OC_Bear", target_candle_time, "Operator Bear Candle (OC)", symbol, tf, f"Bear engulfing valid on close. RSI: {local_rsi:.2f}", live_market_price)

    # Dynamic Peak Mapping Lookbacks
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
        
        # 🔥 ANTI-BUG FIX 2: Check standard intersection so gaps don't cause missed alerts
        if zone['type'] == "demand":
            if (low_curr <= zone['top'] and high_curr >= zone['bottom']) or (df['low'].iloc[-1] <= zone['top'] and df['high'].iloc[-1] >= zone['bottom']):
                process_alert(f"{symbol}_{tf}_demand_touch_{zone['bottom']}", target_candle_time, "Demand Zone Touched (Support)", symbol, tf, 
                              f"Price hit support zone: `[{zone['bottom']:.2f} - {zone['top']:.2f}]`", live_market_price)
            if close_curr < zone['bottom']:
                invalidated = True
                
        elif zone['type'] == "supply":
            if (high_curr >= zone['bottom'] and low_curr <= zone['top']) or (df['high'].iloc[-1] >= zone['bottom'] and df['low'].iloc[-1] <= zone['top']):
                process_alert(f"{symbol}_{tf}_supply_touch_{zone['top']}", target_candle_time, "Supply Zone Touched (Resistance)", symbol, tf, 
                              f"Price hit resistance zone: `[{zone['bottom']:.2f} - {zone['top']:.2f}]`", live_market_price)
            if close_curr > zone['top']:
                invalidated = True

        if not invalidated:
            remaining_zones.append(zone)
            
    active_zones[symbol][tf] = remaining_zones

# ==========================================
# RUNTIME LIFECYCLE
# ==========================================
def core_market_scanner_loop():
    print("BingX Data Core Engine Online...")
    send_telegram_message("🚀 *Macro Watchlist Engine Online* 🚀\nTracking BTC, ETH, and GOLD 24/7. System stable.")
    
    while True:
        try:
            for symbol in SYMBOLS:
                for tf in TIMEFRAMES:
                    df = fetch_candles(symbol, tf)
                    if df is not None and not df.empty:
                        analyze_market(df, symbol, tf)
                    time.sleep(0.25) # Perfectly balanced rate control gap
                        
            time.sleep(10)
        except Exception as e:
            print(f"[⚠️ ENGINE LOOP WARNING]: {e}")
            time.sleep(5)

if __name__ == "__main__":
    scanner_thread = threading.Thread(target=core_market_scanner_loop, daemon=True)
    scanner_thread.start()
    run_web_server()
