import pandas as pd
import re
import firebase_admin
from firebase_admin import credentials, firestore
from concurrent.futures import ThreadPoolExecutor

print("⏳ 金庫（Firestore）へアクセス中...", flush=True)
cred = credentials.Certificate('serviceAccountKey.json')
try: firebase_admin.initialize_app(cred)
except ValueError: pass
db = firestore.client()

csv_path = 'Multilayered_Contest_Data_Master.csv'

# 古いpandasでも絶対にエラーにならない方法で、2パターンの世界を同時にロード
with open(csv_path, 'r', encoding='utf-8-sig', errors='replace') as f:
    df_utf = pd.read_csv(f)

with open(csv_path, 'r', encoding='cp932', errors='replace') as f:
    df_cp = pd.read_csv(f)

# 列名を完全に強制同期
df_cp.columns = df_utf.columns

# 不純物のクレンジング関数
def clean_val(v):
    if v is None: return ""
    s = str(v).strip()
    if s.lower() in ["nan", "none", "null", ""]: return ""
    if s.endswith('.0') and s[:-2].isdigit(): s = s[:-2]
    return s

rows_to_upload = []
print("🔍 14冊の混在から『NT_』などの文字化け行を自動選別しています...", flush=True)

for idx in range(len(df_utf)):
    row_utf = df_utf.iloc[idx].to_dict()
    row_cp = df_cp.iloc[idx].to_dict()
    
    # 判定用の解説文と撮影地
    check_str = str(row_utf.get('Judge_Comment_Summary', '')) + str(row_utf.get('Location', ''))
    
    # 【自動選別】「縺」などの化け文字、または置換ゴミ（）があれば、Shift_JIS（NT_のファイル）側を強制採用！
    if re.search(r'[縺-繧\uFFFD]', check_str) or "NT_" in str(row_utf.get('PicFileName', '')):
        chosen_row = row_cp
    else:
        chosen_row = row_utf
        
    # データの最終洗浄
    cleaned_data = {str(k).strip(): clean_val(v) for k, v in chosen_row.items()}
    rows_to_upload.append((idx, cleaned_data))

def upload_row(args):
    idx, data = args
    db.collection('Master_Photos').document(f"photo_{idx}").set(data)
    if idx % 3000 == 0:
        print(f"🚀 [混在自動仕分け転送] ピカピカの日本語を格納中: {idx} / {len(df_utf)} 件...", flush=True)

print(f"🔥 仕分け完了！ {len(rows_to_upload)} 件をFirestoreへ一気に上書きします...")
with ThreadPoolExecutor(max_workers=25) as executor:
    executor.map(upload_row, rows_to_upload)

print("\n✨ 【完全勝利】14冊すべての文字化け・混在コードの駆除が完了しました！")
