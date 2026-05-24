import os
import json
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

# --- 1. LINE API の初期化 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

# --- 2. Firebase / Firestore の初期化 ---
db = None
try:
    firebase_creds_json = os.environ.get('FIREBASE_CREDENTIALS')
    if firebase_creds_json:
        creds_dict = json.loads(firebase_creds_json)
        cred = credentials.Certificate(creds_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("Firestore initialized successfully.")
except Exception as e:
    print(f"Firestore initialization error: {e}")


# --- 3. LINE Webhook 受信口 ---
@app.route("/callback", methods=['POST'])
def callback():
    try:
        request_json = request.get_json()
        events = request_json.get('events', [])
        for event in events:
            if event.get('type') == 'message' and event['message'].get('type') == 'text':
                handle_line_message(event)
    except Exception as e:
        print(f"Error processing webhook event: {e}")
    return 'OK', 200


# --- 4. 本物のデータ構造（Title内の部分一致）に対応した処理 ---
def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip() # ユーザーが送ってきた文字（例：「富士山」「吉野」）
    
    if db is None:
        return

    try:
        # 【超強化：ガチガチ一致不要の全データ検索】
        # 15,000件のデータをストリームで取得（ limit をかけつつ効率よく検索 ）
        docs = db.collection('Master_Photos').stream()
        
        found_data = None
        
        # 取得したデータの中から、ユーザーの入力文字が「Title」に含まれているものを探す（中間一致）
        for doc in docs:
            data = doc.to_dict()
            title = data.get('Title', '')
            
            # データベースの「Title」の中に、送られてきた文字（例：「富士山」）が含まれているか判定
            if user_message in title:
                found_data = data
                break # 1件見つかったらその時点で確定
                
        if found_data:
            # 本物のCSVヘッダー名に100%一致させてデータ抽出
            title_name = found_data.get('Title', '無題の撮影地')
            author = found_data.get('Author', '不明')
            camera = found_data.get('Camera_Body', '情報なし')
            lens = found_data.get('Lens', '情報なし')
            aperture = found_data.get('Aperture', '-')
            iso = found_data.get('ISO', '-')
            focal = found_data.get('Focal_Length', '-')
            filter_used = found_data.get('Filter', 'なし')
            
            guide = found_data.get('Guide_Page', 'ガイド情報はありません。')
            judge_comment = found_data.get('Judge_Comment_Summary', 'アドバイスはまだありません。')
            
            # 朝の仕様書通りのリッチな返信テキスト
            reply_text = (
                f"📸 【撮影地マッチ】: {title_name}\n"
                f"📷 撮影者: {author}\n"
                f"🛠️ 機材: {camera} / {lens}\n"
                f"⚙️ 設定: F{aperture} / ISO {iso} / 焦点距離 {focal}mm / フィルター: {filter_used}\n\n"
                f"📖 【ガイド・撮影ナビ】\n{guide}\n\n"
                f"🎓 【レベルアップ相談室（審査員評）】\n{judge_comment}"
            )
            
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
            
        else:
            # 見つからなかった場合も、ユーザーに次の行動を促すナビゲーションを返す
            line_bot_api.reply_message(
                reply_token, 
                TextSendMessage(text=f"「{user_message}」を含む撮影マスターデータが見つかりませんでした。地名やキーワードを少し変えて試してみてください。")
            )
            
    except Exception as e:
        print(f"Database Error: {e}")
        line_bot_api.reply_message(reply_token, TextSendMessage(text="データ検索中にエラーが発生しました。"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)