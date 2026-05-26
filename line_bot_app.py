import os
import json
import random
import re
import traceback
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi
from linebot.models import TextSendMessage, FlexSendMessage
import firebase_admin
from firebase_admin import credentials, firestore
from collections import Counter

app = Flask(__name__)
# 🎯 【確定正解】あなたが教えてくれた100%正しいベースURL
IMAGE_BASE_VIEW = "https://fupc.photo/PicsDB/PicsDB4Search"
TOKYO_LAT, TOKYO_LON = 35.6895, 139.6917

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

# 🎯 日本の47都道府県リスト（台湾・海外候補を完全にシャットアウトするための防衛線）
PREFECTURES = [
    "北海道", "青森", "岩手", "宮城", "秋田", "山形", "福島", "茨城", "栃木", "群馬",
    "埼玉", "千葉", "東京", "神奈川", "新潟", "富山", "石川", "福井", "山梨", "長野",
    "岐阜", "静岡", "愛知", "三重", "滋賀", "京都", "大阪", "兵庫", "奈良", "和歌山",
    "鳥取", "島根", "岡山", "広島", "山口", "徳島", "香川", "愛媛", "高知", "福岡",
    "佐賀", "長崎", "熊本", "大分", "宮崎", "鹿児島", "沖縄"
]

db = None
try:
    firebase_creds_json = os.environ.get('FIREBASE_CREDENTIALS')
    if firebase_creds_json:
        creds_dict = json.loads(firebase_creds_json)
        cred = credentials.Certificate(creds_dict)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        db = firestore.client()
except Exception as e:
    print(f"Firebase Init Error: {e}")

def get_photo_place_name(pdata):
    place = str(pdata.get('Place', '')).strip()
    if place and place.lower() not in ['nan', 'null', 'none', '']: return place
    area = str(pdata.get('Area', '')).strip()
    if area and area.lower() not in ['nan', 'null', 'none', '']: return area
    return "厳選撮影地"

def generate_fupc_url(photo_data):
    published = str(photo_data.get('Published', '')).strip()
    pic_file_name = str(photo_data.get('PicFileName', '')).strip()
    
    # 小数点残りのクレンジング
    if published.endswith('.0'): published = published[:-2]
    if pic_file_name.endswith('.0'): pic_file_name = pic_file_name[:-2]
    
    if published and pic_file_name and len(published) >= 4:
        # 🎯 【パターン1完全再現】あなたが実証してくれた正解の形（ベース/年/フォルダ/ファイル）を最後まで寸分違わず組み立てます
        raw_url = f"{IMAGE_BASE_VIEW}/{published[:4]}/{published}/{pic_file_name}"
        # 結合時に万が一発生するスラッシュの重複（//）だけを自動で綺麗に一本化
        return re.sub(r'(?<!:)/+', '/', raw_url)
        
    return f"{IMAGE_BASE_VIEW}/default.jpg"

def get_filtered_photos(current_month, current_day, focus_keyword=None):
    if db is None: return []
    
    if current_day <= 10: d = 1
    elif current_day <= 20: d = 2
    else: d = 3
    
    curr_idx = (current_month - 1) * 3 + d
    prev_idx = 36 if curr_idx == 1 else curr_idx - 1
    next_idx = 1 if curr_idx == 36 else curr_idx + 1
    target_slots = [prev_idx, curr_idx, next_idx]
    
    # 全件検索NGの絶対厳守クエリ
    query = db.collection('contest_data_v2').where('PeriodIdx', 'in', target_slots)
    docs = query.stream()
    
    filtered_photos = []
    for doc in docs:
        pdata = doc.to_dict()
        if not pdata: continue
        
        loc_pool = str(pdata.get('Area', '')) + str(pdata.get('Place', '')) + str(pdata.get('WinnerArea', ''))
        
        # 🎯 台湾・海外データの完全強制除外
        if any(x in loc_pool for x in ["台湾", "海外", "中国", "韓国", "アメリカ"]):
            continue
        if not any(pref in loc_pool for pref in PREFECTURES):
            continue
            
        if focus_keyword:
            search_pool = (
                str(pdata.get('Title', '')) + str(pdata.get('Area', '')) + 
                str(pdata.get('Place', '')) + str(pdata.get('Subject', '')) + 
                str(pdata.get('WinnerArea', ''))
            )
            if focus_keyword not in search_pool: continue
        filtered_photos.append(pdata)
    return filtered_photos

def create_ui_buttons(reply_text, choices_list):
    buttons_contents = []
    for item in choices_list:
        buttons_contents.append({
            "type": "button",
            "action": {"type": "message", "label": item["label"][:15], "text": item["text"]},
            "style": "secondary",
            "margin": "sm"
        })
    return {"type": "bubble", "body": {"type": "box", "layout": "vertical", "spacing": "md", "contents": [{"type": "text", "text": reply_text, "wrap": True, "size": "xl", "color": "#111111", "weight": "bold"}, {"type": "box", "layout": "vertical", "spacing": "xs", "contents": buttons_contents}]}}

