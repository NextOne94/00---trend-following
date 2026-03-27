import ccxt
import pandas as pd
import pandas_ta as ta
import vectorbt as vbt
import numpy as np

# 1. ฟังก์ชันดึงข้อมูล (เหมือนเดิม แต่เพิ่มการเซ็ต Index เป็นวันที่)
def fetch_ohlcv(symbol='BTC/USDT', timeframe='1d', limit=1000):
    exchange = ccxt.binance()
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True) # สำคัญ: ตั้งวันที่เป็น Index เพื่อให้กราฟ vectorbt แสดงผลถูกต้อง
    return df

print("Fetching data...")
df = fetch_ohlcv('BTC/USDT', '1d', 1500) # ดึงย้อนหลังประมาณ 4 ปี

# 2. คำนวณ Indicators (รวดเดียวทั้ง DataFrame)
df['ema_200'] = ta.ema(df['close'], length=200)
df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
df['vol_avg'] = df['volume'].rolling(window=20).mean()

# 3. สร้างสัญญาณ Entry (เข้าซื้อ) เป็น Boolean (True/False)
is_uptrend = df['close'] > df['ema_200']
is_vol_dry = df['volume'] < (df['vol_avg'] * 0.6)
is_consolidating = df['atr'] < df['atr'].shift(1) # ATR วันนี้ < ATR เมื่อวาน

# รวมสัญญาณเข้าซื้อ (เมื่อทุกเงื่อนไขเป็น True พร้อมกัน)
entries = is_uptrend & is_vol_dry & is_consolidating

# 4. สร้างกฎ Risk Management (แปลงระยะ SL/TP เป็น % เพื่อส่งให้ vectorbt)
# สูตรหา % SL = (2 * ATR) / ราคาปัจจุบัน
sl_pct = (2 * df['atr']) / df['close']

# สูตรหา % TP = 3 เท่าของ % SL (เพราะเราต้องการ Risk:Reward = 1:3)
tp_pct = sl_pct * 3

# 5. รัน Backtest ด้วย Portfolio.from_signals
print("\nRunning Backtest with vectorbt...")
pf = vbt.Portfolio.from_signals(
    close=df['close'],
    entries=entries,
    sl_stop=sl_pct,      # จุดตัดขาดทุนแบบ % (Dynamic ตาม ATR)
    tp_stop=tp_pct,      # จุดทำกำไรแบบ % (Dynamic ตาม ATR)
    fees=0.001,          # ค่าธรรมเนียมเทรด 0.1% (มาตรฐาน Binance)
    init_cash=1000,      # ทุนเริ่มต้น 1,000 USDT
    size=1.0,            # ซื้อด้วยเงินทั้งหมดที่มีในพอร์ต (All-in) หรือเปลี่ยนเป็น % เช่น 0.1
    size_type='percent', # ระบุว่า size=1.0 คือ 100% ของพอร์ต
    freq='1d'            # Timeframe 1 วัน
)

# 6. แสดงผลสรุปสถิติ (Stats)
print("\n--- Backtest Results ---")
print(pf.stats())

# 7. สร้างกราฟแสดงจุดเข้าซื้อ และการเติบโตของพอร์ต (ถ้าคุณรันบน Jupyter Notebook หรือมีหน้าจอ UI)
pf.plot().show()