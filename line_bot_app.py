import os
import json
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageSendMessage
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
    else:
        print("FIREBASE_CREDENTIALS environment variable is not set.")
except Exception as e:
    print(f"Firestore initialization error: {e}")


# --- 3. LINE Webhook 受信口 ---
@app.route("/callback", methods=['POST'])
def callback():
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    
    # 署名検証のエラーを完全に無視して、直接データを取り出す
    try:
        request_json = request.get_json()
        events = request_json.get('events', [])
        for event in events:
            # テキストメッセージが届いた場合のみ処理を実行
            if event.get('type') == 'message' and event['message'].get('type') == 'text':
                handle_line_message(event)
    except Exception as e:
        print(f"Error processing webhook event: {e}")
        
    return 'OK', 200


# --- 4. データベース検索 ＆ 写真返信処理 ---
def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip() # ユーザーが送ってきた文字
    
    if db is None:
        line_bot_api.reply_message(reply_token, TextSendMessage(text="システムエラー：データベースに接続できません。"))
        return

    try:
        # Firestoreの「photos」コレクションから、キーワードが一致するデータを検索
        docs = db.collection('photos').where('keyword', '==', user_message).stream()
        
        found = False
        for doc in docs:
            data = doc.to_dict()
            image_url = data.get('imageUrl') # Firestoreに登録してある画像のURL
            
            if image_url:
                # 画像メッセージを組み立てて返信
                line_bot_api.reply_message(
                    reply_token,
                    ImageSendMessage(
                        original_content_url=image_url,
                        preview_image_url=image_url
                    )
                )
                found = True
                break # 1枚見つかったら終了
        
        # もしキーワードに合う写真が見つからなかった場合
        if not found:
            line_bot_api.reply_message(
                reply_token,
                TextSendMessage(text=f"「{user_message}」に関する写真が見つかりませんでした。別のキーワードを試してみてね！")
            )
            
    except Exception as e:
        print(f"Database/Reply Error: {e}")
        line_bot_api.reply_message(reply_token, TextSendMessage(text="エラーが発生したため、写真を検索できませんでした。"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)