def create_preview_carousel(photo1, photo2, word_name):
    t1, a1, l1, u1 = photo1.get('Title') or "無題", photo1.get('Winner') or "写真家", get_photo_place_name(photo1), generate_fupc_url(photo1)
    t2, a2, l2, u2 = photo2.get('Title') or "無題", photo2.get('Winner') or "写真家", get_photo_place_name(photo2), generate_fupc_url(photo2)
    
    return {
        "type": "carousel",
        "contents": [
            {
                "type": "bubble", "backgroundColor": "#ffffff",
                "hero": {"type": "image", "url": u1, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
                "body": {
                    "type": "box", "layout": "vertical", "spacing": "sm", 
                    "contents": [
                        {"type": "text", "text": f"📍 {l1}", "weight": "bold", "size": "xl", "wrap": True, "color": "#111111"},
                        {"type": "text", "text": f"「{t1}」 (撮影: {a1} 様)", "size": "md", "color": "#444444", "wrap": True},
                        {"type": "button", "action": {"type": "message", "label": "👉 ここに行く", "text": f"ここに行く: {word_name}"}, "style": "primary", "color": "#1DB954", "margin": "md"}
                    ]
                }
            },
            {
                "type": "bubble", "backgroundColor": "#ffffff",
                "hero": {"type": "image", "url": u2, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
                "body": {
                    "type": "box", "layout": "vertical", "spacing": "sm", 
                    "contents": [
                        {"type": "text", "text": f"📍 {l2}", "weight": "bold", "size": "xl", "wrap": True, "color": "#111111"},
                        {"type": "text", "text": f"「{t2}」 (撮影: {a2} 様)", "size": "md", "color": "#444444", "wrap": True},
                        {"type": "button", "action": {"type": "message", "label": "👉 ここに行く", "text": f"ここに行く: {word_name}"}, "style": "primary", "color": "#1DB954", "margin": "md"}
                    ]
                }
            }
        ]
    }

def create_detail_ui(location, title, author, camera, lens, settings, weather, guide, map_url, route_url, image_url):
    return {
        "type": "bubble",
        "backgroundColor": "#ffffff",
        "hero": {"type": "image", "url": image_url, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "🌸 AIコンシェルジュ厳選提案", "weight": "bold", "color": "#1DB954", "size": "md"},
                {"type": "text", "text": location, "weight": "bold", "size": "xxl", "margin": "md", "wrap": True},
                {
                    "type": "box", "layout": "vertical", "margin": "md", "spacing": "sm",
                    "contents": [
                        {"type": "text", "text": f"作品名: {title} (撮影: {author} 様)", "wrap": True, "color": "#111111", "size": "md"},
                        {"type": "text", "text": f"推奨機材: {camera} / {lens}", "wrap": True, "color": "#111111", "size": "md"},
                        {"type": "text", "text": f"撮影設定: {settings}", "wrap": True, "color": "#111111", "size": "md"}
                    ]
                },
                {"type": "separator", "margin": "xxl"},
                {
                    "type": "box", "layout": "vertical", "margin": "xxl",
                    "contents": [
                        {"type": "text", "text": "📖 【詳細・選評・アクセス】", "weight": "bold", "size": "lg", "color": "#111111"},
                        {"type": "text", "text": guide, "wrap": True, "size": "md", "color": "#222222", "margin": "lg"}
                    ]
                },
                {"type": "separator", "margin": "xxl"},
                {
                    "type": "box", "layout": "vertical", "margin": "lg", "spacing": "sm",
                    "contents": [
                        {"type": "button", "action": {"type": "uri", "label": "🗺️ Googleマップで場所を確認", "uri": map_url}, "style": "secondary"},
                        {"type": "button", "action": {"type": "uri", "label": "🚗 東京からの高速ルートナビ", "uri": route_url}, "style": "primary", "color": "#1DB954", "margin": "sm"}
                    ]
                }
            ]
        }
    }

@app.route("/callback", methods=['POST'])
def callback():
    try:
        request_json = request.get_json()
        for event in request_json.get('events', []):
            if event.get('type') == 'message' and event['message'].get('type') == 'text': handle_line_message(event)
    except:
        print(traceback.format_exc())
    return 'OK', 200

def handle_line_message(event):
    user_id, reply_token, user_message = event['source']['userId'], event['replyToken'], event['message']['text'].strip()
    if db is None: return
    now = datetime.now()
    curr_m = now.month
    curr_d = now.day

    try:
        session_ref = db.collection('User_Sessions').document(user_id)
        session_doc = session_ref.get()

        if user_message == "やめる":
            session_ref.delete()
            line_bot_api.reply_message(reply_token, TextSendMessage(text="ご用がありましたらお声がけください。"))
            return
        if user_message == "戻る" and session_doc.exists:
            state = session_doc.to_dict()
            line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="メニュー", contents=create_ui_buttons(state.get("menu_text", ""), json.loads(state.get("menu_choices_json", "[]")))))
            return

        requested_month = None
        m_match = re.search(r'(\d+)月', user_message)
        if m_match:
            requested_month = int(m_match.group(1))

        if not session_doc.exists or any(k in user_message for k in ["明日", "おすすめ", "お勧め", "撮影"]) or requested_month:
            target_m = requested_month if requested_month else curr_m
            target_d = 15 if requested_month else curr_d
            
            if target_d <= 10: decade_str = "上旬"
            elif target_d <= 20: decade_str = "中旬"
