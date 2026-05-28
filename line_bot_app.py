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

# 💥【表記揺れ・小文字化完全破壊ゲッター】大文字小文字のバグを細胞レベルで無効化
def g(d, *keys, default=""):
    if not d: return default
    for k in keys:
        if k in d and d[k] is not None and str(d[k]).strip() not in ["", "nan", "NaN", "None", "null"]:
            return str(d[k]).strip()
    # 完全にキーが見つからない場合の、最低限のフォールバック
    if "location" in keys and ("Prefecture" in d or "prefecture" in d):
        return f"{g(d, 'Prefecture', 'prefecture')}の極上撮影地"
    return default

# 📍 半径250km圏内判定
TOKYO_250KM_PREFS = ['東京都', '神奈川県', '千葉県', '埼玉県', '茨城県', '栃木県', '群馬県', '山梨県', '長野県', '静岡県', '新潟県', '富山県', '石川県', '福井県', '岐阜県', '愛知県', '三重県', '福島県', '山形県', '宮城県']

def is_within_250km(data, lat_now=35.6812, lng_now=139.7671):
    try:
        lat_d = float(g(data, 'Latitude', 'latitude', default=0))
        lng_d = float(g(data, 'Longitude', 'longitude', default=0))
        if lat_d != 0 and lng_d != 0:
            R = 6371.0
            dlat = math.radians(lat_d - lat_now)
            dlng = math.radians(lng_d - lng_now)
            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat_now)) * math.cos(math.radians(lat_d)) * math.sin(dlng/2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            return (R * c) <= 250.0
    except: pass
    return g(data, 'Prefecture', 'prefecture') in TOKYO_250KM_PREFS

# --- 2. 状態遷移用：Flexコンポーネント生成ビルダー ---

def build_single_bubble(photo_id, item, base_url, title_text="📌 旬の厳選おすすめ撮影地"):
    loc = g(item, 'Location', 'location', 'place', 'Place', default="日本国内の絶景ポイント")
    t = g(item, 'Title', 'title', default="無題の傑作")
    a = g(item, 'Author', 'author', default="匿名写真家")
    pic_name = g(item, 'PicFileName', 'picfilename', default="default.jpg")
        
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
    t = g(data, 'Title', 'title', default="無題の傑作")
    a = g(data, 'Author', 'author', default="匿名写真家")
    camera = g(data, 'Camera_Body', 'camera_body', 'camera', default="情報なし")
    lens = g(data, 'Lens', 'lens', default="情報なし")
    aperture = g(data, 'Aperture', 'aperture', default="-")
    iso = g(data, 'ISO', 'iso', default="-")
    focal = g(data, 'Focal_Length', 'focal_length', default="-")
    
    return {
        "type": "bubble", "size": "mega",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#2c3e50", "paddingAll": "lg",
            "contents": [{"type": "text", "text": "🏆 入賞作品・機材詳細スペック", "color": "#ffffff", "weight": "bold"}]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md",
            "contents": [
                {"type": "text", "text": f"作品名：『{t}』", "weight": "bold", "size": "md"},
                {"type": "text", "text": f"撮影者：{a} 著", "size": "sm"},
                {"type": "separator"},
                {"type": "text", "text": f"■ カメラ: {camera}", "size": "sm"},
                {"type": "text", "text": f"■ レンズ: {lens}", "size": "sm"},
                {"type": "text", "text": f"■ 露出設定: F{aperture} / ISO {iso} / {focal}mm", "size": "sm"},
                {"type": "button", "action": {"type": "postback", "label": "◀ 戻る", "data": f"action=back_to_initial&id={photo_id}"}, "style": "secondary", "margin": "lg"}
            ]
        }
    }

def build_location_detail_card(photo_id, data, current_db, base_url):
    location = g(data, 'Location', 'location', 'place', 'Place', default="日本国内の絶景ポイント")
    pref = g(data, 'Prefecture', 'prefecture', default="")
    guide = g(data, 'Judge_Comment_Summary', 'judge_comment_summary', default="現地ライブラリーデータに基づき撮影計画を構築してください。")
    pic_name = g(data, 'PicFileName', 'picfilename', default="default.jpg")
    
    clean_base = base_url if base_url.endswith('/') else base_url + '/'
    img_url = f"{clean_base}static/images/{pic_name}"
    
    masterpieces = []
    try:
        ref = current_db.collection('Master_Photos')
        docs = ref.where('Prefecture', '==', pref).limit(10).stream()
        pool = [d.to_dict() for d in docs if g(d.to_dict(), 'Title', 'title') != g(data, 'Title', 'title')]
        if pool: masterpieces = random.sample(pool, min(len(pool), 3))
    except: pass

    mp_contents = []
    if masterpieces:
        for mp in masterpieces:
            mp_contents.append({"type": "text", "text": f"• 『{g(mp, 'Title', 'title')}』（{g(mp, 'Author', 'author')}）", "size": "sm", "color": "#333333", "wrap": True})
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
    
    base_url = os.environ.get('RENDER_EXTERNAL_URL', request.host_url).strip()
    if base_url.startswith("http://"):
        base_url = base_url.replace("http://", "https
