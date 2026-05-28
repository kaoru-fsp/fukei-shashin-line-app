import pandas as pd
import re

# エラーを無視して安全にUTF-8で強制ロード
try:
    df = pd.read_csv('Multilayered_Contest_Data_Master.csv', encoding='utf-8-sig', encoding_errors='ignore')
except TypeError:
    df = pd.read_csv('Multilayered_Contest_Data_Master.csv', encoding='utf-8-sig')

df = df.fillna("")
print("🔍 文字化け（Shift_JISが混ざった巻）の検出を開始します...\n")

count = 0
for i, r in df.iterrows():
    # 検索対象のテキストを結合
    text_to_check = str(r.get('Judge_Comment_Summary', '')) + str(r.get('Location', '')) + str(r.get('Title', ''))
    
    # UTF-8で読み込んだときに、Shift_JISの行が化けたとき特有の文字列（縺、繧など）を検出
    if re.search(r'[縺-繧]', text_to_check) or '' in text_to_check:
        
        # もしCSV内に「巻数」や「元ファイル名」の列（VolやFile、巻、本）があれば自動で拾う
        file_hint = ""
        for col in df.columns:
            if any(k in str(col).lower() for k in ['vol', 'book', '巻', 'ファイル', 'file', 'source']):
                file_hint = f" ＞ 【元データ情報】 {col}: {r[col]}"
        
        print(f"❌ 【CSVの {i} 行目】 作品:「{r.get('Title')}」 著者:{r.get('Author')}{file_hint}")
        count += 1
        if count >= 15:
            print("\n⚠️ 15件以上あるため出力を省略します。このあたりの作品が入っているファイルが犯人です。")
            break

if count == 0:
    print("💡 通常の化け文字パターンではヒットしませんでした。すべて綺麗に読めている可能性があります。")
