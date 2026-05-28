import os
import json
import random
import re
from flask import Flask, request
from linebot import LineBotApi
from linebot.models import FlexSendMessage, TextSendMessage
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

# 📸 デモを華やかに彩る、超高画質風景写真の厳選ライブラリーURL
IMAGE_POOL = {
    "sakura": "https://images.unsplash.com/photo-1522383225653-ed111181a951?w=600", # 満開の桜
    "sunrise": "https://images.unsplash.com/photo-1506744038136-46273834b3fb?w=600", # 朝焼け
    "mountain": "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?w=600", # 霧・山・高原
    "water": "https://images.unsplash.com/photo-1439405326854-014607f694d7?w=600", # 水面・滝・湖
    "default": "https://images.unsplash.com/photo-1470071459604-3b5ec3a7fe05?w=600" # 壮大な大自然
}

def get_beautiful_url(keyword, title, location):
    text = str(keyword) + str(title) + str(location)
    if any(k in text for k in ["桜", "春", "花"]): return IMAGE_POOL["sakura"]
    if any(k in text for k in ["朝焼け", "日の出", "黎明", "光", "夕日"]): return IMAGE_POOL["sunrise"]
    if any(k in text for k in ["山", "霧", "森", "木", "高原", "霧ヶ峰"]): return IMAGE_POOL["mountain"]
    if any(k in text for k in ["海", "川", "滝", "湖", "水"]): return IMAGE_POOL["water"]
    return IMAGE_POOL["default"]

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

