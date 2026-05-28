import os
import json
import random
import re
import urllib.parse
from datetime import datetime, timedelta
from flask import Flask, request
from linebot import LineBotApi
from linebot.models import TextSendMessage
import firebase_admin
from firebase_admin import credentials, firestore
from openai import OpenAI
import math

app = Flask(__name__)

# --- 1. API初期化 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ai_client = OpenAI(api_key=OPENAI_API_KEY)

db = None
def get_db():
    global db
    if db is not None: return db
    try:
        firebase_creds_json = os.environ.get('FIREBASE_CREDENTIALS')
        if firebase_creds_json:
            cred = credentials.Certificate(json.loads(firebase_creds_json))
            try: firebase_admin.initialize_app(cred)
            except ValueError: pass
            db = firestore.client()
            return db
    except Exception as e: print(f"Firebase Error: {e}", flush=True)
    return None

get_db()

class GachiFlexMessage:
    def __init__(self, alt_text, contents_dict):
        self.type = "flex"
        self.alt_text = alt_text
        self.contents = contents_dict
    def as_json_dict(self):
        return {"type": "flex", "altText": self.alt_text, "contents": self.contents}

# 📍 半径250km圏内判定
TOKYO_250KM_PREFS = ['東京都', '神奈川県', '千葉県', '埼玉県', '茨城県', '栃木県', '群馬県', '山梨県', '長野県', '静岡県', '新潟県', '富山県', '石川県', '福井県', '岐阜県', '愛知県', '三重県', '福島県', '山形県', '宮城県']

def is_within_250km(data, lat_now=35.6812, lng_now=139.7671):
    try:
        lat_d = float(data.get('Latitude', 0))
        lng_d = float(data.get('Longitude', 0))
        if lat_d != 0 and lng_d != 0:
            R = 6371.0
            dlat = math.radians(lat_d - lat_now)
            dlng = math.radians(lng_d - lng_now)
            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat_now)) * math.cos(math.radians(lat_d)) * math.sin(dlng/2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            return (R * c) <= 250.0
    except: pass
    return data.get('Prefecture', '') in TOKYO_250KM_PREFS

# --- 2. 状態遷移用：Flexコンポーネント生成ビルダー ---

def build_single_bubble(photo_id, item, base_url, title_text="📌 旬の厳選おすすめ撮影地"):
    loc = item.get('Location', 'おすすめ撮影地')
    t = item.get('Title', '作品名')
    a = item.get('Author', '著者')
    pic_name = item.get('PicFileName', '').strip()
    
    if not pic_name or pic_name.lower() in ['nan', 'none', '']:
        pic_name = "default.jpg"
        
    clean_base = base_url if base_url.endswith('/') else base_url + '/'
    img_url = f"{clean_base}static/images/{pic_name}"
    
    return {
        "type": "bubble",
        "size": "mega",
        "hero": {
            "type": "image",
            "url": img_url,
            "size": "full",
            "aspectRatio": "16:10",
            "aspectMode": "cover",
            "action": {"type": "postback", "data": f"action=artwork_info&id={photo_id}"}
        },
        "body": {
            "type": "box", "layout": "vertical", "paddingAll": "xl", "backgroundColor": "#fafafa",
            "contents": [
                {"type": "text", "text": title_text, "size": "xs", "color": "#e74c3c", "weight": "bold"},
                {"type": "text", "text": loc, "weight": "bold", "size": "xl", "margin": "xs", "wrap": True, "color": "#111111"},
                {"type": "text", "text": f"参考作品：『{t}』（{a} 著）", "size": "sm", "color": "#555555", "wrap": True, "margin": "xs"},
                {
                    "type": "button",
                    "action": {"type": "postback", "label": "🔍 ここを詳しく (トチカン攻略)", "data": f"action=location_detail&id={photo_id}"},
                    "style": "primary", "color": "#1f3c3d", "margin": "md"
                }
            ]
        }
    }

def build_artwork_info_card(photo_id, data):
    title = data.get('Title', '無題')
    author = data.get('Author', 'ライブラリー記録')
    camera = data.get('Camera_Body', '情報なし')
    lens = data.get('Lens', '情報なし')
    aperture = data.get('Aperture', '-')
    iso = data.get('ISO', '-')
    focal = data.get('Focal_Length', '-')
    
    return {
        "type": "bubble", "size": "mega",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#2c3e50", "paddingAll": "lg",
            "contents": [{"type": "text", "text": "🏆 入賞作品・機材詳細スペック", "color": "#ffffff", "weight": "bold"}]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md",
            "contents": [
                {"type": "text", "text": f"作品名：『{title}』", "weight": "bold", "size": "md"},
                {"type": "text", "text": f"撮影者：{author} 著", "size": "sm"},
                {"type": "separator"},
                {"type": "text", "text": f"■ カメラ: {camera}", "size": "sm"},
                {"type": "text", "text": f"■ レンズ: {lens}", "size": "sm"},
                {"type": "text", "text": f"■ 露出設定: F{aperture} / ISO {iso} / {focal}mm", "size": "sm"},
                {"type": "button", "action": {"type": "postback", "label": "◀ 戻る", "data": f"action=back_to_initial&id={photo_id}"}, "style": "secondary", "margin": "lg"}
            ]
        }
    }

