import os
import json
import random
from flask import Flask, request, abort
from linebot import LineBotApi
from linebot.models import TextSendMessage, FlexSendMessage
import firebase_admin
from firebase_admin import credentials, firestore
from openai import OpenAI

app = Flask(__name__)

# --- 1. LINE API の初期化 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

# --- 2. OpenAI API の初期化 ---
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ai_client = OpenAI(api_key=OPENAI_API_KEY)

# --- 3. Firebase / Firestore の初期化 ---
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


# --- 4. LINE Webhook 受信口 ---
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


# --- 5. 【完全復元】元の添削指導UI（Flex Message）の組み立て ---
def create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment):
    flex_bubble = {
      "type": "bubble",
      "hero": {
        "type": "image",
        "url": "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=1000&q=80",
        "size": "full",
        "aspectRatio": "20:13",
        "aspectMode": "cover"
      },
      "body": {
        "type": "box",
        "layout": "vertical",
        "contents": [
          {"type": "text", "text": "🌸 AIコンシェルジュ厳選提案", "weight": "bold", "color": "#1DB954", "size": "sm"},
          {"type": "text", "text": location, "weight": "bold", "size": "xl", "margin": "md", "wrap": True},
          {
            "type": "box",
            "layout": "vertical",
            "margin": "lg",
            "spacing": "sm",
            "contents": [
              {
                "type": "box",
                "layout": "baseline",
                "spacing": "sm",
                "contents": [
                  {"type": "text", "text": "作品名", "color": "#aaaaaa", "size": "sm", "flex": 2},
                  {"type": "text", "text": f"{title} (撮影: {author} 様)", "wrap": True, "color": "#666666", "size": "sm", "flex": 5}
                ]
              },
              {
                "type": "box",
                "layout": "baseline",
                "spacing": "sm",
                "contents": [
                  {"type": "text", "text": "推奨機材", "color": "#aaaaaa", "size": "sm", "flex": 2},
                  {"type": "text", "text": f"{camera}\n{lens}", "wrap": True, "color": "#666666", "size": "sm", "flex": 5}
                ]
              },
              {
                "type": "box",
                "layout": "baseline",
                "spacing": "sm",
                "contents": [
                  {"type": "text", "text": "撮影設定", "color": "#aaaaaa", "size": "sm", "flex": 2},
                  {"type": "text", "text": settings, "wrap": True, "color": "#666666", "size": "sm", "flex": 5}
                ]
              }
            ]
          },
          {"type": "separator", "margin": "xxl"},
          {
            "type": "box",
            "layout": "vertical",
            "margin": "xxl",
            "contents": [
              {"type": "text", "text": "📖 【現地ナビ・アクセス】", "weight": "bold", "size": "md", "color": "#111111"},
              {"type": "text", "text": guide, "wrap": True, "size": "sm", "color": "#555555", "margin": "md"}
            ]
          },
          {"type": "separator", "margin": "xxl"},
          {
            "type": "box",
            "layout": "vertical",
            "margin": "xxl",
            "backgroundColor": "#f7f8fa",
            "cornerRadius": "md",
            "paddingAll": "md",
            "contents": [
              {"type": "text", "text": "🎓 【レベルアップ相談室・添削指導】", "weight": "bold", "size": "md", "color": "#e67e22"},
              {"type": "text", "text": judge_comment, "wrap": True, "size": "sm", "color": "#333333", "margin": "sm"}
            ]
          }
        ]
      }
    }
    return flex_bubble


# --- 6. メイン処理：元の項目名（Location, Author等）を1ミリも変えずに完全合致 ---
def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    
    if db is None:
        return

    try:
        # OpenAIで入力文から適切な検索キーワードを特定
        intent_response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "ユーザーの文章から、撮影地や被写体に関するキーワード（例：長野、富士山、桜など）を1つだけ抽出してください。"},
                {"role": "user", "content": user_message}
            ],
            temperature=0.0
        )
        keyword = intent_response.choices[0].message.content.strip()
        
        photos_ref = db.collection('Master_Photos')
        matched_photos = []
        
        # タイムアウトとインデックスエラーを防ぐため、安全な上限数（500件）をロードして部分一致判定
        search_limit_docs = photos_ref.limit(500).stream()
        
        for doc in search_limit_docs:
            data = doc.to_dict()
            db_loc = str(data.get('Location', ''))
            db_title = str(data.get('Title', ''))
            
            # 【完全維持】元の項目名「Location」「Title」でキーワード判定
            if keyword in db_loc or keyword in db_title or user_message in db_loc:
                matched_photos.append(data)
                if len(matched_photos) >= 10:
                    break
        
        # 万が一ヒットしない場合の安全策
        if not matched_photos:
            backup_docs = photos_ref.limit(5).stream()
            matched_photos = [doc.to_dict() for doc in backup_docs]

        target_data = random.choice(matched_photos)

        # ─── 【重要】元の項目名（フィールド名）を100%そのまま維持して抽出 ───
        title = target_data.get('Title', '無題')
        location = target_data.get('Location', '不明な撮影地')
        author = target_data.get('Author', '不明')
        camera = target_data.get('Camera_Body', '情報なし')
        lens = target_data.get('Lens', '情報なし')
        
        aperture = target_data.get('Aperture', '-')
        iso = target_data.get('ISO', '-')
        focal = target_data.get('Focal_Length', '-')
        settings = f"F{aperture} / ISO {iso} / {focal}mm"
        
        weather = target_data.get('Weather', '不明')
        guide = target_data.get('Guide_Page', 'ナビ情報は現在準備中です。')
        judge_comment = target_data.get('Judge_Comment_Summary', '審査員アドバイスは現在準備中です。')

        # ─── 元の事実データのみをAIに渡し、中身の詰まった具体的な案内文を作らせる ───
        system_prompt = """
        あなたは雑誌『風景写真』のライブラリー司書です。
        与えられた【データ】の事実（作品名、撮影地、作者名、機材設定など）を必ず文章の中に具体的に盛り込んで、
        シニア写真愛好家の方へ向けた、丁寧で役に立つ案内文を作成してください。
        データが「情報なし」や「準備中」となっている場合は、正直にその旨を伝えてください。
        """
        
        user_prompt = f"""
        【データ】
        ・作品名: 「{title}」
        ・撮影地: {location}
        ・作者: {author} 様
        ・推奨機材: {camera} ({lens})
        ・撮影設定: {settings}
        
        ユーザーの問いかけ: 「{user_message}」
        
        上記の具体的な情報をしっかりと文章に含めて、150文字程度の案内文を作ってください。最後は「こちらの名作の書棚を開きましたので、どうぞご高覧ください。」と結んでください。
        """
        
        response = ai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2
        )
        司書のメッセージ = response.choices[0].message.content

        # ─── LINEへ返信 ───
        bubble_json = create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment)
        
        line_bot_api.reply_message(
            reply_token,
            [
                TextSendMessage(text=司書のメッセージ),
                FlexSendMessage(alt_text="撮影地コンシェルジュレポート", contents=bubble_json)
            ]
        )
            
    except Exception as e:
        print(f"Concierge System Error: {e}")
        line_bot_api.reply_message(reply_token, TextSendMessage(text="申し訳ございません。書棚の検索中に不手際がございました。"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
