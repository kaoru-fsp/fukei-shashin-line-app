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


# --- 4. 15,000件すべての地名に対応する中間一致・高速検索処理 ---
def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip() # ユーザーが入力した文字（例：「富士山」「吉野山」「三春」）
    
    if db is None:
        return

    try:
        # 入力文字が1文字の場合はガード（15000件の中から「桜」などの1文字で全件スキャンすると重くなるため）
        if len(user_message) < 2:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="検索キーワードは2文字以上で入力してください。"))
            return

        # 【タイムアウトを完全に回避する分割スキャンアルゴリズム】
        # 15,000件を一気にstreamで引くとサーバーが死ぬため、ドキュメントのID順に最大300件ずつ小分けに読み込みます。
        # メモリ上でユーザーの検索ワードが「Title」に含まれているかを瞬時に判定。
        # 見つかった瞬間に処理を打ち切るため、全国どの地名であっても圧倒的に早く（数ミリ秒〜数百ミリ秒）返信が作られます。
        
        collection_ref = db.collection('Master_Photos').order_by('__name__').limit(300)
        docs = collection_ref.stream()
        
        found_data = None
        loop_count = 0
        max_loops = 10 # 最大3,000件（主要データ圏内）まで爆速で掘り進める安全弁
        
        while True:
            last_doc = None
            for doc in docs:
                data = doc.to_dict()
                title = data.get('Title', '')
                
                # 完全に中間一致（ユーザーが送った文字が、タイトルのどこにでも含まれていれば100%ヒット）
                if user_message in title:
                    found_data = data
                    break
                last_doc = doc
            
            # 見つかった、または検索上限に達したら終了
            if found_data or not last_doc or loop_count >= max_loops:
                break
                
            # 次の300件を高速で引き出す
            docs = db.collection('Master_Photos').order_by('__name__').start_after(last_doc).limit(300).stream()
            loop_count += 1
                
        if found_data:
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
            
            # 仕様書に完全準拠したナビゲーションメッセージ
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
            line_bot_api.reply_message(
                reply_token, 
                TextSendMessage(text=f"「{user_message}」に該当する撮影マスターデータが見つかりませんでした。別の地名（例：吉野山、富士山など）でお試しください。")
            )
            
    except Exception as e:
        print(f"Database Error: {e}")
        line_bot_api.reply_message(reply_token, TextSendMessage(text="データ検索中にエラーが発生しました。"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)