def build_location_detail_card(photo_id, data, current_db, base_url):
    location = data.get('Location', '日本国内の撮影地')
    pref = data.get('Prefecture', '')
    guide = data.get('Judge_Comment_Summary', '現地ライブラリーデータに基づき撮影計画を構築してください。')
    pic_name = data.get('PicFileName', '').strip()
    if not pic_name or pic_name.lower() in ['nan', 'none', '']: pic_name = "default.jpg"
    
    clean_base = base_url if base_url.endswith('/') else base_url + '/'
    img_url = f"{clean_base}static/images/{pic_name}"
    
    masterpieces = []
    try:
        ref = current_db.collection('Master_Photos')
        docs = ref.where('Prefecture', '==', pref).limit(10).stream()
        pool = [d.to_dict() for d in docs if d.to_dict().get('Title') != data.get('Title')]
        if pool: masterpieces = random.sample(pool, min(len(pool), 3))
    except: pass

    mp_contents = []
    if masterpieces:
        for mp in masterpieces:
            mp_contents.append({"type": "text", "text": f"• 『{mp.get('Title','無題')}』（{mp.get('Author','')}）", "size": "sm", "color": "#333333", "wrap": True})
    else:
        mp_contents.append({"type": "text", "text": "• 周辺の過去入賞記録を照会中", "size": "sm", "color": "#777777"})

    safe_info = "適切な防寒・装備を推奨。周辺の野生動物や安全管理に留意してください。"
    if any(k in location for k in ["山", "森", "高原", "霧ヶ峰", "渓谷"]):
        safe_info = "⚠️【重要】山林・熊生息エリア：熊鈴・熊スプレーを必ず携行し、単独行動を避けてください。足元のトレッキングシューズ等も必須です。"

    return {
        "type": "bubble", "size": "mega",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#1f3c3d", "paddingAll": "lg",
            "contents": [{"type": "text", "text": f"🗺️ 撮影地攻略：{location}", "color": "#ffffff", "weight": "bold", "size": "md"}]
        },
        "hero": {
            "type": "image", "url": img_url, "size": "full", "aspectRatio": "16:10", "aspectMode": "cover"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {"type": "text", "text": "🔷 【トチカン】地域密着撮影知見", "weight": "bold", "size": "sm", "color": "#1f3c3d"},
                {"type": "text", "text": guide, "size": "md", "wrap": True, "color": "#222222"},
                {"type": "separator", "margin": "md"},
                
                {"type": "text", "text": "🔶 【セーフガイド】安全・装備情報", "weight": "bold", "size": "sm", "color": "#c0392b"},
                {"type": "text", "text": safe_info, "size": "sm", "wrap": True, "color": "#444444"},
                {"type": "separator", "margin": "md"},
                
                {"type": "text", "text": f"🏆 同地域における {pref}傑作選（3選）", "weight": "bold", "size": "sm", "color": "#d35400"},
                {"type": "box", "layout": "vertical", "spacing": "xs", "contents": mp_contents},
                {"type": "separator", "margin": "md"},
                
                {"type": "text", "text": "🌐 リアルタイム撮影インフラリンク", "weight": "bold", "size": "sm", "color": "#2980b9"},
                {
                    "type": "box", "layout": "horizontal", "spacing": "sm",
                    "contents": [
                        {"type": "button", "action": {"type": "uri", "label": "🗺️ Map", "uri": f"https://www.google.com/maps/search/?api=1&query={location}"}, "style": "link", "size": "sm"},
                        {"type": "button", "action": {"type": "uri", "label": "⏱️ ルート(時間表示)", "uri": f"https://www.google.com/maps/dir/?api=1&destination={location}"}, "style": "link", "size": "sm"},
                        {"type": "button", "action": {"type": "uri", "label": "☀️ 天気・天文・潮汐", "uri": "https://www.jma.go.jp/"}, "style": "link", "size": "sm"}
                    ]
                },
                {"type": "separator", "margin": "md"},
                
                {
                    "type": "box", "layout": "horizontal", "spacing": "sm",
                    "contents": [
                        {"type": "button", "action": {"type": "postback", "label": "◀ 戻る", "data": f"action=back_to_initial&id={photo_id}"}, "style": "secondary", "size": "sm"},
                        {"type": "button", "action": {"type": "postback", "label": "🚗 ここから移動(2h)", "data": f"action=move_2h&id={photo_id}"}, "style": "primary", "color": "#2c3e50", "size": "sm"},
                        {"type": "button", "action": {"type": "postback", "label": "💾 ルートを記録", "data": f"action=record_route&id={photo_id}"}, "style": "primary", "color": "#27ae60", "size": "sm"}
                    ]
                }
            ]
        }
    }

