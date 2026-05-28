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

app = Flask(name)

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

def g(d, keys, default=""):
    if not d: return default
    for k in keys:
        if k in d and d[k] is not None and str(d[k]).strip() not in ["", "nan", "NaN", "None", "null"]:
            return str(d[k]).strip()
    return default

# 📍 半径250km圏内判定
TOKYO_250KM_PREFS = ['東京都', '神奈川県', '千葉県', '埼玉県', '茨城県', '栃木県', '群馬県', '山梨県', '長野県', '静岡県', '新潟県', '富山県', '石川県', '福井県', '岐阜県', '愛知県', '三重県', '福島県', '山形県', '宮城県']

def is_within_250km(data, lat_now=35.6812, lng_now=139.7671):
    try:
        lat_d = float(g(data, ['Latitude', 'latitude'], default=0))
        lng_d = float(g(data, ['Longitude', 'longitude'], default=0))
        if lat_d != 0 and lng_d != 0:
            R = 6371.0
            dlat = math.radians(lat_d - lat_now)
            dlng = math.radians(lng_d - lng_now)
            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat_now)) * math.cos(math.radians(lat_d)) * math.sin(dlng/2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            return (R * c) <= 250.0
    except: pass
    return g(data, ['Prefecture', 'prefecture']) in TOKYO_250KM_PREFS

# --- 2. 状態遷移用：Flexコンポーネント生成ビルダー ---

def build_single_bubble(photo_id, item, base_url, title_text="📌 旬の厳選おすすめ撮影地"):
    loc = g(item, ['Location', 'location', 'place', 'Place'], default="日本国内の絶景ポイント")
    t = g(item, ['Title', 'title'], default="無題の傑作")
    a = g(item, ['Author', 'author'], default="匿名写真家")
    pic_name = g(item, ['PicFileName', 'picfilename'], default="default.jpg")
        
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
    t = g(data, ['Title', 'title'], default="無題の傑作")
    a = g(data, ['Author', 'author'], default="匿名写真家")
    camera = g(data, ['Camera_Body', 'camera_body', 'camera'], default="情報なし")
    lens = g(data, ['Lens', 'lens'], default="情報なし")
    aperture = g(data, ['Aperture', 'aperture'], default="-")
    iso = g(data, ['ISO', 'iso'], default="-")
    focal = g(data, ['Focal_Length', 'focal_length'], default="-")
    
    return {
        "type": "bubble", "size": "mega",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#2c3e50", "paddingAll": "lg",
            "contents": [{"type": "text", "text": "🏆 入賞作品・機材詳細スペック", "color": "#ffffff", "weight": "bold"}]
        },
        "body":
