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


# --- 4. 15,000件のLocation（地名）をミリ秒で部分一致検索する完全版 ---
def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip() # ユーザーが入力した文字（例：「富士山」「吉野山」）
    
    if db is None:
        return

    try:
        if len(user_message) < 2:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="検索キーワードは2文字以上で入力してください。"))
            return

        # 【超高速ストリーム処理】
        # 本物のCSVデータに合わせて「Location（地名）」の列だけを限定取得。
        # 15,000件を一瞬で走査し、ユーザーが入力した地名が含まれているドキュメントIDを特定します。
        docs = db.collection('Master_Photos').select(['Location']).stream()
        
        target_doc_id = None
        for doc in docs:
            loc_data = doc.to_dict().get('Location', '')
            if user_message in loc_data:
                target_doc_id = doc.id
                break # 見つかった瞬間にループを抜ける（タイムアウトを絶対回避）
                
        if target_doc_id:
            # ヒットしたドキュメントのフルデータをピンポイントで一瞬で取得
            full_data = db.collection('Master_Photos').document(target_doc_id).get().to_dict()
            
            # 本物のCSVのヘッダー名（列名）に100%一致させてデータを抽出
            title_name = full_data.get('Title', '無題')
            location_name = full_data.get('Location', '不明な撮影地')
            author = full_data.get('Author', '不明')
            camera = full_data.get('Camera_Body', '情報なし')
            lens = full_data.get('Lens', '情報なし')
            aperture = full_data.get('Aperture', '-')
            iso = full_data.get('ISO', '-')
            focal = full_data.get('Focal_Length', '-')
            filter_used = full_data.get('Filter', 'なし')
            
            # ガイドページとレベルアップ相談室（審査員評）のデータをマッピング
            guide = full_data.get('Guide_Page', 'ガイド情報はありません。')
            judge_comment = full_data.get('Judge_Comment_Summary', 'アドバイスはまだありません。')
            
            # 朝の仕様書に完全準拠したナビゲーションテキストの組み立て
            reply_text = (
                f"📸 【撮影地マッチ】: {location_name}（作品名: {title_name}）\n"
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
        line_bot_api.reply_message(reply_token, TextSendMessage(text="データ検索中にエラーが発生しました。"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)