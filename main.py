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
    return "Bot Matrix Status: ONLINE & MULTI-ASSET-CORE ENGINE ACTIVE 24/7", 200

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# CONFIGURATION & PARAMETERS
# ==========================================
# Crypto assets route via Coinbase Exchange, XAU-USD routes via Yahoo Finance API Pipeline
SYMBOLS = ["BTC-USD", "ETH-USD", "XAU-USD"] 
TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]

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
# MULTI-EXCHANGE DATA PIPELINE (COINBASE & YAHOO FINANCE)
# ==========================================
def fetch_candles(symbol, timeframe, limit=150):
    try:
        # ----------------------------------------------------
        # 🪙 GOLD FEED PIPELINE (YAHOO FINANCE)
        # ----------------------------------------------------
        if symbol == "XAU-USD":
            yf_interval_map = {
                "3m": "1m",   # Resampled below since 3m isn't native to YF
                "5m": "5m",
                "15m": "15m",
                "1h": "60m",
                "4h": "60m",  # Driven through the 4h math resampler
                "1d": "1d"
            }
            interval = yf_interval_map.get(timeframe, "5m")
            
            # Dynamic range to minimize bandwidth and fit rate constraints
            range_param = "1d" if interval in ["1m", "5m"] else "5d" if interval == "15m" else "60d"
            
            url = f"https://query1.financeapp.yahoo.com/v8/finance/chart/XAUUSD=X"
            params = {"interval": interval, "range": range_param}
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            
            response = requests.get(url, params=params, headers=headers)
            if response.status_code != 200:
                return None
                
            res = response.json().get("chart", {}).get("result", [None])[0]
            if not res:
                return None
                
            timestamps = res.get("timestamp", [])
            quote = res.get("indicators", {}).get("quote", [{}])[0]
            
            df = pd.DataFrame({
                'timestamp': timestamps,
                'low': quote.get('low', []),
                'high': quote.get('high', []),
                'open': quote.get('open', []),
                'close': quote.get('close', []),
                'volume': quote.get('volume', [0] * len(timestamps))
            })
            
            df = df.dropna(subset=['close']).reset_index(drop=True)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
            
            # Formulate the custom 3m timeframe if requested
            if timeframe == "3m":
                df = df.set_index('timestamp').resample('3min').agg({
                    'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
                }).dropna().reset_index()
                
            # Execute 4h math layer if targeted
            if timeframe == "4h":
                df = resample_to_4h(df)
                if df is None: return None
                
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
                
            return df.tail(limit).copy()

        # ----------------------------------------------------
        # 🚀 CRYPTO FEED PIPELINE (COINBASE)
        # ----------------------------------------------------
        else:
            cb_granularity_map = {
                "3m": 60,
                "5m": 300,
                "15m": 900,
                "1h": 3600,
                "4h": 3600,
                "1d": 86400
            }
            
            target_tf = "1h" if timeframe == "4h" else timeframe
            granularity = cb_granularity_map.get(target_tf, 300)
            
            url = f"https://api.exchange.coinbase.com/products/{symbol}/candles"
            params = {"granularity": granularity}
            headers = {"User-Agent": "CryptoAlertBot/1.0"}
            
            response = requests.get(url, params=params, headers=headers)
            if response.status_code != 200:
                return None
                
            data = response.json()
            if not data:
                return None
                
            df = pd.DataFrame(data, columns=['timestamp', 'low', 'high', 'open', 'close', 'volume'])
            df = df.iloc[::-1].reset_index(drop=True)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
            
            if timeframe == "4h":
                df = resample_to_4h(df)
                if df is None: return None
            
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
                
            return df.tail(limit).copy()
            
    except Exception as e:
        print(f"Data Pipeline Engine Error for {symbol} ({timeframe}): {e}")
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
    
    price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else "N/A"
    
    # 🔗 ENVIRONMENT CORRECTION FOR DEEP LINKS
    if symbol == "XAU-USD":
        tv_chart_url = "https://www.tradingview.com/chart/?symbol=OANDA:XAUUSD"
        feed_label = "OANDA Spot Feed"
    else:
        clean_symbol = symbol.replace("-", "")
        tv_chart_url = f"https://www.tradingview.com/chart/?symbol=COINBASE:{clean_symbol}"
        feed_label = "Coinbase Spot Feed"
        
    if "Support" in alert_type or "Bull" in alert_type:
        header = "🟢 *[LIVE BUY SIGNAL MATCHED]* 🟢"
    else:
        header = "🔴 *[LIVE SELL SIGNAL MATCHED]* 🔴"
    
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

def analyze_market(df, symbol):
    global active_zones
    if len(df) < TREND_LENGTH + 10:
        return
    
    tf = df.timeframe_meta
    
    # 🛡️ NO-REPAINT BOUNDARY LAYER RULES (ILOC[-2])
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
    print(f"Resampled Macro Asset Matrix Processing Engine Online...")
    send_telegram_message("🚀 *Macro Watchlist Engine Online* 🚀\nTracking Crypto & Gold Assets 24/7. Multi-Exchange pipelines operational.")
    
    while True:
        try:
            for symbol in SYMBOLS:
                for tf in TIMEFRAMES:
                    df = fetch_candles(symbol, tf)
                    if df is not None and not df.empty:
                        df.timeframe_meta = tf
                        analyze_market(df, symbol)
                    
                    # Small rest gap to respect public endpoint rate-limiting thresholds
                    time.sleep(1.5)
                        
            time.sleep(15)
        except Exception as e:
            print(f"Loop Engine Fault Trace: {e}")
            time.sleep(5)

if __name__ == "__main__":
    scanner_thread = threading.Thread(target=core_market_scanner_loop, daemon=True)
    scanner_thread.start()
    run_web_server()
