import os
import json
from flask import Flask, request, abort
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, ImageSendMessage
)

if not firebase_admin._apps:
    # Render上の環境変数（先ほど設定したもの）から鍵を読み込む
    firebase_creds = os.environ.get('FIREBASE_CREDENTIALS')
    
    if firebase_creds:
        # 環境変数がある場合（Render環境）
        cred_dict = json.loads(firebase_creds)
        cred = credentials.Certificate(cred_dict)
    else:
        # 環境変数がない場合（あなたのパソコン環境）
        cred = credentials.Certificate('serviceAccountKey.json')
        
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ==========================================
# 設定（環境変数または直接入力）
# ==========================================
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get(
    'LINE_CHANNEL_ACCESS_TOKEN',
    'zl9qX3l1P1CZ/h3umY+dExVdF+Q0kfZfGQrPUzd/8u9GeYb4nN7HtH6uqmItwsjUJikT1AbJea17R0dgyeXP+sK8fBThy1PLkWoDsYzYpZV3TUHXHGiarezI+QyxaBZgGEvfizLTa7JibDrYoUoT1wdB04t89/10/w1cDnyi1FU='
)

# シークレットはLINE Developersコンソールから取得して設定してください
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', '72f4758bcd9918d175946a01597f9ea')
# クローズドテスト用のユーザーID
TEST_USER_ID = 'U9d8196b4cec0551a812809ed156b1877'

# Firestoreのコレクション名
FIRESTORE_COLLECTION_NAME = 'photos'

app = Flask(__name__)

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ==========================================
# Firestoreの初期化
# ==========================================
try:
    # 外部サーバで実行する際は GOOGLE_APPLICATION_CREDENTIALS にJSONキーのパスを設定してください
    initialize_app()
    db = firestore.client()
    print("Firestore initialized successfully.")
except Exception as e:
    print(f"Firestore initialization error: {e}")
    db = None

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id

    # 1. セキュリティ: テスト用ユーザーID以外からのメッセージは完全スルー
    if user_id != TEST_USER_ID:
        print(f"Unauthorized access blocked from user: {user_id}")
        return

    user_text = event.message.text
    print(f"Received message: '{user_text}' from {user_id}")

    if not db:
        line_bot_api.reply_message(event.reply_token, [TextSendMessage(text="データベース未接続")])
        return

    # 2. Firestoreを検索 
    # Firestoreの仕様上、今回は15,000件に対応できる `array_contains` または部分一致フィルタリングを利用します。
    results = []
    
    # 手法A: tags配列へのキーワード完全一致
    docs = db.collection(FIRESTORE_COLLECTION_NAME).where('tags', 'array_contains', user_text).limit(3).stream()
    for doc in docs:
        results.append(doc.to_dict())
    
    # 手法B: ヒットしなかった場合、最大100件取得してタイトル/詳細テキストの手動部分一致フィルタ（本来はAlgolia等の併用を推奨）
    if len(results) == 0:
         query = db.collection(FIRESTORE_COLLECTION_NAME).limit(100).stream()
         for doc in query:
             data = doc.to_dict()
             title = data.get('title', '')
             desc = data.get('description', '')
             if user_text in title or user_text in desc:
                 results.append(data)
                 if len(results) >= 3:
                     break
    
    if len(results) == 0:
        line_bot_api.reply_message(
            event.reply_token,
            [TextSendMessage(text=f"「{user_text}」に一致する風景写真が見つかりませんでした。")]
        )
        return

    # 3. 紙芝居形式の構成（最大5スロット制御）
    # LINEの制限で1回の返信は「最大5枠」です。3件を「画像＋テキスト」で送ると枠数オーバー（6枠）になりAPIが落ちるため、
    # 最大送信件数を「2件（計4スロット）」に自動成端することで確実に動作させる仕様にしています。
    messages_to_send = []
    max_items = 2 

    for item in results[:max_items]:
        image_url = item.get('imageUrl', 'https://via.placeholder.com/1024x768.png?text=No+Image')
        title = item.get('title', '無題')
        description = item.get('description', '')
        
        # 安全弁: LINEのImageSendMessageはhttps必須
        if not image_url.startswith("https://"):
            image_url = "https://via.placeholder.com/1024x768.png?text=Invalid+Image+URL"

        # 【枠1】画像メッセージ
        messages_to_send.append(
            ImageSendMessage(original_content_url=image_url, preview_image_url=image_url)
        )
        
        # 【枠2】テキストメッセージ
        text_content = f"■ {title}\n{description}"
        if len(text_content) > 1000:
            text_content = text_content[:1000] + "..."

        messages_to_send.append(TextSendMessage(text=text_content))

    # 一括送信
    line_bot_api.reply_message(event.reply_token, messages_to_send)
    print(f"Sent {len(messages_to_send)} slots successfully.")

if __name__ == "__main__":
    # Render 等の PaaS でも動くようポートを環境変数から取得
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)