# -*- coding: utf-8 -*-
"""
Created on Sun Mar 29 22:55:57 2026

@author: Chalermwong
"""

import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
import os
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import plotly.io as pio

pio.renderers.default = 'browser'

symbol = 'BTC/USDT'


baseTF = '4h'
entryTF = '1h'

years_to_fetch = 3

exchange = ccxt.binance({'enableRateLimit': True})


now = exchange.milliseconds()
years_ms = int(years_to_fetch * 365.25 * 24 * 60 * 60 * 1000)
since = now - years_ms

# --- 2. ตั้งค่าพารามิเตอร์ (เหมือนใน Pine Script) ---
lookback = 4
atr_len = 14
atr_mult = 1.5
vol_len = 20
tolerance_bars = 2

delayfororder = 4


def loadData (timeframe, since, now):
    all_bars = []
    
    while since < now:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
            if not bars:
                break
            
            all_bars.extend(bars)
            since = bars[-1][0] + 1
            
            last_date = pd.to_datetime(bars[-1][0], unit='ms').strftime('%Y-%m-%d %H:%M:%S')
            print(f"ดึงข้อมูลสะสมแล้ว {len(all_bars):,} แท่ง... (ข้อมูลล่าสุดถึง: {last_date})")
            
            time.sleep(0.5) # พักเบรกให้ API ปลอดภัยจากการถูกแบน
            
        except Exception as e:
            print(f"เกิดข้อผิดพลาด: {e} -> จะลองดึงใหม่ในอีก 5 วินาที...")
            time.sleep(5)
            continue
            
    # แปลงข้อมูลเป็น DataFrame
    df = pd.DataFrame(all_bars, columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
    df['Timestamp_txt'] = pd.to_datetime(df['Timestamp'], unit='ms')
    df.set_index('Timestamp_txt', inplace=True)
    df = df[~df.index.duplicated(keep='first')]
    return df
 
df_baseRaw = loadData(baseTF, since, now)
df_entryRaw = loadData(entryTF, since, now)


df_base = df_baseRaw.copy()    
df_entry = df_entryRaw.copy()    



# --- 3. คำนวณค่าต่างๆ แบบรวดเดียว (Vectorized) ---
# คำนวณ ATR
df_base['ATR'] = ta.atr(df_base['High'], df_base['Low'], df_base['Close'], length=atr_len)

# หา Highest High และ Lowest Low ย้อนหลัง 4 แท่ง
df_base['HH'] = df_base['High'].rolling(window=lookback).max()
df_base['LL'] = df_base['Low'].rolling(window=lookback).min()
df_base['BoxRange'] = df_base['HH'] - df_base['LL']

# คำนวณ Volume เงื่อนไข
df_base['AvgVol_4'] = df_base['Volume'].rolling(window=lookback).mean()
df_base['SMA_Vol_20'] = df_base['Volume'].rolling(window=vol_len).mean()
df_base['VolCondition'] = df_base['AvgVol_4'] < df_base['SMA_Vol_20']

# เงื่อนไขเริ่มต้นของการเกิดกรอบสะสม
df_base['IsConsolidating'] = (df_base['BoxRange'] <= (df_base['ATR'] * atr_mult)) & df_base['VolCondition']

#คำนวณ SMA 200 จาก DataFrame ตัวเต็ม (df_base) ก่อน ---
# (ต้องคำนวณจาก df_base ตัวเต็ม เพื่อให้มีข้อมูลย้อนหลังพอสำหรับ 200 แท่ง)S
df_base['SMA_200'] = df_base['Close'].rolling(window=200).mean()
 
 
 
 # --- 4. ตัวแปรเก็บสถานะการวาดกล่อง ---
in_zone = False
upper_limit = np.nan
lower_limit = np.nan
bars_outside = 0

df_base['InBox'] = False
df_base['BoxTop'] = np.nan
df_base['BoxBottom'] = np.nan


# --- 5. ชุดโค้ดตรวจสอบแบบแท่งต่อแท่งเต็มรูปแบบ (Iterative State Machine with Back-population) ---
# เซ็ตค่าเริ่มต้นใหม่
in_zone = False
upper_limit = np.nan
lower_limit = np.nan
bars_outside = 0

df_base['InBox'] = False
df_base['BoxTop'] = np.nan
df_base['BoxBottom'] = np.nan

# --- ลอจิกการตรวจสอบแบบแท่งต่อแท่ง (เดินหน้าอย่างเดียว ไม่ย้อนหลัง) ---
for i in range(len(df_base)):
    if pd.isna(df_base['ATR'].iloc[i]):
        continue
        
    current_close = df_base['Close'].iloc[i] 
    
    if in_zone:
        if current_close > upper_limit or current_close < lower_limit: #check out zone
            bars_outside += 1
        else:
            bars_outside = 0
            
        if bars_outside > tolerance_bars:
            in_zone = False # จบกล่อง
            bars_outside = 0
        else:
            # ยืดกล่องน้ำเงินต่อไป
            df_base.iat[i, df_base.columns.get_loc('InBox')] = True
            df_base.iat[i, df_base.columns.get_loc('BoxTop')] = upper_limit
            df_base.iat[i, df_base.columns.get_loc('BoxBottom')] = lower_limit
            
    if not in_zone:
        # เจอแท่งที่ 4 ที่เข้าเงื่อนไข (เริ่มเข้าโซน)
        if df_base['IsConsolidating'].iloc[i]:
            in_zone = True
            upper_limit = df_base['HH'].iloc[i]
            lower_limit = df_base['LL'].iloc[i]
            bars_outside = 0
            
            # บันทึกกล่องน้ำเงินแท่งแรก
            df_base.iat[i, df_base.columns.get_loc('InBox')] = True
            df_base.iat[i, df_base.columns.get_loc('BoxTop')] = upper_limit
            df_base.iat[i, df_base.columns.get_loc('BoxBottom')] = lower_limit


# %% Plot zone
# plot_df_base = df_base.tail(7000).copy() # ดึงมา 500 แท่งล่าสุด

# fig = go.Figure(data=[go.Candlestick(
#     x=plot_df_base.index, 
#     open=plot_df_base['Open'], 
#     high=plot_df_base['High'], 
#     low=plot_df_base['Low'], 
#     close=plot_df_base['Close'], 
#     name='Price'
# )])

# # --- 3. เพิ่มเส้น SMA 200 (พล็อตเป็นเส้น Scatter) ---
# fig.add_trace(go.Scatter(
#     x=plot_df_base.index,
#     y=plot_df_base['SMA_200'],
#     mode='lines',
#     line=dict(color='orange', width=2),
#     name='SMA 200'
# ))

# plot_df_base['BoxGroup'] = (plot_df_base['InBox'] != plot_df_base['InBox'].shift()).cumsum()
# boxes = plot_df_base[plot_df_base['InBox'] == True].groupby('BoxGroup')

# for name, group in boxes:
#     if len(group) >= 1:
#         # 1. ข้อมูลของกล่องสีน้ำเงิน (เริ่มจากแท่งที่ 4 เป็นต้นไป)
#         start_time_blue = group.index[0]
#         end_time_blue = group.index[-1]
#         top = group['BoxTop'].iloc[0]
#         bottom = group['BoxBottom'].iloc[0]
        
#         # 2. คำนวณหาจุดเริ่มต้นของกล่องสีแดง (ย้อนกลับไป lookback-1 แท่ง)
#         # หาตำแหน่ง index (บรรทัดที่เท่าไหร่) ของแท่งที่เริ่มกล่องน้ำเงิน
#         idx_blue_start = plot_df_base.index.get_loc(start_time_blue)
#         # ถอยหลังไป 3 แท่ง (หรือตามค่า lookback)
#         idx_red_start = max(0, idx_blue_start - lookback + 1)
#         start_time_red = plot_df_base.index[idx_red_start]

#         # --- วาดกล่องสีแดง (ช่วงสะสม 4 แท่งแรก) ---
#         fig.add_shape(
#             type="rect",
#             x0=start_time_red, y0=bottom, 
#             x1=start_time_blue, y1=top,
#             line=dict(color="rgba(255, 50, 50, 1)", width=2),   # ขอบสีแดง
#             fillcolor="rgba(255, 50, 50, 0.2)",                 # พื้นหลังสีแดงโปร่งแสง
#             layer="below"
#         )

#         # --- วาดกล่องสีน้ำเงิน (ช่วงที่ราคายังอยู่ในกรอบ รอ Breakout) ---
#         fig.add_shape(
#             type="rect",
#             x0=start_time_blue, y0=bottom, 
#             x1=end_time_blue, y1=top,
#             line=dict(color="rgba(41, 98, 255, 1)", width=2),   # ขอบสีน้ำเงิน
#             fillcolor="rgba(41, 98, 255, 0.2)",                 # พื้นหลังสีน้ำเงินโปร่งแสง
#             layer="below"
#         )

# fig.update_layout(
#     title='Crypto Consolidation (Red = Setup, Blue = Waiting for Breakout)',
#     yaxis_title='Price (USDT)', 
#     xaxis_title='Time',
#     xaxis_rangeslider_visible=False, 
#     template='plotly_dark', 
#     height=600
# )

# fig.show()



#%% Entry
# ใช้ตัวแปร boxes จากขั้นตอนก่อนหน้าที่เรา Group ไว้แล้ว
# for name, group in boxes:
#     if len(group) < 1: 
#         continue

df_entry['BoxTop'] = np.nan
df_entry['BoxBottom'] = np.nan

for i in range(df_base.shape[0]-1):
    if np.isnan(df_base.iloc[i]['BoxTop']) == False:
        df_entry.loc[ (df_entry['Timestamp'] >= df_base.iloc[i]['Timestamp']) & 
                      (df_entry['Timestamp'] <  df_base.iloc[i+1]['Timestamp']), 'BoxTop'] = df_base.iloc[i]['BoxTop']
        
        df_entry.loc[ (df_entry['Timestamp'] >= df_base.iloc[i]['Timestamp']) & 
                      (df_entry['Timestamp'] <  df_base.iloc[i+1]['Timestamp']), 'BoxBottom'] = df_base.iloc[i]['BoxBottom']


# คำนวณค่าพื้นฐาน
df_entry['Body'] = df_entry['Close'] - df_entry['Open']
df_entry['Is_Green'] = df_entry['Body'] > 0
df_entry['Is_Red'] = df_entry['Body'] < 0
df_entry['Body_Size'] = abs(df_entry['Body'])
df_entry = df_entry.reset_index()
 
# 1. ตรวจจับ Engulfing Pattern
def detect_engulfing(df):
    df['Bull_Engulfing'] = 0
    df['Bear_Engulfing'] = 0
    
    for i in range(1, len(df)):
        prev_open = df.loc[i-1, 'Open']
        prev_close = df.loc[i-1, 'Close']
        curr_open = df.loc[i, 'Open']
        curr_close = df.loc[i, 'Close']
        
        # Bull Engulfing: แท่งก่อนแดง, แท่งปัจจุบันเขียว และกลืนแท่งก่อนหมด
        if (prev_close < prev_open and  # แท่งก่อนแดง
            curr_close > curr_open and  # แท่งปัจจุบันเขียว
            curr_open <= prev_close and  # เปิดต่ำกว่าหรือเท่ากับปิดแท่งก่อน
            curr_close >= prev_open):    # ปิดสูงกว่าหรือเท่ากับเปิดแท่งก่อน
            df.loc[i, 'Bull_Engulfing'] = 1
        
        # Bear Engulfing: แท่งก่อนเขียว, แท่งปัจจุบันแดง และกลืนแท่งก่อนหมด
        if (prev_close > prev_open and  # แท่งก่อนเขียว
            curr_close < curr_open and  # แท่งปัจจุบันแดง
            curr_open >= prev_close and  # เปิดสูงกว่าหรือเท่ากับปิดแท่งก่อน
            curr_close <= prev_open):    # ปิดต่ำกว่าหรือเท่ากับเปิดแท่งก่อน
            df.loc[i, 'Bear_Engulfing'] = 1
    
    return df
 
# 2. ตรวจจับ CRT (Change of Trend) Pattern
def detect_crt(df):
    df['Bull_CRT'] = 0
    df['Bear_CRT'] = 0
    
    for i in range(2, len(df)):
        # Bull CRT: แดง -> แดง -> เขียว (กลับตัวขึ้น)
        if (df.loc[i-2, 'Is_Red'] and 
            df.loc[i-1, 'Is_Red'] and 
            df.loc[i, 'Is_Green']):
            df.loc[i, 'Bull_CRT'] = 1
        
        # Bear CRT: เขียว -> เขียว -> แดง (กลับตัวลง)
        if (df.loc[i-2, 'Is_Green'] and 
            df.loc[i-1, 'Is_Green'] and 
            df.loc[i, 'Is_Red']):
            df.loc[i, 'Bear_CRT'] = 1
    
    return df
 
# 3. นับจำนวนแท่งเทียนต่อเนื่อง
def count_consecutive_candles(df):
    df['Candle_Count'] = 0
    count = 0
    
    for i in range(len(df)):
        if df.loc[i, 'Is_Green']:
            if i == 0 or df.loc[i-1, 'Is_Red']:
                # แท่งเขียวแท่งแรก หรือ เปลี่ยนจากแดงมาเขียว
                count = 1
            else:
                # เขียวต่อเนื่อง
                count += 1
            df.loc[i, 'Candle_Count'] = count
        elif df.loc[i, 'Is_Red']:
            # แท่งแดง ให้เป็น -1

            if i == 0 or df.loc[i-1, 'Is_Green']:
                count = -1
            else:
                # แดงต่อเนื่อง
                count += -1
            df.loc[i, 'Candle_Count'] = count
            
            
            
        else:
            # แท่ง Doji (เปิด = ปิด)
            df.loc[i, 'Candle_Count'] = 0
            count = 0
    
    return df

def create_box_group(df):
    """
    สร้าง column BoxGroup ที่บอกว่าแต่ละแถวอยู่ในกลุ่ม Box ไหน
    กลุ่มจะเปลี่ยนเมื่อมีค่า NaN ใน BoxTop หรือ BoxBottom
    """
    df['BoxGroup'] = 0
    group_number = 0
    in_box = False
    
    for i in range(len(df)):
        # ตรวจสอบว่ามีค่า BoxTop และ BoxBottom หรือไม่
        has_box = pd.notna(df.loc[i, 'BoxTop']) and pd.notna(df.loc[i, 'BoxBottom'])
        
        if has_box:
            if not in_box:
                # เริ่มกลุ่มใหม่
                group_number += 1
                in_box = True
            df.loc[i, 'BoxGroup'] = group_number
        else:
            # ไม่มี Box ให้เป็น 0 หรือ NaN
            df.loc[i, 'BoxGroup'] = 0
            in_box = False
    
    return df
 
# เรียกใช้ฟังก์ชัน


 
# ใช้ฟังก์ชันทั้งหมด
df_entry = detect_engulfing(df_entry)
df_entry = detect_crt(df_entry)
df_entry = count_consecutive_candles(df_entry)
df_entry = create_box_group(df_entry)

df_entry.loc[ (df_entry['Open'] < df_entry['BoxTop']) & 
              (df_entry['Close'] >= df_entry['BoxTop'] ), 'BreakOut'] = 1


df_entry.loc[ (df_entry['Open'] > df_entry['BoxBottom']) & 
              (df_entry['Close'] <= df_entry['BoxBottom'] ), 'BreakOut'] = -1


df_entry['status'] = 0
df_entry['order'] = 0

df_entry['Bull_Engulfing_lookBack'] = df_entry['Bull_Engulfing'].rolling(window=delayfororder).sum()
df_entry['Bear_Engulfing_lookBack'] = df_entry['Bear_Engulfing'].rolling(window=delayfororder).sum() 
df_entry['Bull_CRT_lookBack'] = df_entry['Bull_CRT'].rolling(window=delayfororder).sum() 
df_entry['Bear_CRT_lookBack'] = df_entry['Bear_CRT'].rolling(window=delayfororder).sum()

df_entry.loc[(df_entry['BreakOut']==1) & 
             ((df_entry['Bull_Engulfing_lookBack']>0) | (df_entry['Bull_CRT_lookBack']>0)), 'order'] = 1
df_entry.loc[(df_entry['BreakOut']==-1) & 
             ((df_entry['Bear_Engulfing_lookBack']>0) | (df_entry['Bear_CRT_lookBack']>0)), 'order'] = -1


# เพิ่ม columns สำหรับ backtest
df_entry['position'] = 0  # 0=no position, 1=long, -1=short
df_entry['entry_price'] = np.nan
df_entry['exit_price'] = np.nan
df_entry['pnl'] = 0.0
df_entry['close_reason'] = ''
df_entry['tp_price'] = np.nan
df_entry['sl_price'] = np.nan
df_entry['expect'] = np.nan
df_entry['break_even_triggered'] = False
 
def run_backtest(df, mulExp=2, candleClose = 4):
    """
    ระบบ Backtest สำหรับ Trading
    
    กฎการเทรด:
    1. order = 1 -> Long, order = -1 -> Short
    2. ถือได้ทีละออเดอร์
    3. TP = 2 * expect (expect = BoxTop - BoxBottom)
    4. SL = ขอบของ Box (ประมาณ 1 expect)
    5. ถ้าราคาวิ่งได้ 1 expect -> ขยับ SL มากันหน้าทุน
    6. ถ้า Candle_Count = 3 ทิศทางตรงข้าม -> Force close
    """
    
    position = 0  # สถานะปัจจุบัน: 0=ไม่มี, 1=long, -1=short
    entry_price = 0
    entry_index = 0
    tp_price = 0
    sl_price = 0
    expect = 0
    break_even_triggered = False
    
    for i in range(len(df)):
        current_order = df.loc[i, 'order']
        current_close = df.loc[i, 'Close']
        current_high = df.loc[i, 'High']
        current_low = df.loc[i, 'Low']
        current_candle_count = df.loc[i, 'Candle_Count']
        box_top = df.loc[i, 'BoxTop']
        box_bottom = df.loc[i, 'BoxBottom']
        
        # ==============================
        # 1. ตรวจสอบการปิดออเดอร์ที่มีอยู่
        # ==============================
        if position != 0:
            close_order = False
            close_reason = ''
            exit_price = current_close
            
            # ตรวจสอบ TP/SL
            if position == 1:  # Long position
                # ตรวจสอบ SL (ราคา Low ถูก SL)
                if current_low <= sl_price:
                    close_order = True
                    close_reason = 'SL'
                    exit_price = sl_price
                # ตรวจสอบ Force Close (Candle_Count = -3)
                elif current_candle_count <= -candleClose:
                    close_order = True
                    close_reason = 'Force_Close_Candle'
                    exit_price = current_close
                # ตรวจสอบ Trailing Stop (ราคาวิ่งได้ 1 expect)
                elif not break_even_triggered and current_high >= entry_price + expect:
                    # ขยับ SL มากันหน้าทุน
                    sl_price = entry_price
                    break_even_triggered = True
                    df.loc[entry_index:i, 'break_even_triggered'] = True
                    df.loc[entry_index:i, 'sl_price'] = sl_price+0.5
                # ตรวจสอบ TP (ราคา High ถึง TP)
                elif current_high >= tp_price:
                    close_order = True
                    close_reason = 'TP'
                    exit_price = tp_price
                    
            elif position == -1:  # Short position
                # ตรวจสอบ SL (ราคา High ถูก SL)
                if current_high >= sl_price:
                    close_order = True
                    close_reason = 'SL'
                    exit_price = sl_price
                # ตรวจสอบ Force Close (Candle_Count = 3)
                elif current_candle_count >= candleClose:
                    close_order = True
                    close_reason = 'Force_Close_Candle'
                    exit_price = current_close
                # ตรวจสอบ Trailing Stop (ราคาวิ่งได้ 1 expect)
                elif not break_even_triggered and current_low <= entry_price - expect:
                    # ขยับ SL มากันหน้าทุน
                    sl_price = entry_price
                    break_even_triggered = True
                    df.loc[entry_index:i, 'break_even_triggered'] = True
                    df.loc[entry_index:i, 'sl_price'] = sl_price-0.5
                # ตรวจสอบ TP (ราคา Low ถึง TP)
                elif current_low <= tp_price:
                    close_order = True
                    close_reason = 'TP'
                    exit_price = tp_price
            
            # ปิดออเดอร์
            if close_order:
                # คำนวณ PnL
                if position == 1:  # Long
                    pnl = exit_price - entry_price
                else:  # Short
                    pnl = entry_price - exit_price
                
                # บันทึกผลลัพธ์
                df.loc[i, 'position'] = 0
                df.loc[i, 'exit_price'] = exit_price
                df.loc[i, 'pnl'] = pnl
                df.loc[i, 'close_reason'] = close_reason
                
                # รีเซ็ตตัวแปร
                position = 0
                entry_price = 0
                entry_index = 0
                tp_price = 0
                sl_price = 0
                expect = 0
                break_even_triggered = False
                continue
        
        # ==============================
        # 2. เปิดออเดอร์ใหม่
        # ==============================
        if position == 0 and current_order != 0:
            # ต้องมี Box เพื่อคำนวณ expect
            if pd.notna(box_top) and pd.notna(box_bottom):
                expect = box_top - box_bottom
                
                # เปิด Long
                if current_order == 1:
                    position = 1
                    entry_price = current_close
                    entry_index = i
                    tp_price = entry_price + (mulExp * expect)
                    sl_price = box_bottom  # SL ที่ขอบล่างของ Box
                    
                # เปิด Short
                elif current_order == -1:
                    position = -1
                    entry_price = current_close
                    entry_index = i
                    tp_price = entry_price - (mulExp * expect)
                    sl_price = box_top  # SL ที่ขอบบนของ Box
                
                # บันทึกข้อมูลการเปิดออเดอร์
                df.loc[i, 'position'] = position
                df.loc[i, 'entry_price'] = entry_price
                df.loc[i, 'tp_price'] = tp_price
                df.loc[i, 'sl_price'] = sl_price
                df.loc[i, 'expect'] = expect
                df.loc[i, 'break_even_triggered'] = False
        
        # ==============================
        # 3. อัพเดทสถานะออเดอร์ที่ถืออยู่
        # ==============================
        elif position != 0:
            df.loc[i, 'position'] = position
            df.loc[i, 'entry_price'] = entry_price
            df.loc[i, 'tp_price'] = tp_price
            df.loc[i, 'sl_price'] = sl_price
            df.loc[i, 'expect'] = expect
            df.loc[i, 'break_even_triggered'] = break_even_triggered
    
    return df

#%%
# df_entryBT = df_entry.copy()
# df_entryBT = run_backtest(df_entryBT, mulExp=2, candleClose = 3)

# # #กรองเฉพาะออเดอร์ที่ปิดแล้ว
# closed_orders = df_entryBT[df_entryBT['exit_price'].notna()].copy()
 
# if len(closed_orders) > 0:
#     total_trades = len(closed_orders)
#     winning_trades = len(closed_orders[closed_orders['pnl'] > 0])
#     losing_trades = len(closed_orders[closed_orders['pnl'] < 0])
#     break_even_trades = len(closed_orders[closed_orders['pnl'] == 0])
    
#     total_pnl = closed_orders['pnl'].sum()
#     avg_pnl = closed_orders['pnl'].mean()
#     max_win = closed_orders['pnl'].max()
#     max_loss = closed_orders['pnl'].min()
    
#     win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
#     print(f"\n📈 สถิติการเทรด:")
#     print(f"  • จำนวนเทรดทั้งหมด: {total_trades} ครั้ง")
#     print(f"  • ชนะ: {winning_trades} ครั้ง ({win_rate:.2f}%)")
#     print(f"  • แพ้: {losing_trades} ครั้ง")
#     print(f"  • เท่าทุน: {break_even_trades} ครั้ง")
#     print(f"\n💰 ผลกำไร/ขาดทุน:")
#     print(f"  • กำไร/ขาดทุนรวม: {total_pnl:,.2f}")
#     print(f"  • กำไร/ขาดทุนเฉลี่ย: {avg_pnl:,.2f}")
#     print(f"  • กำไรสูงสุด: {max_win:,.2f}")
#     print(f"  • ขาดทุนสูงสุด: {max_loss:,.2f}")
    
#     # # สถิติการปิดออเดอร์
#     # print(f"\n🎯 สาเหตุการปิดออเดอร์:")
#     # close_reason_counts = closed_orders['close_reason'].value_counts()
#     # for reason, count in close_reason_counts.items():
#     #     print(f"  • {reason}: {count} ครั้ง ({count/total_trades*100:.1f}%)")
    
#     # # แสดงตัวอย่างเทรด
#     # print(f"\n" + "=" * 120)
#     # print("📋 ตัวอย่างเทรดที่ปิด (10 เทรดแรก)")
#     # print("=" * 120)
#     # display_cols = ['Timestamp_txt', 'position', 'entry_price', 'exit_price', 
#     #                 'tp_price', 'sl_price', 'pnl', 'close_reason', 'expect']
#     # print(closed_orders[display_cols].head(10).to_string(index=False))
    
#     # # แสดงเทรดที่กำไรสูงสุด 5 อันดับ
#     # print(f"\n" + "=" * 120)
#     # print("🏆 Top 5 เทรดที่กำไรสูงสุด")
#     # print("=" * 120)
#     # top_winners = closed_orders.nlargest(5, 'pnl')
#     # print(top_winners[display_cols].to_string(index=False))
    
#     # # แสดงเทรดที่ขาดทุนสูงสุด 5 อันดับ
#     # print(f"\n" + "=" * 120)
#     # print("💔 Top 5 เทรดที่ขาดทุนสูงสุด")
#     # print("=" * 120)
#     # top_losers = closed_orders.nsmallest(5, 'pnl')
#     # print(top_losers[display_cols].to_string(index=False))
    
# else:
#     print("\n⚠️  ไม่พบการเทรดที่ปิดในช่วงเวลาที่วิเคราะห์")
 


summary_data = []

for mulExp in [2, 2.5, 3, 3.5, 4]:
    for candleClose in [3, 4, 5]:
        
        # รัน Backtest ตามพารามิเตอร์ปัจจุบัน
        df_entryBT = df_entry.copy()
        df_entryBT = run_backtest(df_entryBT, mulExp=mulExp, candleClose = 3)
        # closed_orders = run_backtest(df_raw, mulExp=mulExp, candleClose=candleClose)
        closed_orders = df_entryBT[df_entryBT['exit_price'].notna()].copy()
        
        # สรุปผล
        if len(closed_orders) > 0:
            total_trades = len(closed_orders)
            winning_trades = len(closed_orders[closed_orders['pnl'] > 0])
            losing_trades = len(closed_orders[closed_orders['pnl'] < 0])
            break_even_trades = len(closed_orders[closed_orders['pnl'] == 0])
            
            total_pnl = closed_orders['pnl'].sum()
            avg_pnl = closed_orders['pnl'].mean()
            max_win = closed_orders['pnl'].max()
            max_loss = closed_orders['pnl'].min()
            
            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
            
            # เก็บค่าลง List รอแปลงเป็นตาราง
            summary_data.append({
                'mulExp': mulExp,
                'candleClose': candleClose,
                'Total Trades': total_trades,
                'Win Rate (%)': round(win_rate, 2),
                'Win Trades': winning_trades,
                'Loss Trades': losing_trades,
                'Breakeven': break_even_trades,
                'Total PnL': round(total_pnl, 2),
                'Avg PnL': round(avg_pnl, 2),
                'Max Win': round(max_win, 2),
                'Max Loss': round(max_loss, 2)
            })

# แสดงผลและ Save ไฟล์
summary_df = pd.DataFrame(summary_data)




#%%

summary_data = []

for mulExp in [2, 2.5, 3, 3.5, 4]: #
    for candleClose in [3,4,5]:
        
        
        print ('mulExp',mulExp,'candleClose',candleClose)
        
        df_entryBT = df_entry.copy()
        df_entryBT = run_backtest(df_entryBT, mulExp, candleClose)
        
        
        df_entryBT.loc[ (df_entryBT['close_reason'] == 'Force_Close_Candle') & 
                        (df_entryBT['pnl'] > 0), 'close_reason' ] = 'TP_Force_Close_Candle'
        df_entryBT.loc[ (df_entryBT['close_reason'] == 'Force_Close_Candle') & 
                        (df_entryBT['pnl'] < 0), 'close_reason' ] = 'SL_Force_Close_Candle'
        
        df_entryBT.loc[ (df_entryBT['close_reason'] == 'SL') & 
                        (df_entryBT['pnl'] > 0), 'close_reason' ] = 'Protect_Balance'
        
        

        closed_orders = df_entryBT[df_entryBT['exit_price'].notna()].copy()
        reason_counts = closed_orders['close_reason'].value_counts()
         
        if len(closed_orders) > 0:
            total_trades = len(closed_orders)
            winning_trades = len(closed_orders[closed_orders['pnl'] > 0])
            losing_trades = len(closed_orders[closed_orders['pnl'] < 0])
            break_even_trades = len(closed_orders[closed_orders['pnl'] == 0])
            
            total_pnl = closed_orders['pnl'].sum()
            avg_pnl = closed_orders['pnl'].mean()
            max_win = closed_orders['pnl'].max()
            max_loss = closed_orders['pnl'].min()
            
            win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
            
            
            summary_data.append({
                'mulExp': mulExp,
                'candleClose': candleClose,
                'Total Trades': total_trades,
                'Win Rate (%)': round(win_rate, 2),
                'Win Trades': winning_trades,
                'Loss Trades': losing_trades,
                'Breakeven': break_even_trades,
                'Total PnL': round(total_pnl, 2),
                'Avg PnL': round(avg_pnl, 2),
                'Max Win': round(max_win, 2),
                'Max Loss': round(max_loss, 2),
                'TP': reason_counts.get('TP', 0),
                'SL': reason_counts.get('SL', 0),
                'Protect_Bal': reason_counts.get('Protect_Balance', 0),
                'TP_Force': reason_counts.get('TP_Force_Close_Candle', 0),
                'SL_Force': reason_counts.get('SL_Force_Close_Candle', 0)
            })
            
summary_df = pd.DataFrame(summary_data)























































































































#%%










