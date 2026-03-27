import ccxt
import pandas as pd
import pandas_ta as ta
import time

def fetch_ohlcv(symbol='BTC/USDT', timeframe='1d', limit=100):
    """
    ดึงข้อมูลราคาจาก Exchange (ตัวอย่างนี้ใช้ Binance)
    """
    exchange = ccxt.binance()
    
    # ดึงข้อมูล OHLCV
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    
    # แปลงเป็น DataFrame เพื่อให้จัดการง่าย
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # แปลง Timestamp เป็นรูปแบบวันที่ที่อ่านออก
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    return df

def scan_opportunity(df, symbol):
    """
    ฟังก์ชันตรวจสอบเงื่อนไขพักตัวและวอลุ่มแห้ง
    """
    if len(df) < 50:
        return None

    # 1. คำนวณ Indicators
    df['ema_200'] = ta.ema(df['close'], length=200)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['vol_avg'] = df['volume'].rolling(window=20).mean()
    
    # ดึงค่าแถวล่าสุด (Current State)
    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]
    
    # 2. ตั้งเงื่อนไข (Conditions)
    
    # เงื่อนไข A: อยู่ในเทรนด์ขาขึ้น (ราคา > EMA 200)
    is_uptrend = last_row['close'] > last_row['ema_200']
    is_downtrend = last_row['close'] < last_row['ema_200']
    # เงื่อนไข B: Volume Dry-up (วอลุ่มวันนี้ < 60% ของค่าเฉลี่ย 20 วัน)
    is_vol_dry = last_row['volume'] < (last_row['vol_avg'] * 0.6)
    
    # เงื่อนไข C: Consolidation (ATR ปัจจุบัน < ATR เมื่อวาน) 
    # หรือจะเช็คว่าราคาแกว่งตัวแคบลงเรื่อยๆ
    is_consolidating = last_row['atr'] < prev_row['atr']

    # 3. สรุปผลการสแกน
    if (is_uptrend or is_downtrend) and is_vol_dry and is_consolidating:
        return {
            'symbol': symbol,
            'status': 'MATCH',
            'close': last_row['close'],
            'trend': 'uptrend' if is_uptrend else 'downtrend',
            'vol_ratio': round(last_row['volume'] / last_row['vol_avg'], 2)
        }
    return None

# ทดลองดึงข้อมูลย้อนหลัง 150 วัน (เพื่อให้ครอบคลุมช่วงวิเคราะห์ 1-3 เดือน)
# --- ส่วนของการรัน Scanner ---
symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'LINK/USDT', 'DOT/USDT'] # รายชื่อเหรียญที่ต้องการสแกน
matches = []

print("--- Start Scanning ---")
for s in symbols:
    try:
        # ใช้ Function จาก Step 1 ดึงข้อมูล 250 วัน (เพื่อให้คำนวณ EMA 200 ได้)
        df_scan = fetch_ohlcv(s, '1d', 900) 
        result = scan_opportunity(df_scan, s)
        
        if result:
            matches.append(result)
            print(f"✅ Found: {s} | Vol Ratio: {result['vol_ratio']}")
        else:
            print(f"❌ {s}: Not Match")
            
    except Exception as e:
        print(f"⚠️ Error scanning {s}: {e}")

print("\n--- Scan Results ---")
print(pd.DataFrame(matches))