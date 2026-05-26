import os
import json
import traceback
from flask import Flask, request, abort
from linebot import LineBotApi
from linebot.models import TextSendMessage
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

# --- LINE API の初期化 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

# --- Firebase / Firestore の初期化 ---
db = None
try:
    firebase_creds_json = os.environ.get('FIREBASE_CREDENTIALS')
    if firebase_creds_json:
        creds_dict = json.loads(firebase_creds_json)
        cred = credentials.Certificate(creds_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
except Exception as e:
    pass

@app.route("/callback", methods=['POST'])
def callback():
    try:
        request_json = request.get_json()
        events = request_json.get('events', [])
        for event in events:
            if event.get('type') == 'message' and event['message'].get('type') == 'text':
                handle_line_message(event)
    except Exception as e:
        print(f"🔥 Webhook Error: {traceback.format_exc()}")
    return 'OK', 200

def handle_line_message(event):
    reply_token = event['replyToken']
    
    if db is None:
        line_bot_api.reply_message(reply_token, TextSendMessage(text="❌ Firebaseの初期化自体に失敗しています。環境変数を確認してください。"))
        return

    try:
        # ─── ⚡ 【デバッグ専用】条件を1割もつけず、コレクションから1件だけ直接ロード ───
        photos_ref = db.collection('Master_Photos')
        docs = list(photos_ref.limit(1).stream())
        
        if not docs:
            # フォルダ名自体が違う可能性を考慮し、別名でも1件試す
            alternative_ref = db.collection('master_photos')
            docs = list(alternative_ref.limit(1).stream())
            if docs:
                line_bot_api.reply_message(reply_token, TextSendMessage(text="⚠️ 判明: コレクション名が『Master_Photos』ではなく小文字の『master_photos』で登録されています。"))
                return
            
            line_bot_api.reply_message(reply_token, TextSendMessage(text="❌ 物理的事実: 接続したFirestore内にデータが『1件も存在しない（空っぽ）』か、コレクション名が間違っています。"))
            return

        # データの鍵と値をそのまま文字列にする
        actual_data = docs[0].to_dict()
        debug_output = "📊 【DB内部データ生中継】\n"
        debug_output += f"ドキュメントID: {docs[0].id}\n\n"
        for key, value in actual_data.items():
            debug_output += f"■ フィールド名: {key}\n   └ 値: {value} (型: {type(value).__name__})\n"

        # そのままLINEに送信
        line_bot_api.reply_message(reply_token, TextSendMessage(text=debug_output))

    except Exception as e:
        raw_error = traceback.format_exc()
        line_bot_api.reply_message(reply_token, TextSendMessage(text=f"🔥 クエリ実行中にエラーが発生しました:\n{raw_error}"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
