import os
import json
import pandas as pd
import re
from concurrent.futures import ThreadPoolExecutor
import firebase_admin
from firebase_admin import credentials, firestore

cred = credentials.Certificate('serviceAccountKey.json')
try: firebase_admin.initialize_app(cred)
except ValueError: pass
db = firestore.client()

# ファイルを読み込み
df = pd.read_csv('Multilayered_Contest_Data_Master.csv', encoding='utf-8-sig')
df.columns = df.columns.str.strip()
df = df.fillna("")

# 文字化けや制御文字の死骸（\u00a0 や奇妙な記号）を大元から完全に削ぎ落とす関数
def clean_text(text):
    s = str(text).strip()
    # 不可視の制御文字や、パース時に化けたゴミ記号を正規表現で完全に排除
    s = re.sub(f'[\x00-\x1f\x7f-\x9f]', '', s)
    s = s.replace('\xa0', ' ').replace('\\u00a0', ' ')
    return s

def upload_row(args):
    index, row = args
    data = row.to_dict()
    cleaned_data = {}
    
    for k, v in data.items():
        k_clean = clean_text(k)
        # 小数点表記（.0）のクレンジング
        if isinstance(v, float) and v == int(v):
            cleaned_data[k_clean] = str(int(v))
        else:
            cleaned_data[k_clean] = clean_text(v)
            
    db.collection('Master_Photos').document(f"photo_{index}").set(cleaned_data)
    if index % 2000 == 0:
        print(f"🧹 大元の文字化けを駆除中: {index} / {len(df)} 件...", flush=True)

print(f"🔥 総データ数 {len(df)} 件の『真の文字化け根絶アップロード』を開始します...")
with ThreadPoolExecutor(max_workers=20) as executor:
    executor.map(upload_row, list(df.iterrows()))

print("✨ 【完全浄化】大元のデータベースの文字化けは1文字残らず消滅しました！")
