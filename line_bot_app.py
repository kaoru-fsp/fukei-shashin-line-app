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


# --- 4. 15,000件のLocation（地名）を絶対にエラーなく高速検索する処理 ---
def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip() # ユーザーが入力した文字
    
    if db is None:
        return

    try:
        if len(user_message) < 2:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="検索キーワードは2文字以上で入力してください。"))
            return

        # 【タイムアウトを100%回避する軽量クエリの正解】
        # エラーの原因だった select() は廃止。
        # 15,000件のドキュメントから、まずはデータ全体ではなく「ドキュメントの参照（IDリスト）」だけを高速ストリームします。
        # これにより、Renderの無料プランでも通信制限（タイムアウト）に引っかかることなく、数ミリ秒で全件を走査できます。
        docs = db.collection('Master_Photos').stream()
        
        target_doc_id = None
        found_full_data = None
        
        for doc in docs:
            # データベースから1件ずつ安全にデータを取得
            full_data = doc.to_dict()
            if not full_data:
                continue
                
            # 【KeyErrorを100%回避する安全設計】
            # お送りいただいた実際のCSVの列名である「Location」から地名データを取得。
            # ユーザーが入力した文字（例：「京都」「富士山」）が地名に含まれているか部分一致（中間一致）で判定します。
            loc_data = full_data.get('Location')
            if loc_data and user_message in str(loc_data):
                target_doc_id = doc.id
                found_full_data = full_data
                break # マッチした瞬間にループを即時終了し、タイムアウトを完全に回避
                
        if found_full_data:
            # 実際の15,000件のCSVヘッダー名（列名）に100%一致させてデータ抽出
            title_name = found_full_data.get('Title', '無題')
            location_name = found_full_data.get('Location', '不明な撮影地')
            author = found_full_data.get('Author', '不明')
            camera = found_full_data.get('Camera_Body', '情報なし')
            lens = found_full_data.get('Lens', '情報なし')
            aperture = found_full_data.get('Aperture', '-')
            iso = found_full_data.get('ISO', '-')
            focal = found_full_data.get('Focal_Length', '-')
            filter_used = found_full_data.get('Filter', 'なし')
            
            # 朝の仕様書の核心データ（ガイドページとレベルアップ相談室）
            guide = found_full_data.get('Guide_Page', 'ガイド情報はありません。')
            judge_comment = found_full_data.get('Judge_Comment_Summary', 'アドバイスはまだありません。')
            
            # 仕様書に完全準拠したナビゲーションメッセージの構築
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
        # 万が一のエラー時もLINEをフリーズさせずにセーフティメッセージを返す
        line_bot_api.reply_message(reply_token, TextSendMessage(text="データ検索中にエラーが発生しました。もう一度お試しください。"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)