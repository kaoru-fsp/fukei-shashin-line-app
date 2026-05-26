import os
import json
import random
import math
import traceback
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi
from linebot.models import (
    TextSendMessage, FlexSendMessage, BubbleContainer, CarouselContainer
)
import firebase_admin
from firebase_admin import credentials, firestore
from collections import Counter

app = Flask(__name__)

# ==========================================================
# 📸 定数定義（仕様書に完全準拠・東京の現在地リファレンス）
# ==========================================================
IMAGE_BASE_VIEW = "https://fupc.photo/PicsDB/PicsDB4Search/"
TOKYO_LAT = 35.6895  # 現在地リファレンス：新宿・東京都庁周辺
TOKYO_LON = 139.6917

# --- LINE API の初期化 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

# --- Firebase / Firestore の初期化 ---
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


# --- 2点間の距離を算出するハヴェルサイン公式 ---
def calculate_distance(lat1, lon1, lat2, lon2):
    math_pi = math.pi
    rad_lat1, rad_lon1 = lat1 * math_pi / 180.0, lon1 * math_pi / 180.0
    rad_lat2, rad_lon2 = lat2 * math_pi / 180.0, lon2 * math_pi / 180.0
    d_lat = rad_lat2 - rad_lat1
    d_lon = rad_lon2 - rad_lon1
    a = math.sin(d_lat / 2) ** 2 + math.cos(rad_lat1) * math.cos(rad_lat2) * math.sin(d_lon / 2) ** 2
    return 6371.0 * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


# --- 【CSV構造厳守】撮影地名またはエリア名を安全に返すルール ---
def get_photo_place_name(pdata):
    place = str(pdata.get('Place', '')).strip()
    if place and place.lower() != 'nan': 
        return place
    area = str(pdata.get('Area', '')).strip()
    if area and area.lower() != 'nan': 
        return area
    return "厳選撮影地"


# ─── 🌸 【FUPC公式】閲覧用画像URL生成関数（タイポ完全根絶） ───
def generate_fupc_url(photo_data):
    published = str(photo_data.get('Published', '')).strip()
    pic_file_name = str(photo_data.get('PicFileName', '')).strip()
    if len(published) >= 4 and pic_file_name:
        return f"{IMAGE_BASE_VIEW.rstrip('/')}/{published[:4]}/{published}/{pic_file_name}"
    return "https://fupc.photo/PicsDB/PicsDB4Search/default.jpg"


# ─── 🛡️ 【CSV完全準拠】新フォルダ contest_data_v2 直結データ抽出エンジン ───
def get_filtered_photos(target_month, target_period, focus_keyword=None):
    # 🌟 文字化け・列ズレのない、新しく流し込んだ『contest_data_v2』を指定
    photos_ref = db.collection('contest_data_v2')
    
    # "5月" -> 5 (純粋な数値型)に変換してクエリを発行
    m_num = int(target_month.replace("月", "").strip())
    
    # 複合インデックスエラーを避けるため、Monthの数値型単一クエリで一撃ロード
    docs = photos_ref.where('Month', '==', m_num).stream()
    
    filtered_photos = []
    for doc in docs:
        pdata = doc.to_dict()
        if not pdata: continue
        
        # ─── ⚡ 【パズル解決】CSVに実在する Day（日付）から、今の上旬・中旬・下旬を自動判定 ───
        try:
            db_day = int(pdata.get('Day', 0))
            if target_period == "初旬" and not (1 <= db_day <= 10): continue
            if target_period == "中旬" and not (11 <= db_day <= 20): continue
            if target_period == "下旬" and not (21 <= db_day <= 31): continue
        except:
            continue
            
        # 必須データの存在チェック（インプレース）
        pub = pdata.get('Published')
        pic = pdata.get('PicFileName')
        if not pub or not pic: continue

        # 2往復目のキーワード指定（長野、滝など）がある場合の部分一致抽出
        if focus_keyword:
            search_pool = (
                str(pdata.get('Title', '')) + 
                str
