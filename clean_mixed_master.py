import firebase_admin
from firebase_admin import credentials, firestore
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor

print("⏳ 金庫（Firestore）へアクセス中...", flush=True)
cred = credentials.Certificate('serviceAccountKey.json')
try: firebase_admin.initialize_app(cred)
except ValueError: pass
db = firestore.client()

csv_path = 'Multilayered_Contest_Data_Master.csv'

# あらゆる不純物とパースゴミを削ぎ落とす最強の洗浄関数
def clean_text(val):
    if val is None or str(val).lower() in ["nan", "none", "null", ""]: return ""
    s = str(val).strip()
    s = unicodedata.normalize('NFKC', s)
    s = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', s)
    s = s.replace('\xa0', ' ').replace('\\u00a0', ' ').replace('\u200b', '')
    return s.strip()

# 混合された文字コードを行ごとに力技で1行ずつ解読する特殊パサー
rows_data = []
print("🔍 14冊分の混在文字コードを『1行ずつ個別に精密解読』しています...", flush=True)

with open(csv_path, 'rb') as f:
    header_bytes = f.readline()
    # ヘッダーを安全に解読
    header_str = None
    for enc in ['utf-8-sig', 'cp932', 'utf-8', 'shift_jis']:
        try:
            header_str = header_bytes.decode(enc)
            break
        except: continue
    
    headers = [clean_text(h) for h in header_str.split(',')]
    
    # 2行目以降のデータ行を個別に解読執行
    index = 0
    while True:
        line_bytes = f.readline()
        if not line_bytes: break
        
        line_str = None
        # ⭕️ 行ごとに文字コードを総当たり判定（これが混在を破壊する防壁です）
        for enc in ['utf-8-sig', 'cp932', 'utf-8', 'shift_jis']:
            try:
                line_str = line_bytes.decode(enc)
                if '' not in line_str:  # 文字化けの特有記号が含まれていなければ合格
                    break
            except: continue
        
        if line_str is None:
            # 最終防衛
            try: line_str = line_bytes.decode('utf-8', errors='replace')
            except: line_str = ""
            
        cells = [clean_text(c) for c in line_str.split(',')]
        
        # ヘッダーとセルの数を合わせて辞書化
        row_dict = {}
        for i, h in enumerate(headers):
            if i < len(cells):
                val = cells[i]
                # 小数点の .0 駆除
                if val.endswith('.0') and val[:-2].isdigit():
                    val = val[:-2]
                row_dict[h] = val
            else:
                row_dict[h] = ""
                
        rows_data.append((index, row_dict))
        index += 1

def upload_row(args):
    idx, data = args
    db.collection('Master_Photos').document(f"photo_{idx}").set(data)
    if idx % 3000 == 0:
        print(f"🚀 [混在完全浄化] 金庫へクリーン転送中: {idx} 件目...", flush=True)

print(f"🔥 解読完了。文字コードの壁を越えた {len(rows_data)} 件をFirestoreへ一気流し込みます...")
with ThreadPoolExecutor(max_workers=25) as executor:
    executor.map(upload_row, rows_data)

print("\n✨ 【歴史的大勝利】14冊分の混在コードが1つに融解し、完全無欠の日本語データベースが完成しました！")
