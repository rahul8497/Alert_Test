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

STOCK_LIST = ["BTC-USD", "ETH-USD", "XAUT-USD"]

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
TIMEFRAMES = ["15m", "1h", "4h", "1d"]

TREND_LENGTH = 50
RSI_LENGTH = 14
PCT_THRESH = 0.5 / 100  
SWING_LENGTH = 10
BOX_WIDTH = 2.0  
LDP_LENGTH = 15 # Period for the 100% Liquidity Zones

# NEW: Supertrend & Order Block Config
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
    global active_zones, ldp_zones
    
    if len(df) < TREND_LENGTH + max(SWING_LENGTH, LDP_LENGTH, OB_PIVOT_LEN*2) + 5:
        return
    
    tf = df.timeframe_meta
    
    df['rsi'] = ta.rsi(df['close'], length=RSI_LENGTH)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=50)

    # ---------------------------------------------------------
    # NEW: 0. ATR Supertrend Calculation (Matches Pine Script)
    # ---------------------------------------------------------
    st_df = ta.supertrend(df['high'], df['low'], df['close'], length=ST_LENGTH, multiplier=ST_MULT)
    if st_df is not None and not st_df.empty:
        # Dynamically extract direction column based on length/mult
        st_dir_col = [col for col in st_df.columns if 'SUPERTd' in col][0]
        df['st_dir'] = st_df[st_dir_col]
    else:
        df['st_dir'] = 1 # Fallback

    # ---------------------------------------------------------
    
    # index alignment for locked-in closed bar evaluation
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


    # --- NEW: Supertrend Core/Glow Flip Alerts ---
    st_dir_curr = df['st_dir'].iloc[-2]
    st_dir_prev = df['st_dir'].iloc[-3]
    
    st_bull_flip = (st_dir_curr == 1 and st_dir_prev == -1)
    st_bear_flip = (st_dir_curr == -1 and st_dir_prev == 1)
    
    if st_bull_flip:
        process_alert(f"{symbol}_{tf}_ST_Bull_Glow", target_candle_time, "ATR Supertrend Bullish (Core/Glow)", symbol, tf, f"Bullish Supertrend Reversal activated at ${close_curr:.2f}.", close_curr)
    if st_bear_flip:
        process_alert(f"{symbol}_{tf}_ST_Bear_Glow", target_candle_time, "ATR Supertrend Bearish (Core/Glow)", symbol, tf, f"Bearish Supertrend Reversal activated at ${close_curr:.2f}.", close_curr)


    # --- NEW: Order Block % Formation Logic ---
    idx_ob = -(OB_PIVOT_LEN + 2) # Delay by PIVOT_LEN to confirm the swing
    is_ob_bull, is_ob_bear = True, True
    
    # Check Pivot Low (Bullish OB)
    for i in range(1, OB_PIVOT_LEN + 1):
        if df['low'].iloc[idx_ob] >= df['low'].iloc[idx_ob - i] or df['low'].iloc[idx_ob] >= df['low'].iloc[idx_ob + i]:
            is_ob_bull = False
            break
            
    # Check Pivot High (Bearish OB)
    for i in range(1, OB_PIVOT_LEN + 1):
        if df['high'].iloc[idx_ob] <= df['high'].iloc[idx_ob - i] or df['high'].iloc[idx_ob] <= df['high'].iloc[idx_ob + i]:
            is_ob_bear = False
            break
            
    if is_ob_bull or is_ob_bear:
        buy_vol, sell_vol = 0.0, 0.0
        buy_range, sell_range = 0.0, 0.0
        
        # Calculate volume percentages dynamically over the pivot evaluation window
        for i in range(-2 - OB_PIVOT_LEN + 1, -1):
            o, c, v = df['open'].iloc[i], df['close'].iloc[i], df['volume'].iloc[i]
            body = abs(c - o)
            if c >= o:
                buy_vol += v; buy_range += body
            else:
                sell_vol += v; sell_range += body
                
        total_vol = buy_vol + sell_vol
        total_range = buy_range + sell_range
        
        # Volume fallback math if tick vol is 0
        buy_pct = (buy_vol / total_vol) if total_vol > 0 else ((buy_range / total_range) if total_range > 0 else 0.5)
        sell_pct = 1.0 - buy_pct
        
        if is_ob_bull:
            ob_price = df['low'].iloc[idx_ob]
            process_alert(f"{symbol}_{tf}_OB_Bull_Pct_{ob_price}", target_candle_time, "Bullish OB % Formation", symbol, tf, f"Bullish Order Block Confirmed at pivot low.\nBuy Vol: `{buy_pct*100:.0f}%` / Sell Vol: `{sell_pct*100:.0f}%`", ob_price)
            
        if is_ob_bear:
            ob_price = df['high'].iloc[idx_ob]
            process_alert(f"{symbol}_{tf}_OB_Bear_Pct_{ob_price}", target_candle_time, "Bearish OB % Formation", symbol, tf, f"Bearish Order Block Confirmed at pivot high.\nSell Vol: `{sell_pct*100:.0f}%` / Buy Vol: `{buy_pct*100:.0f}%`", ob_price)


    # --- 2. 100% LDP Lines (Buy/Sell Side Liquidity) Creation ---
    idx_ldp = -(LDP_LENGTH + 2) 
    is_ldp_ph, is_ldp_pl = True, True
    
    for check_i in range(1, LDP_LENGTH + 1):
        if df['high'].iloc[idx_ldp] <= df['high'].iloc[idx_ldp - check_i] or df['high'].iloc[idx_ldp] <= df['high'].iloc[idx_ldp + check_i]:
            is_ldp_ph = False
            break
    for check_i in range(1, LDP_LENGTH + 1):
        if df['low'].iloc[idx_ldp] >= df['low'].iloc[idx_ldp - check_i] or df['low'].iloc[idx_ldp] >= df['low'].iloc[idx_ldp + check_i]:
            is_ldp_pl = False
            break

    # Calculate zone boundaries based on your Pine logic
    ldp_atr = df['atr'].iloc[idx_ldp] if not pd.isna(df['atr'].iloc[idx_ldp]) else df['close'].iloc[idx_ldp] * 0.002
    
    if is_ldp_ph:
        pHigh = df['high'].iloc[idx_ldp]
        pBot = max(df['close'].iloc[idx_ldp], df['open'].iloc[idx_ldp])
        if pHigh - pBot < ldp_atr * 0.1: pBot = pHigh - ldp_atr * 0.1
        
        if not any(max(pBot, z['bottom']) <= min(pHigh, z['top']) for z in ldp_zones[symbol][tf] if z['type'] == 'BSL'):
            ldp_zones[symbol][tf].append({"top": pHigh, "bottom": pBot, "type": "BSL"})
            process_alert(f"{symbol}_{tf}_LDP_BSL_Formed_{pHigh}", str(df['timestamp'].iloc[-1]), "100% Buy-Side Liquidity Formed", symbol, tf, f"Fresh 100% LDP Resistance Zone formed at `[${pBot:.2f} - ${pHigh:.2f}]`", pHigh)
            
    if is_ldp_pl:
        pLow = df['low'].iloc[idx_ldp]
        pTop = min(df['close'].iloc[idx_ldp], df['open'].iloc[idx_ldp])
        if pTop - pLow < ldp_atr * 0.1: pTop = pLow + ldp_atr * 0.1
        
        if not any(max(pLow, z['bottom']) <= min(pTop, z['top']) for z in ldp_zones[symbol][tf] if z['type'] == 'SSL'):
            ldp_zones[symbol][tf].append({"top": pTop, "bottom": pLow, "type": "SSL"})
            process_alert(f"{symbol}_{tf}_LDP_SSL_Formed_{pLow}", str(df['timestamp'].iloc[-1]), "100% Sell-Side Liquidity Formed", symbol, tf, f"Fresh 100% LDP Support Zone formed at `[${pLow:.2f} - ${pTop:.2f}]`", pLow)


    # --- 3. Live Touches (LDP Zones & General POI Zones) ---
    live_low, live_high, live_close = df['low'].iloc[-1], df['high'].iloc[-1], df['close'].iloc[-1]
    
    # Process LDP 100% Zone Touches
    remaining_ldp = []
    for zone in ldp_zones[symbol][tf]:
        invalidated = False
        if zone['type'] == 'BSL': # Resistance
            if live_high >= zone['bottom'] and live_low <= zone['top']:
                process_alert(f"{symbol}_{tf}_LDP_BSL_Touch_{zone['top']}", str(df['timestamp'].iloc[-1]), "100% Resistance Tested", symbol, tf, f"Price touched the fresh 100% BSL Zone at `[${zone['bottom']:.2f} - ${zone['top']:.2f}]`", live_close)
                invalidated = True # Zone gets swept/health reduced
            if live_close > zone['top']: invalidated = True
                
        elif zone['type'] == 'SSL': # Support
            if live_low <= zone['top'] and live_high >= zone['bottom']:
                process_alert(f"{symbol}_{tf}_LDP_SSL_Touch_{zone['bottom']}", str(df['timestamp'].iloc[-1]), "100% Support Tested", symbol, tf, f"Price touched the fresh 100% SSL Zone at `[${zone['bottom']:.2f} - ${zone['top']:.2f}]`", live_close)
                invalidated = True
            if live_close < zone['bottom']: invalidated = True
                
        if not invalidated: remaining_ldp.append(zone)
    ldp_zones[symbol][tf] = remaining_ldp

    # Standard Swing High/Low POI zones tracking
    idx = -(SWING_LENGTH + 3)
    is_swing_high, is_swing_low = True, True
    
    for check_i in range(1, SWING_LENGTH + 1):
        if df['high'].iloc[idx] <= df['high'].iloc[idx - check_i] or df['high'].iloc[idx] <= df['high'].iloc[idx + check_i]:
            is_swing_high = False; break
    for check_i in range(1, SWING_LENGTH + 1):
        if df['low'].iloc[idx] >= df['low'].iloc[idx - check_i] or df['low'].iloc[idx] >= df['low'].iloc[idx + check_i]:
            is_swing_low = False; break

    if is_swing_high:
        top_edge = df['high'].iloc[idx]
        bottom_edge = top_edge - atr_buffer
        if not any(abs(z['top'] - top_edge) < atr_buffer for z in active_zones[symbol][tf]):
            active_zones[symbol][tf].append({"top": top_edge, "bottom": bottom_edge, "type": "supply"})
            process_alert(f"{symbol}_{tf}_POI_Supply_Formed_{top_edge}", str(df['timestamp'].iloc[-1]), "Supply Zone Formed", symbol, tf, f"New Supply (Resistance) formed at `[${bottom_edge:.2f} - ${top_edge:.2f}]`", top_edge)
            
    if is_swing_low:
        bottom_edge = df['low'].iloc[idx]
        top_edge = bottom_edge + atr_buffer
        if not any(abs(z['bottom'] - bottom_edge) < atr_buffer for z in active_zones[symbol][tf]):
            active_zones[symbol][tf].append({"top": top_edge, "bottom": bottom_edge, "type": "demand"})
            process_alert(f"{symbol}_{tf}_POI_Demand_Formed_{bottom_edge}", str(df['timestamp'].iloc[-1]), "Demand Zone Formed", symbol, tf, f"New Demand (Support) formed at `[${bottom_edge:.2f} - ${top_edge:.2f}]`", bottom_edge)

    remaining_zones = []
    for zone in active_zones[symbol][tf]:
        invalidated = False
        if zone['type'] == "demand":
            if live_low <= zone['top'] and live_high >= zone['bottom']:
                process_alert(f"{symbol}_{tf}_demand_touch_{zone['bottom']}", str(df['timestamp'].iloc[-1]), "Demand Zone Touched (Support)", symbol, tf, f"Price pulled into support zone: `[${zone['bottom']:.2f} - ${zone['top']:.2f}]`", live_close)
            if live_close < zone['bottom']: invalidated = True
                
        elif zone['type'] == "supply":
            if live_high >= zone['bottom'] and live_low <= zone['top']:
                process_alert(f"{symbol}_{tf}_supply_touch_{zone['top']}", str(df['timestamp'].iloc[-1]), "Supply Zone Touched (Resistance)", symbol, tf, f"Price pushed into resistance zone: `[${zone['bottom']:.2f} - ${zone['top']:.2f}]`", live_close)
            if live_close > zone['top']: invalidated = True

        if not invalidated: remaining_zones.append(zone)
            
    active_zones[symbol][tf] = remaining_zones

# ==========================================
# RUNTIME SCANNER LIFECYCLE
# ==========================================
def core_market_scanner_loop():
    print(f"Global Macro Market Scanner Online...")
    send_telegram_message(
        f"🚀 *Macro Watchlist Engine Online* 🚀\n"
        f"• Monitoring dedicated bot feed via yfinance.\n"
        f"• Active watchlist assets: {len(ACTIVE_SYMBOLS)}\n"
        f"• Scanning LDP Zones, OC Candles, OB Formations, and Supertrend Flips."
    )
    
    while True:
        try:
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
