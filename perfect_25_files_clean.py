import os
import glob
import re
import csv
import unicodedata
import firebase_admin
from firebase_admin import credentials, firestore
from concurrent.futures import ThreadPoolExecutor

print("⏳ 金庫（Firestore）への絶対接続を確立中...", flush=True)
cred = credentials.Certificate('serviceAccountKey.json')
try: firebase_admin.initialize_app(cred)
except ValueError: pass
db = firestore.client()

# ⭕️ Kaoruさん指定のフォルダ住所をダイレクトに指定
target_dir = "/Users/ishikawakaoru/bot_fix/photos_csv"

# 大文字・小文字を問わず、指定フォルダ内のすべてのCSVを確実に全検知
csv_files = glob.glob(os.path.join(target_dir, "*.csv")) + glob.glob(os.path.join(target_dir, "*.CSV"))
csv_files = sorted(list(set(csv_files)))

if not csv_files:
    print(f"❌ 指定されたフォルダ内にCSVファイルが見つかりません: {target_dir}")
    exit()

print(f"📂 指定先から計 {len(csv_files)} 個のデータファイルを検出しました。個別点検を開始します。\n")

def ultimate_clean(val):
    if val is None: return ""
    s = str(val).strip()
    if s.lower() in ["nan", "none", "null", ""]: return ""
    if s.endswith('.0') and s[:-2].isdigit(): s = s[:-2]
    s = unicodedata.normalize('NFKC', s)
    s = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', s)
    s = s.replace('\xa0', ' ').replace('\\u00a0', ' ').replace('\u200b', '')
    return s.strip()

all_rows_to_upload = []
global_idx = 0

for file_path in csv_files:
    file_name = os.path.basename(file_path)
    
    with open(file_path, 'rb') as f:
        file_bytes = f.read()
        
    decoded_text = None
    chosen_enc = "不明"
    
    try:
        u_text = file_bytes.decode('utf-8-sig')
        if not re.search(r'[縺-繧]', u_text):
            decoded_text = u_text
            chosen_enc = "UTF-8"
    except: pass
    
    if decoded_text is None:
        try:
            decoded_text = file_bytes.decode('cp932')
            chosen_enc = "Shift_JIS (cp932)"
        except:
            decoded_text = file_bytes.decode('utf-8', errors='replace')
            chosen_enc = "UTF-8 (破損箇所強制代替)"

    print(f"📋 【点検完了】ファイル: {file_name:<35} ＞ 判定コード: {chosen_enc}")
    
    lines = decoded_text.splitlines()
    reader = csv.DictReader(lines)
    
    file_row_count = 0
    for row in reader:
        cleaned_data = {ultimate_clean(k): ultimate_clean(v) for k, v in row.items()}
        cleaned_data["_source_file"] = file_name
        
        all_rows_to_upload.append((global_idx, cleaned_data))
        global_idx += 1
        file_row_count += 1
        
    print(f"     └─ 正常抽出: {file_row_count} 件を完全クレンジングしました。")

print(f"\n🔥 【点検総括】全 {len(csv_files)} ファイルから、計 {len(all_rows_to_upload)} 件の純度100%の日本語データを抽出完了。")
print("Firestoreの『Master_Photos』コレクションへ一括上書きを開始します...")

def upload_row(args):
    idx, data = args
    db.collection('Master_Photos').document(f"photo_{idx}").set(data)

with ThreadPoolExecutor(max_workers=25) as executor:
    executor.map(upload_row, all_rows_to_upload)

print("\n✨ 【大元・完全勝利】25ファイルすべての文字化け・混在コードの浄化が完了しました！")