# --- 2. コンシェルジュ・リッチUIエンジン ---
def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    
    current_db = get_db()
    if current_db is None: return

    # AIによる高精度検索インテントの分離
    intent_pref = ""
    intent_keyword = "朝焼け"
    try:
        intent_response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": 'ユーザーの言葉から検索のヒントを抽出し、以下のJSONで出力。{"pref": "都道府県名。なければ空文字", "keyword": "撮影キーワード（日の出、桜、朝霧、新緑など）。なければ朝焼け"}'},
                {"role": "user", "content": user_message}
            ],
            temperature=0.1
        )
        intent = json.loads(intent_response.choices[0].message.content)
        intent_pref = intent.get("pref", "")
        intent_keyword = intent.get("keyword", "朝焼け")
    except: pass

    # 金庫（純度100%の1085件）からの複数候補スキャン
    matched_photos = []
    try:
        ref = current_db.collection('Master_Photos')
        if intent_pref:
            docs = ref.where('Prefecture', '==', intent_pref).limit(5).stream()
            matched_photos = [doc.to_dict() for doc in docs]
        
        if not matched_photos:
            wide_docs = ref.limit(300).stream()
            for doc in wide_docs:
                d = doc.to_dict()
                if intent_keyword in str(d.get('Subject','')) or intent_keyword in str(d.get('Location','')) or intent_keyword in str(d.get('Title','')):
                    matched_photos.append(d)
                    if len(matched_photos) >= 5: break
                    
        if not matched_photos:
            matched_photos = [doc.to_dict() for doc in ref.limit(3).stream()]
    except: pass

    if not matched_photos: return

    # メイン決定版と、カルーセル（選択肢）用の複数候補をセット
    main_data = matched_photos[0]
    choice_datas = matched_photos[:3]

    # 純度100%のデータをマッピング
    title = main_data.get('Title', '無題')
    location = main_data.get('Location', '日本国内の撮影地')
    author = main_data.get('Author', 'ライブラリー記録')
    camera = main_data.get('Camera_Body', '情報なし')
    lens = main_data.get('Lens', '情報なし')
    aperture = main_data.get('Aperture', '-')
    iso = main_data.get('ISO', '-')
    focal = main_data.get('Focal_Length', '-')
    weather = main_data.get('Weather', '').strip()
    guide = main_data.get('Judge_Comment_Summary', 'ナビゲーションデータを確認中です。')

    settings = f"F{aperture} ／ ISO {iso} ／ {focal}mm"
    
    # お天気セリフのマッピング（日本語崩壊防止）
    if not weather or weather.lower() in ["nan", "none", "不明", ""]:
        weather_phrase = "明日はお天気もいいようですから"
        weather_display = "晴れ"
    elif "晴" in weather or "快晴" in weather:
        weather_phrase = f"明日はお天気も{weather}のようですから"
        weather_display = weather
    else:
        weather_phrase = f"明日はお天気も{weather}模様のようですから"
        weather_display = weather

    # --- ✨ ① 「ようこそ〜」のくだりを120%活かしたテキストメッセージ ---
    if "明日" in user_message:
        greeting = f"ようこそ『風景写真』コンシェルジュの部屋へ。それで明日撮影にお出かけですか。{weather_phrase}撮影も楽しめそうですね。今時分ですと皆さんこんなところでいい作品を撮っているようですよ"
    else:
        greeting = f"ようこそ『風景写真』コンシェルジュの部屋へ。本日は撮影のご相談でしょうか。今時分ですと皆さんこんなところでいい作品を撮っているようですよ"
    
    msg_text = TextSendMessage(text=greeting)

    # --- 📸 ② 写真付き選択肢（カルーセルFlex） ---
    carousel_bubbles = []
    for c in choice_datas:
        c_title = c.get('Title', '無題')
        c_loc = c.get('Location', '日本国内の撮影地')
        c_img = get_beautiful_url(intent_keyword, c_title, c_loc)
        
        bubble = {
            "type": "bubble",
            "size": "micro",
            "hero": {
                "type": "image",
                "url": c_img,
                "size": "full",
                "aspectRatio": "4:3",
                "aspectMode": "cover"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#fafafa",
                "contents": [
                    {"type": "text", "text": f"「{c_title}」", "weight": "bold", "size": "sm", "wrap": True, "color": "#2c3e50"},
                    {"type": "text", "text": c_loc, "size": "xs", "color": "#777777", "wrap": True, "margin": "xs"}
                ]
            }
        }
        carousel_bubbles.append(bubble)
        
    msg_carousel = FlexSendMessage(
        alt_text="お勧めの撮影地選択肢",
        contents={"type": "carousel", "contents": carousel_bubbles}
    )

    # --- 📖 ③ 【完全体】詳細案内カード（文字が潰れないメガ仕様・余白ゼロ） ---
    main_img = get_beautiful_url(intent_keyword, title, location)
    detail_json = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1f3c3d",
            "paddingAll": "xl",
            "contents": [
                {"type": "text", "text": "📖 ライブラリー撮影地詳細知見", "color": "#ffffff", "weight": "bold", "size": "md"}
            ]
        },
        "hero": {
            "type": "image",
            "url": main_img,
            "size": "full",
            "aspectRatio": "16:10",
            "aspectMode": "cover"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "lg",
            "paddingAll": "xl",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "xs",
                    "contents": [
                        {"type": "text", "text": f"🗺️ 撮影地：{location}", "weight": "bold", "size": "md", "wrap": True, "color": "#111111"},
                        {"type": "text", "text": f"■ 参考作品：「{title}」 （{author} 著）", "size": "sm", "color": "#555555", "wrap": True, "margin": "xs"}
                    ]
                },
                {"type": "separator", "color": "#eeeeee"},
                {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "xs",
                    "contents": [
                        {"type": "text", "text": "📸 過去の記録に基づく撮影条件", "weight": "bold", "size": "sm", "color": "#1f3c3d"},
                        {"type": "text", "text": f"• 機材: {camera} ／ {lens}", "size": "sm", "color": "#444444", "wrap": True},
                        {"type": "text", "text": f"• 条件: {settings} （天候: {weather_display}）", "size": "sm", "color": "#444444", "wrap": True}
                    ]
                },
                {"type": "separator", "color": "#eeeeee"},
                {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "xs",
                    "contents": [
                        {"type": "text", "text": "📚 情報ライブラリーの司書知見", "weight": "bold", "size": "sm", "color": "#1f3c3d"},
                        {"type": "text", "text": guide, "size": "md", "color": "#222222", "wrap": True, "lineSpacing": "md", "margin": "xs"}
                    ]
                }
            ]
        }
    }
    
    msg_detail = FlexSendMessage(alt_text="撮影地詳細ナビゲーションカード", contents=detail_json)

    # --- 🚀 3通を完璧なコンボで同時送信 ---
    try:
        line_bot_api.reply_message(reply_token, [msg_text, msg_carousel, msg_detail])
    except Exception: pass

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
