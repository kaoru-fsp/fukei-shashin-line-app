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


# --- 4. 15,000件を絶対にタイムアウト・クラッシュさせない検索処理 ---
def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip() # ユーザーが入力した文字（例：「富士山」「京都」）
    
    if db is None:
        return

    try:
        if len(user_message) < 2:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="検索キーワードは2文字以上で入力してください。"))
            return

        # 【超軽量化・セーフティ仕様】
        # Locationフィールドのみを狙い撃ちでストリーム。通信負荷を極限までカット。
        docs = db.collection('Master_Photos').select(['Location']).stream()
        
        target_doc_id = None
        for doc in docs:
            doc_dict = doc.to_dict()
            if not doc_dict:
                continue
                
            # KeyErrorを絶対に起こさない安全なデータ取得（空データはスキップ）
            loc_data = doc_dict.get('Location')
            if loc_data and user_message in str(loc_data):
                target_doc_id = doc.id
                break # 見つかった瞬間に終了し、タイムアウトを回避
                
        if target_doc_id:
            # ヒットした1件のフルデータをミリ秒でピンポイント取得
            full_data = db.collection('Master_Photos').document(target_doc_id).get().to_dict()
            
            title_name = full_data.get('Title', '無題')
            location_name = full_data.get('Location', '不明な撮影地')
            author = full_data.get('Author', '不明')
            camera = full_data.get('Camera_Body', '情報なし')
            lens = full_data.get('Lens', '情報なし')
            aperture = full_data.get('Aperture', '-')
            iso = full_data.get('ISO', '-')
            focal = full_data.get('Focal_Length', '-')
            filter_used = full_data.get('Filter', 'なし')
            
            # 朝の仕様書の核心データ
            guide = full_data.get('Guide_Page', 'ガイド情報はありません。')
            judge_comment = full_data.get('Judge_Comment_Summary', 'アドバイスはまだありません。')
            
            # 仕様書通りのリッチメッセージを構築
            reply_text = (
                f"📸 【撮影地マッチ】: {location_name}\n"
                f"🖼️ 作品名: {title_name}\n"
                f"📷 撮影者: {author}\n"
                f"🛠️ 機材: {camera} / {lens}\n"
                f"⚙️ 設定: F{aperture} / ISO {iso} / 焦点距離 {focal} / フィルター: {filter_used}\n\n"
                f"📖 【ガイド・撮影ナビ】\n{guide}\n\n"
                f"🎓 【レベルアップ相談室（審査員評）】\n{judge_comment}"
            )
            
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
            
        else:
            line_bot_api.reply_message(
                reply_token, 
                TextSendMessage(text=f"「{user_message}」に該当する撮影マスターデータが見つかりませんでした。別の地名でお試しください。")
            )
            
    except Exception as e:
        print(f"Database Error: {e}")
        # 万が一のエラー時もLINE側をフリーズさせずにメッセージを返す
        line_bot_api.reply_message(reply_token, TextSendMessage(text="データ検索中にエラーが発生しました。もう一度お試しください。"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)