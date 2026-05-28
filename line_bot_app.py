import os
import json
import random
from flask import Flask, request
from linebot import LineBotApi
from linebot.models import TextSendMessage
import firebase_admin
from firebase_admin import credentials, firestore
from openai import OpenAI

app = Flask(__name__)

# --- 1. API初期化 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ai_client = OpenAI(api_key=OPENAI_API_KEY)

db = None
def get_db():
    global db
    if db is not None:
        return db
    try:
        firebase_creds_json = os.environ.get('FIREBASE_CREDENTIALS')
        if firebase_creds_json:
            creds_dict = json.loads(firebase_creds_json)
            cred = credentials.Certificate(creds_dict)
            try: firebase_admin.initialize_app(cred)
            except ValueError: pass
            db = firestore.client()
            return db
    except Exception: pass
    return None

get_db()

# --- 2. Webhook受付 ---
@app.route("/callback", methods=['POST'])
def callback():
    try:
        request_json = request.get_json()
        events = request_json.get('events', [])
        for event in events:
            if event.get('type') == 'message' and event['message'].get('type') == 'text':
                handle_line_message(event)
    except Exception: pass
    return 'OK', 200

# --- 3. 撮影地ナビゲーター（ライブラリーの司書仕様） ---
def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    
    current_db = get_db()
    target_data = None

    if current_db is not None:
        try:
            matched_photos = []
            # ユーザーの言葉から、金庫を高速スキャンするための確実な1キーワードを連想抽出
            intent_response = ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "ユーザーの文章から連想される、風景写真の重要な撮影キーワード（例：日の出、朝焼け、黎明、朝霧、光、あるいは都道府県名など）を1単語だけ抽出してください。特にない場合は「朝焼け」と出力してください。"},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.1
            )
            keyword = intent_response.choices[0].message.content.strip()
            
            # 本体で完全浄化された Master_Photos からガチ検索
            ref = current_db.collection('Master_Photos')
            docs = ref.limit(150).stream()
            for doc in docs:
                d = doc.to_dict()
                if keyword in str(d.get('Subject', '')) or keyword in str(d.get('Location', '')) or keyword in str(d.get('Title', '')):
                    matched_photos.append(d)
            
            if not matched_photos:
                docs = ref.limit(5).stream()
                matched_photos = [doc.to_dict() for doc in docs]
                    
            if matched_photos:
                target_data = random.choice(matched_photos)
        except Exception: pass

    # 金庫からピカピカのデータをスッと引き出す（AIによる誤魔化しの文章補填は一切なし）
    title = target_data.get('Title', '無題') if target_data else "無題"
    location = target_data.get('Location', '日本国内の撮影地') if target_data else "日本国内の撮影地"
    author = target_data.get('Author', 'ライブラリー記録') if target_data else "ライブラリー記録"
    camera = target_data.get('Camera_Body', '情報なし') if target_data else "情報なし"
    lens = target_data.get('Lens', '情報なし') if target_data else "情報なし"
    aperture = target_data.get('Aperture', '-') if target_data else "-"
    iso = target_data.get('ISO', '-') if target_data else "-"
    focal = target_data.get('Focal_Length', '-') if target_data else "-"
    weather = target_data.get('Weather', '晴れ') if target_data else "晴れ"
    
    # 複数の想定される解説ヘッダー名から最も安全に知見データをマッピング
    guide = "ナビゲーションデータは現在確認中です。"
    if target_data:
        for key in ['Judge_Comment_Summary', 'guide', '解説', '選評', '撮影ナビ']:
            if target_data.get(key):
                guide = target_data.get(key)
                break

    settings = f"F{aperture} ／ ISO {iso} ／ {focal}mm"
    weather_word = f"も{weather}" if weather and str(weather) != "不明" else "もいい"

    # --- 4. Kaoruさん設計の見本UX・セリフを完全体現 ---
    if "明日" in user_message:
        コンシェルジュのセリフ = f"ようこそ『風景写真』コンシェルジュの部屋へ。それで明日撮影にお出かけですか。明日はお天気{weather_word}のようですから撮影も楽しめそうですね。今時分ですと皆さんこんなところでいい作品を撮っているようですよ"
    else:
        コンシェルジュのセリフ = f"ようこそ『風景写真』コンシェルジュの部屋へ。本日は撮影のご相談でしょうか。今時分ですと皆さんこんなところでいい作品を撮っているようですよ"

    # 視認性最大のプレーンテキストレイアウト
    reply_text = f"""{コンシェルジュのセリフ}

🗺️ 【撮影地ナビゲーション】
■ 撮影地：{location}
■ 参考作品：「{title}」（{author} 著）

📸 【過去の記録に基づく撮影条件】
■ 機材：{camera} ／ {lens}
  ({settings} ／ 天候：{weather})

📖 【ライブラリーの撮影地知見】
{guide}"""

    try:
        line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
    except Exception: pass

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
