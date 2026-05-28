import os
import json
import pandas as pd
from google.cloud import firestore
from google.oauth2 import service_account

print("🔥 【大元データ 15,000件 完全クレンジング作戦開始】")

# 1. 認証キーの自動検出
KEY_FILES = ['serviceAccountKey.json', 'firebase_key.json']
cred_file = None
for k in KEY_FILES:
    if os.path.exists(k):
        cred_file = k
        break

if not cred_file:
    print("🚨 [エラー] Firebaseの認証キー(jsonファイル)がディレクトリに見つかりません。")
    exit(1)

with open(cred_file, 'r', encoding='utf-8') as f:
    creds_dict = json.load(f)

cred = service_account.Credentials.from_service_account_info(creds_dict)
db = firestore.Client(project=creds_dict.get('project_id'), database='(default)', credentials=cred)

# 2. CSVの文字化け・勝手な型変換を完全防御して読み込み
CSV_FILE = 'Multilayered_Contest_Data_Master.csv'
if not os.path.exists(CSV_FILE):
    print(f"🚨 [エラー] 大元CSVファイル '{CSV_FILE}' が見つかりません。")
    exit(1)

df = None
# Kaoruさんが見つけてくれた文字化けを突破するため、主要なエンコードを総当たり
for enc in ['utf-8-sig', 'cp932', 'utf-8', 'shift_jis']:
    try:
        # dtype=str でPandasによる勝手な「.0」の付与を根本から絶対禁止する
        df = pd.read_csv(CSV_FILE, encoding=enc, dtype=str)
        print(f"📖 CSVの読み込みに成功しました (確定エンコード: {enc}) | 総件数: {len(df)} 件")
        break
    except Exception:
        continue

if df is None:
    print("🚨 [エラー] CSVの読み込みに失敗しました。文字コードが特殊な可能性があります。")
    exit(1)

# 3. Kaoruさんの指摘に基づく「.0」の揺らぎ・文字化けの完全クレンジング
print("🧹 データの全細胞を検査し、隠れた「.0」と余計な空白を焼き尽くします...")
cleaned_data = []
id_column = None

# ドキュメントIDとして使えそうな列（IDやNo）を自動探索
for possible_id in ['ID', 'id', 'No', 'no', '管理番号']:
    if possible_id in df.columns:
        id_column = possible_id
        break

for index, row in df.iterrows():
    doc_data = {}
    for col, val in row.items():
        clean_col = str(col).strip() # 列名の前後のゴミ空白を削除
        
        if pd.isna(val):
            doc_data[clean_col] = ""
            continue
            
        val_str = str(val).strip()
        
        # 【最重要】浮動小数点バグ（.0）が文字列末尾に付着していたら即座に抹殺
        if val_str.endswith('.0'):
            val_str = val_str[:-2]
            
        doc_data[clean_col] = val_str
        
    cleaned_data.append(doc_data)

# 4. 500件ずつのWriteBatchによるFirestoreへの超高速インポート
print(f"🚀 金庫 [photo master] コレクションへ、綺麗になった15,000件のデータを爆速上書きします...")
collection_ref = db.collection("photo master")

batch = db.batch()
count = 0
total_count = len(cleaned_data)

for i, data in enumerate(cleaned_data):
    # ID列があればそれをドキュメント名にして上書き、なければ自動生成
    if id_column and data.get(id_column):
        doc_id = data[id_column]
        doc_ref = collection_ref.document(doc_id)
    else:
        doc_ref = collection_ref.document()
        
    batch.set(doc_ref, data)
    count += 1
    
    # Firestoreの上限500件ごとに一括コミット
    if count == 500:
        batch.commit()
        print(f"📥 【進捗】 {i+1} / {total_count} 件を金庫に格納完了...")
        batch = db.batch()
        count = 0

if count > 0:
    batch.commit()

print(f"✨ 【完全勝利】 すべてのクレンジングデータの格納が完了しました！ 総件数: {total_count} 件")