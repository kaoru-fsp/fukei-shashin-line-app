import os
import json
import re
import unicodedata
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import firebase_admin
from firebase_admin import credentials, firestore

cred = credentials.Certificate('serviceAccountKey.json')
try: firebase_admin.initialize_app(cred)
except ValueError: pass
db = firestore.client()

csv_file = 'Multilayered_Contest_Data_Master.csv'
encodings = ['utf-8-sig', 'cp932', 'utf-8', 'shift_jis']
df = None

for enc in encodings:
    try:
        df = pd.read_csv(csv_file, encoding=enc)
        print(f"⭕️ CSVファイル認識成功: {enc}")
        break
    except Exception: continue

if df is None:
    print("❌ CSVが読み込めません"); exit()

def ultimate_clean(val):
    if val is None: return ""
    if isinstance(val, (int, float)):
        if pd.isna(val): return ""
        if val == int(val): return str(int(val))
        return str(val)
    s = str(val).strip()
    if s.lower() in ["nan", "none", "null", ""]: return ""
    s = unicodedata.normalize('NFKC', s)
    s = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', s)
    s = s.replace('\xa0', ' ').replace('\\u00a0', ' ').replace('\u200b', '')
    return s.strip()

df.columns = [ultimate_clean(col) for col in df.columns]
df = df.fillna("")

def upload_row(args):
    index, row = args
    cleaned_data = {str(k): ultimate_clean(v) for k, v in row.to_dict().items()}
    db.collection('Master_Photos').document(f"photo_{index}").set(cleaned_data)
    if index % 3000 == 0:
        print(f"🚀 データ完全浄化転送中: {index} / {len(df)} 件...", flush=True)

print(f"🔥 {len(df)} 件の文字化け根絶アップロードを開始します...")
with ThreadPoolExecutor(max_workers=20) as executor:
    executor.map(upload_row, list(df.iterrows()))
print("✨ 【本体クレンジング完全完了】金庫は100%ピカピカになりました！")
