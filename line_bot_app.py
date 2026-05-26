import os
import glob
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore

# ==========================================================
# ⚙️ 設定箇所
# ==========================================================
CSV_FOLDER_NAME = 'photos_csv'      # 14冊のCSVをまとめて入れるフォルダ名
COLLECTION_NAME = 'contest_data_v2' # まっ先にやり直すための新フォルダ名
# ==========================================================

print("⏳ Firebaseの接続を初期化しています...")
try:
    cred = credentials.Certificate('serviceAccountKey.json')
    firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    print(f"❌ Firebaseの初期化に失敗しました: {e}")
    exit()

def safe_int(val):
    try:
        return int(float(str(val).strip()))
    except:
        return 0

# 14冊のファイルをフォルダ内から一括検知
csv_files = glob.glob(os.path.join(CSV_FOLDER_NAME, '*.csv'))

if not csv_files:
    print(f"❌ エラー: '{CSV_FOLDER_NAME}' フォルダの中にCSVファイルが1件も見つかりません。")
    exit()

print(f"🔍 フォルダ内に {len(csv_files)} 冊のCSV候補を確認しました。")
print("🔍 Firestoreから既に登録済みの作品を照合しています（重複防止）...")
existing_keys = set()
try:
    docs = db.collection(COLLECTION_NAME).stream()
    for doc in docs:
        data = doc.to_dict()
        title = str(data.get('Title', '')).strip()
        winner = str(data.get('Winner', '')).strip()
        if title and winner:
            existing_keys.add((title, winner))
except Exception as e:
    print(f"⚠️ 既存データ照合中の通知（空の場合は問題ありません）: {e}")

print(f"🚀 500件小分け連動インポートを開始します（現在登録済み: {len(existing_keys)}件）...")

batch = db.batch()
uploaded_count = 0

for file_path in sorted(csv_files):
    file_name = os.path.basename(file_path)
    
    # 🚨 【Macの罠を粉砕】「._」から始まるニセモノの隠しファイルは無条件でスキップ
    if file_name.startswith('._'):
        continue
        
    print(f"📖 現在、ファイル: {file_name} を文字化けガード仕様で処理中...")
    try:
        df = pd.read_csv(file_path, encoding='utf-8-sig')
        df = df.fillna('')
    except Exception as e:
        # 万が一、Numbers等で開きっぱなしでロックされている場合の親切な警告文
        print(f"⚠️ ファイル {file_name} の読み込みに失敗しました（Numbers等で開きっぱなしの場合は閉じてください）: {e}")
        continue

    for index, row in df.iterrows():
        csv_title = str(row.get('Title', '')).strip()
        csv_winner = str(row.get('Winner', '')).strip()
        
        if not csv_title or not csv_winner:
            continue
            
        if (csv_title, csv_winner) in existing_keys:
            continue

        doc_data = {
            "dNumb": safe_int(row.get('dNumb')),
            "Published": str(row.get('Published', '')).strip(),
            "PicFileName": str(row.get('PicFileName', '')).strip(),
            "Page": safe_int(row.get('Page')),
            "Winner": csv_winner,
            "Winner4Search": str(row.get('Winner4Search', '')).strip(),
            "Title": csv_title,
            "WinnerArea": str(row.get('WinnerArea', '')).strip(),
            "WinnerClub1": str(row.get('WinnerClub1', '')).strip(),
            "WinnerClub2": str(row.get('WinnerClub2', '')).strip(),
            "Area": str(row.get('Area', '')).strip(),
            "Place": str(row.get('Place', '')).strip(),
            "DayTime": str(row.get('DayTime', '')).strip(),
            "Year": safe_int(row.get('Year')),
            "Month": safe_int(row.get('Month')),
            "Day": safe_int(row.get('Day')),
            "Hour": safe_int(row.get('Hour')),
            "Min": safe_int(row.get('Min')),
            "Weather": str(row.get('Weather', '')).strip(),
            "Subject": str(row.get('Subject', '')).strip(),
            "Composition": str(row.get('Composition', '')).strip(),
            "Camera": str(row.get('Camera', '')).strip(),
            "Lens": str(row.get('Lens', '')).strip(),
            "Exposure": str(row.get('Exposure', '')).strip(),
            "DataOfPhoto": str(row.get('DataOfPhoto', '')).strip(),
            "MapLink": str(row.get('MapLink', '')).strip(),
            "OfficialSite": str(row.get('OfficialSite', '')).strip()
        }

        doc_ref = db.collection(COLLECTION_NAME).document()
        batch.set(doc_ref, doc_data)
        uploaded_count += 1

        if uploaded_count >= 500:
            batch.commit()
            print(f"✨ 成功: 14冊のデータの中から、本日分のジャスト500件を流し込みました。安全のため自動停止します。")
            print(f"💡 残りの続きは、明日（または数分後）またこのスクリプトを実行すれば、今日止まった続きから再開されます。")
            exit()

if uploaded_count > 0:
    batch.commit()
    print(f"✨ 今回分のデータ {uploaded_count} 件をすべて送信し、現在のインポートが安全に完了しました！")
else:
    print(f"😎 フォルダ内のすべての本物のCSVデータが既にFirestoreに登録済みです。")