def build_carousel_suggestions(suggestions, base_url, title_text="🚗 2時間圏内の周辺候補地"):
    bubbles = []
    for idx, (d_id, item) in enumerate(suggestions[:3]):
        bubbles.append(build_single_bubble(d_id, item, base_url, title_text))
    return {"type": "carousel", "contents": bubbles}

# --- 3. イベントハンドラー ---

@app.route("/callback", methods=['POST'])
def callback():
    try:
        request_json = request.get_json()
        events = request_json.get('events', [])
        for event in events:
            if event.get('type') == 'message' and event['message'].get('type') == 'text':
                handle_line_message(event)
            elif event.get('type') == 'postback':
                handle_line_postback(event)
    except Exception as e: print(f"Root Callback Error: {e}", flush=True)
    return 'OK', 200

def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    current_db = get_db()
    if current_db is None: return

    base_url = request.host_url
    base_date = datetime.now() + timedelta(days=1)
    
    parsed_periods = []
    for i in range(-5, 11):
        d = base_date + timedelta(days=i)
        m = d.month
        day = d.day
        p = "上旬" if day <= 10 else "中旬" if day <= 20 else "下旬"
        parsed_periods.append((m, p))
    parsed_periods = list(set(parsed_periods))

    intent_pref = ""
    intent_keyword = "朝焼け"
    try:
        intent_response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": "地域名とキーワード抽出"}, {"role": "user", "content": user_message}],
            temperature=0.1
        )
        intent = json.loads(intent_response.choices[0].message.content)
        pref_val = intent.get("target_pref", "")
        intent_pref = str(pref_val).strip() if pref_val else ""
        kw_val = intent.get("keyword", "朝焼け")
        intent_keyword = str(kw_val).strip() if kw_val else "朝焼け"
    except: pass

    ref = current_db.collection('Master_Photos')
    precise_seasonal_pool = []
    
    # ⚡️【Firestoreインデックスエラーの完全撲滅】
    # 複数whereによるIndexRequiredエラーを防ぐため、自動索引のあるMonth単体で取得し、PeriodはPython側で超高速安全にフィルタリング！
    try:
        for m_val, p_val in parsed_periods:
            for m_str in [str(m_val), f"{m_val:02d}"]:
                docs = ref.where('Month', '==', m_str).stream()
                for doc in docs:
                    d = doc.to_dict()
                    if str(d.get('Period', '')).strip() == p_val:
                        precise_seasonal_pool.append((doc.id, d))
    except Exception as e: print(f"Firestore Snipe Error: {e}", flush=True)

    main_pool = []
    radius_pool = []

    for d_id, d in precise_seasonal_pool:
        if is_within_250km(d): radius_pool.append((d_id, d))
        if intent_pref and d.get('Prefecture', '') == intent_pref: main_pool.append((d_id, d))

    if not intent_pref: main_pool = list(radius_pool)

    def score_item(item_tuple):
        _, d = item_tuple
        return 1 if intent_keyword in str(d.get('Subject','')) + str(d.get('Location','')) + str(d.get('Title','')) else 0

    main_pool.sort(key=score_item, reverse=True)
    radius_pool.sort(key=score_item, reverse=True)

    if not main_pool: main_pool = list(radius_pool)
    if not main_pool:
        rand_ref = ref.order_by('__name__').start_at([f"photo_{random.randint(0, 14000)}"]).limit(3).stream()
        main_pool = [(doc.id, doc.to_dict()) for doc in rand_ref]

    carousel_bubbles = []
    for d_id, item in main_pool[:3]:
        carousel_bubbles.append(build_single_bubble(d_id, item, base_url))

    msg_carousel = GachiFlexMessage(
        alt_text="今が旬のおすすめ撮影地3選",
        contents_dict={"type": "carousel", "contents": carousel_bubbles}
    )

    # ⚡️【NoneTypeエラーの完全防殺】
    weather_val = main_pool[0][1].get('Weather', '')
    weather = str(weather_val).strip() if weather_val else ""
    weather_phrase = "明日はお天気もいいようですから" if not weather or weather.lower() in ["nan", "none", "不明", ""] else f"明日はお天気も{weather}のようですから"

    if intent_pref:
        greeting = f"ようこそ『風景写真』コンシェルジュの部屋へ。明日の撮影に向けて『{intent_pref}』でお探しですね。現地を狙い撃ちした知見データから、今の季節に最も素晴らしい表情を見せてくれるおすすめのポイントを厳選いたしました。"
    else:
        greeting = f"ようこそ『風景写真』コンシェルジュの部屋へ。明日（{base_date.strftime('%m/%d')}）撮影にお出かけですか。{weather_phrase}撮影を楽しめそうですね。今の季節にまさに『旬』を迎えているおすすめのポイントをご案内いたします。スクロールして気になる場所をお選びください。"

    msg_text = TextSendMessage(text=greeting)

    try: line_bot_api.reply_message(reply_token, [msg_text, msg_carousel])
    except Exception as e: print(f"LINE Message Send Error: {e}", flush=True)


def handle_line_postback(event):
    reply_token = event['replyToken']
    postback_data = event['postback']['data']
    current_db = get_db()
    if current_db is None: return
    
    base_url = request.host_url
    params = dict(urllib.parse.parse_qsl(postback_data))
    action = params.get('action')
    photo_id = params.get('id', 'photo_0')
    clean_db_id = photo_id.split('_')[-1] if 'move' in photo_id else photo_id
    if not clean_db_id.startswith('photo_'): clean_db_id = f"photo_{clean_db_id}"

    try:
        doc_ref = current_db.collection('Master_Photos').document(clean_db_id).get()
        data = doc_ref.to_dict() if doc_ref.exists else {}
    except: data = {}

    if not data: return

    if action == "artwork_info":
        msg = GachiFlexMessage(alt_text="入賞作品詳細情報", contents_dict=build_artwork_info_card(photo_id, data))
        line_bot_api.reply_message(reply_token, msg)
    elif action == "back_to_initial":
        msg = GachiFlexMessage(alt_text="撮影地ナビゲーション", contents_dict=build_single_bubble(clean_db_id, data, base_url))
        line_bot_api.reply_message(reply_token, msg)
    elif action == "location_detail":
        concierge_comment = "該当ポイントの攻略知見を展開します。"
        msg_text = TextSendMessage(text=concierge_comment)
        msg_detail = GachiFlexMessage(alt_text="撮影地攻略詳細知見", contents_dict=build_location_detail_card(clean_db_id, data, current_db, base_url))
        line_bot_api.reply_message(reply_token, [msg_text, msg_detail])
    elif action == "move_2h":
        ref = current_db.collection('Master_Photos')
        near_photos = []
        try:
            docs = ref.where('Prefecture', '==', data.get('Prefecture','')).limit(10).stream()
            near_photos = [(doc.id, doc.to_dict()) for doc in docs if doc.id != clean_db_id]
        except: pass
        if not near_photos: near_photos = [(clean_db_id, data)]
        msg = GachiFlexMessage(alt_text="2時間圏内の周辺候補地", contents_dict=build_carousel_suggestions(near_photos, base_url))
        line_bot_api.reply_message(reply_token, msg)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
