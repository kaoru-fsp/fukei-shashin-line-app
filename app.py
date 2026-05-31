# -*- coding: utf-8 -*-
"""
風景写真コンシェルジュ 完全版 v2
仕様書に完全準拠。3分類選定×乱数×除外2系統×LINE Flex カルーセル×postback
"""
import os
import json
import sys
import re
import math
import random
from datetime import date, timedelta
from collections import defaultdict, Counter
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, LocationMessage, PostbackEvent, TextSendMessage, FlexSendMessage
from linebot.exceptions import InvalidSignatureError
import unicodedata
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

# ──────────────── LINE API 初期化 ────────────────
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ──────────────── Firestore 初期化 ────────────────
db = None
try:
    firebase_creds_json = os.environ.get('FIREBASE_CREDENTIALS')
    if firebase_creds_json:
        creds_dict = json.loads(firebase_creds_json)
        cred = credentials.Certificate(creds_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("[INFO] Firestore initialized.")
except Exception as e:
    print(f"[ERROR] Firestore initialization failed: {e}")

# ──────────────── 心臓部ユーティリティ ────────────────
PREF_LATLNG = {
    "北海道":(43.06,141.35),"青森県":(40.82,140.74),"岩手県":(39.70,141.15),"宮城県":(38.27,140.87),
    "秋田県":(39.72,140.10),"山形県":(38.24,140.36),"福島県":(37.75,140.47),"茨城県":(36.34,140.45),
    "栃木県":(36.57,139.88),"群馬県":(36.39,139.06),"埼玉県":(35.86,139.65),"千葉県":(35.60,140.12),
    "東京都":(35.69,139.69),"神奈川県":(35.45,139.64),"新潟県":(37.90,139.02),"富山県":(36.70,137.21),
    "石川県":(36.59,136.63),"福井県":(36.07,136.22),"山梨県":(35.66,138.57),"長野県":(36.65,138.18),
    "岐阜県":(35.39,136.72),"静岡県":(34.98,138.38),"愛知県":(35.18,136.91),"三重県":(34.73,136.51),
    "滋賀県":(35.00,135.87),"京都府":(35.02,135.76),"大阪府":(34.69,135.52),"兵庫県":(34.69,135.18),
    "奈良県":(34.69,135.83),"和歌山県":(34.23,135.17),"鳥取県":(35.50,134.24),"島根県":(35.47,133.05),
    "岡山県":(34.66,133.93),"広島県":(34.40,132.46),"山口県":(34.19,131.47),"徳島県":(34.07,134.56),
    "香川県":(34.34,134.04),"愛媛県":(33.84,132.77),"高知県":(33.56,133.53),"福岡県":(33.61,130.42),
    "佐賀県":(33.25,130.30),"長崎県":(32.74,129.87),"熊本県":(32.79,130.74),"大分県":(33.24,131.61),
    "宮崎県":(31.91,131.42),"鹿児島県":(31.56,130.56),"沖縄県":(26.21,127.68),
}
GHOST_PREF = {"山内県":"山口県","京都県":"京都府","青山県":"青森県","三重御県":"三重県","金沢県":"神奈川県"}
CITY_PREF = {"京都市":"京都府","南丹市":"京都府","鹿児島":"鹿児島県"}
PREF_RE = re.compile(r'^(北海道|東京都|京都府|大阪府|.{2,3}県)')

AWARD_SCORE = {'最優秀作品賞':100, '優秀作品賞':80, '入選':40, '佳作':30}
SERVER_BASE = "https://fupc.photo/PicsDB"
VIEW_DIR = "PicsDB4Search"

def extract_pref(area):
    if not area:
        return None
    a = str(area).strip()
    for ghost in sorted(GHOST_PREF, key=len, reverse=True):
        if a.startswith(ghost):
            return GHOST_PREF[ghost]
    m = PREF_RE.match(a)
    if m and m.group(1) in PREF_LATLNG:
        return m.group(1)
    for city, pref in CITY_PREF.items():
        if a.startswith(city):
            return pref
    return None

def junkun(day):
    try:
        d = int(day)
    except:
        return None
    if d <= 10:
        return "上旬"
    if d <= 20:
        return "中旬"
    return "下旬"

def haversine(lat1, lng1, lat2, lng2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    h = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlmb/2)**2
    return 2 * R * math.asin(math.sqrt(h))

def half_month_window(base_date):
    pairs = set()
    for delta in range(-7, 14):
        d = base_date + timedelta(days=delta)
        pairs.add((d.month, junkun(d.day)))
    return pairs

def view_image_url(published, pic_filename):
    return "/".join([SERVER_BASE, VIEW_DIR, str(published)[:4], str(published), str(pic_filename)])

def has_valid_image(pic_filename):
    fn = str(pic_filename or '').strip()
    return fn and fn not in ('なし.jpg', 'default.jpg', 'なし', 'none', '')

def calc_award_score(award_rank):
    r = str(award_rank or '').strip()
    for k, v in AWARD_SCORE.items():
        if k in r:
            return v
    return 10 if r else 0

def load_exclusions():
    authors = set()
    blocked = []
    today = date.today().isoformat()
    try:
        doc = db.collection('settings').document('excluded_authors').get()
        if doc.exists:
            authors = set(doc.to_dict().get('names', []))
    except:
        pass
    try:
        doc = db.collection('settings').document('blocked_areas').get()
        if doc.exists:
            for item in doc.to_dict().get('items', []):
                if item.get('until', '9999') >= today:
                    blocked.append(item.get('match', ''))
    except:
        pass
    return authors, [b for b in blocked if b]

def is_area_blocked(place, area, blocked_list):
    if not blocked_list:
        return False
    s = str(place or '') + ' ' + str(area or '')
    return any(b and b in s for b in blocked_list)



# ──────────────── Google Geocoding API ────────────────
GEOCODING_API_KEY = os.environ.get('GOOGLE_GEOCODING_API_KEY')
GEOCODE_CACHE = {}

def geocode(place_name):
    if place_name in GEOCODE_CACHE:
        return GEOCODE_CACHE[place_name]
    if not GEOCODING_API_KEY:
        return None
    try:
        import urllib.request
        from urllib.parse import quote
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={quote(place_name)}&language=ja&key={GEOCODING_API_KEY}"
        with urllib.request.urlopen(url, timeout=3) as res:
            data = json.loads(res.read())
        if data['status'] == 'OK':
            loc = data['results'][0]['geometry']['location']
            result = (loc['lat'], loc['lng'])
            GEOCODE_CACHE[place_name] = result
            return result
    except Exception as e:
        print(f"[WARN] Geocoding failed for {place_name}: {e}")
    return None

# ──────────────── メッセージ解析 ────────────────
CITY_TO_PREF = {}
CITY_TO_LATLNG = {}
CITY_TO_PREF_MULTI = {}
AMBIGUOUS_PENDING = {}  # user_id -> {"city": "小国町", "prefs": ["熊本県", "山形県"]}
USER_LOCATION = {}  # user_id -> {"lat": 35.xxx, "lng": 139.xxx}
WIDE_PREFS = {"北海道", "長野県", "岩手県", "新潟県"}
PREF_CITY = {
    "北海道":"札幌","青森県":"青森市","岩手県":"盛岡市","宮城県":"仙台市",
    "秋田県":"秋田市","山形県":"山形市","福島県":"福島市","茨城県":"水戸市",
    "栃木県":"宇都宮市","群馬県":"前橋市","埼玉県":"さいたま市","千葉県":"千葉市",
    "東京都":"新宿","神奈川県":"横浜市","新潟県":"新潟市","富山県":"富山市",
    "石川県":"金沢市","福井県":"福井市","山梨県":"甲府市","長野県":"長野市",
    "岐阜県":"岐阜市","静岡県":"静岡市","愛知県":"名古屋市","三重県":"津市",
    "滋賀県":"大津市","京都府":"京都市","大阪府":"大阪市","兵庫県":"神戸市",
    "奈良県":"奈良市","和歌山県":"和歌山市","鳥取県":"鳥取市","島根県":"松江市",
    "岡山県":"岡山市","広島県":"広島市","山口県":"山口市","徳島県":"徳島市",
    "香川県":"高松市","愛媛県":"松山市","高知県":"高知市","福岡県":"福岡市",
    "佐賀県":"佐賀市","長崎県":"長崎市","熊本県":"熊本市","大分県":"大分市",
    "宮崎県":"宮崎市","鹿児島県":"鹿児島市","沖縄県":"那覇市",
}


def parse_target_date(text):
    today = date.today()
    if "明日" in text or "あした" in text:
        return today + timedelta(days=1)
    if "明後日" in text or "あさって" in text:
        return today + timedelta(days=2)
    m = re.search(r'(\d+)日後', text)
    if m:
        return today + timedelta(days=int(m.group(1)))
    m = re.search(r'(\d{1,2})月(\d{1,2})日', text)
    if m:
        mo, dy = int(m.group(1)), int(m.group(2))
        try:
            target = date(today.year, mo, dy)
            if target < today:
                target = date(today.year + 1, mo, dy)
            return target
        except:
            pass
    if "来週末" in text:
        days_ahead = 5 - today.weekday() + 7
        return today + timedelta(days=days_ahead)
    if "来週" in text:
        return today + timedelta(days=7)
    if "今週末" in text or "週末" in text:
        days_ahead = 5 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return today + timedelta(days=days_ahead)
    return today + timedelta(days=1)

def parse_target_area(text):
    for pref in PREF_LATLNG:
        if pref == "北海道":
            short = "北海道"
        else:
            short = pref.replace("都","").replace("府","").replace("県","")
        if pref in text or short in text:
            import sys; print(f"[DEBUG2] pref_match: pref={pref}, short={short}, text={text}", file=sys.stdout, flush=True)
            return pref, PREF_LATLNG[pref], PREF_CITY.get(pref, pref)
    for city, pref in CITY_PREF.items():
        if city in text:
            return pref, PREF_LATLNG[pref], city
    for city, pref in CITY_TO_PREF.items():
        # 「美瑛」→「美瑛町」のような前方一致も拾う
        city_base = re.sub(r'[市区町村郡]', '', city).strip()
        if city in text:
            if city in CITY_TO_PREF_MULTI:
                return "AMBIGUOUS", None, city
            latlng = geocode(city) or CITY_TO_LATLNG.get(city, PREF_LATLNG[pref])
            matched_name = city_base if city_base in text else city
            return pref, latlng, matched_name
    for city in CITY_TO_PREF_MULTI:
        city_base = re.sub(r'[市区町村郡]', '', city).strip()
        if city in text or (len(city_base) >= 2 and city_base in text):
            return "AMBIGUOUS", None, city
    EXCLUDE_WORDS = {'撮影', '明日', '今日', '明後日', '写真', '行きたい', '探して', '教えて', 'したい', 'ください'}
        words = [w for w in re.split(r'[\s、。！？!?]+', text) if len(w) >= 2 and w not in EXCLUDE_WORDS]
    for word in words:
        latlng = geocode(word + ' 日本')
    return None, None, None
def format_date_jp(d):
    weekdays = ["月","火","水","木","金","土","日"]
    return f"{d.month}月{d.day}日（{weekdays[d.weekday()]}）"

def build_greeting(target_date, area_name):
    today = date.today()
    delta = (target_date - today).days
    if delta == 1:
        date_str = f"明日（{format_date_jp(target_date)}）"
    elif delta == 2:
        date_str = f"明後日（{format_date_jp(target_date)}）"
    elif 3 <= delta <= 14:
        date_str = f"{delta}日後（{format_date_jp(target_date)}）"
    else:
        date_str = format_date_jp(target_date)
    area_str = f"{area_name}に" if area_name else ""
    return (
        f"ようこそ風景写真コンシェルジュの部屋へ。"
        f"{date_str}に{area_str}撮影にお出かけですか。"
        f"それでしたらこんなところはいかがでしょう。"
    )

# ──────────────── 3分類選定エンジン ────────────────
def select_three_points(base_date=None, base_latlng=None, radius=None, place_name=None):
    with open('/tmp/debug.log', 'a') as f:
        f.write("[DEBUG] select_three_points: start\n")

    if not db:
        with open('/tmp/debug.log', 'a') as f:
            f.write("[DEBUG] select_three_points: db is None\n")
        return None, None, None

    try:
        excl_authors, blocked_areas = load_exclusions()
        tomorrow = base_date if base_date else date.today() + timedelta(days=1)
        junkun_window = half_month_window(tomorrow)
        tokyo = base_latlng if base_latlng else PREF_LATLNG["東京都"]
        _radius = radius if radius else (150 if base_latlng else 250)
        if base_latlng:
            base_name = place_name if place_name else (PREF_CITY.get(next((k for k,v in PREF_LATLNG.items() if v == base_latlng), None), "指定地"))
        else:
            base_name = "新宿区"

        pool = []
        place_years = defaultdict(list)

        with open('/tmp/debug.log', 'a') as f:
            f.write("[DEBUG] select_three_points: starting Firestore stream\n")

        for doc in db.collection('Master_Photos').stream():
            d = doc.to_dict()

            try:
                mo = int(d.get('Month'))
            except:
                continue
            if (mo, junkun(d.get('Day'))) not in junkun_window:
                continue

            pref = extract_pref(d.get('Area'))
            if not pref:
                continue
            lat, lng = PREF_LATLNG[pref]
            dist = haversine(tokyo[0], tokyo[1], lat, lng)
            if dist > _radius:
                continue

            if d.get('Winner') in excl_authors:
                continue
            if is_area_blocked(d.get('Place'), d.get('Area'), blocked_areas):
                continue
            if not has_valid_image(d.get('PicFileName')):
                continue

            item = {
                'dist': dist,
                'pref': pref,
                'area': d.get('Area', ''),
                'place': d.get('Place', ''),
                'title': d.get('Title', ''),
                'winner': d.get('Winner', ''),
                'award': d.get('AwardRank', ''),
                'ascore': calc_award_score(d.get('AwardRank')),
                'pic': d.get('PicFileName', ''),
                'pub': d.get('Published', ''),
                'url': view_image_url(d.get('Published', ''), d.get('PicFileName', '')),
                'base_name': base_name,
            'maplink': d.get('MapLink', ''),
            }
            pool.append(item)

            try:
                place_years[d.get('Area', '')].append(int(d.get('Year')))
            except:
                pass

        with open('/tmp/debug.log', 'a') as f:
            f.write(f"[DEBUG] select_three_points: pool size={len(pool)}\n")

        # 地域指定時にpoolが空の場合、旬ウィンドウを前後1ヶ月に広げてリトライ
        if not pool and base_latlng:
            with open('/tmp/debug.log', 'a') as f:
                f.write("[DEBUG] pool empty, retrying with wider window\n")
            wider_window = set()
            for delta in range(-30, 31):
                d2 = tomorrow + timedelta(days=delta)
                wider_window.add((d2.month, junkun(d2.day)))
            for doc in db.collection('Master_Photos').stream():
                d = doc.to_dict()
                try:
                    mo = int(d.get('Month'))
                except:
                    continue
                if (mo, junkun(d.get('Day'))) not in wider_window:
                    continue
                pref = extract_pref(d.get('Area'))
                if not pref:
                    continue
                lat, lng = PREF_LATLNG[pref]
                dist = haversine(tokyo[0], tokyo[1], lat, lng)
                if dist > _radius:
                    continue
                if d.get('Winner') in excl_authors:
                    continue
                if is_area_blocked(d.get('Place'), d.get('Area'), blocked_areas):
                    continue
                if not has_valid_image(d.get('PicFileName')):
                    continue
                item = {
                    'dist': dist,
                    'pref': pref,
                    'area': d.get('Area', ''),
                    'place': d.get('Place', '') or '',
                    'title': d.get('Title', ''),
                    'winner': d.get('Winner', ''),
                    'award': d.get('AwardRank', ''),
                    'ascore': calc_award_score(d.get('AwardRank')),
                    'pic': d.get('PicFileName', ''),
                    'pub': d.get('Published', ''),
                    'url': view_image_url(d.get('Published', ''), d.get('PicFileName', '')),
                    'base_name': base_name,
                    'maplink': d.get('MapLink', ''),
                }
                pool.append(item)
                try:
                    place_years[d.get('Area', '')].append(int(d.get('Year')))
                except:
                    pass
            with open('/tmp/debug.log', 'a') as f:
                f.write(f"[DEBUG] wider window pool size={len(pool)}\n")

        if not pool:
            with open('/tmp/debug.log', 'a') as f:
                f.write("[DEBUG] select_three_points: pool is empty\n")
            return None, None, None

        top_pool = sorted(pool, key=lambda x: (-x['ascore'], x['dist']))[:max(8, len(pool)//10)]
        masterpiece = random.choice(top_pool)

        near_pool = sorted(pool, key=lambda x: x['dist'])[:max(8, len(pool)//8)]
        near_cand = [p for p in near_pool if p['pref'] != masterpiece['pref']] or near_pool
        near = random.choice(near_cand)

        recent_cutoff = date.today().year - 5
        attention_score = {
            a: sum(1 for y in ys if y >= recent_cutoff)
            for a, ys in place_years.items()
        }
        hot_pool = sorted(
            pool,
            key=lambda x: (-attention_score.get(x['area'], 0), x['dist'])
        )
        used_prefs = {masterpiece['pref'], near['pref']}
        used_pics = {masterpiece['pic'], near['pic']}
        hot_cand = [p for p in hot_pool if p['pref'] not in used_prefs and p['pic'] not in used_pics] or                    [p for p in hot_pool if p['pic'] not in used_pics] or hot_pool
        hot_cand = hot_cand[:max(8, len(hot_pool)//10)]
        attention = random.choice(hot_cand) if hot_cand else None

        with open('/tmp/debug.log', 'a') as f:
            f.write(f"[DEBUG] select_three_points: done. masterpiece={masterpiece.get('title')}, near={near.get('title')}\n")
            f.write(f"[DEBUG] dist: masterpiece={masterpiece.get('dist')}, base_name={masterpiece.get('base_name')}\n")

        return masterpiece, near, attention

    except Exception as e:
        import traceback
        with open('/tmp/debug.log', 'a') as f:
            f.write(f"[ERROR] select_three_points exception: {traceback.format_exc()}\n")
        return None, None, None

# ──────────────── Flex Message 組み立て ────────────────
def build_carousel_bubble(item, label_emoji, area_note=""):
    place = item.get('place', '')
    area = item.get('area', '')
    location_contents = []
    if place:
        location_contents.append({
            "type": "text",
            "text": place,
            "weight": "bold",
            "size": "xl",
            "wrap": True,
            "color": "#111111"
        })
        if area:
            location_contents.append({
                "type": "text",
                "text": area,
                "size": "sm",
                "color": "#666666",
                "margin": "xs"
            })
    else:
        if area:
            location_contents.append({
                "type": "text",
                "text": area,
                "weight": "bold",
                "size": "xl",
                "wrap": True,
                "color": "#111111"
            })

    from urllib.parse import quote
    map_uri = f"https://maps.google.com/maps?q={quote(area)}" if area else "https://maps.google.com/"

    bubble = {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": item['url'],
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": f"{label_emoji} {area_note}",
                    "weight": "bold",
                    "size": "md",
                    "color": "#666666"
                },
            ] + location_contents + [
                {
                    "type": "text",
                    "text": item['title'],
                    "size": "sm",
                    "margin": "sm",
                    "wrap": True,
                    "color": "#444444"
                },
                {
                    "type": "text",
                    "text": f"{item['winner']}  ({item['award'] or '記録'})",
                    "size": "sm",
                    "color": "#666666",
                    "margin": "xs"
                },
                {
                    "type": "text",
                    "text": (f"{item['base_name']}より {item['dist']:.0f}km" if item['dist'] >= 5 else f"{item['base_name']}周辺"),
                    "size": "sm",
                    "color": "#999999",
                    "margin": "sm"
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "horizontal",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "action": {
                        "type": "uri",
                        "label": "マップ",
                        "uri": map_uri
                    }
                }
            ]
        }
    }
    return bubble

def build_city_to_pref():
    global CITY_TO_PREF
    if not db:
        return
    try:
        import re as _re
        from collections import defaultdict as _dd
        pref_map = _dd(set)
        for doc in db.collection('Master_Photos').stream():
            area = doc.to_dict().get('Area', '')
            pref = extract_pref(area)
            if not pref or not area:
                continue
            city_part = area.replace(pref, '').strip()
            if city_part:
                m = _re.match(r'(.+?[市区町村])', city_part)
                if m:
                    pref_map[m.group(1)].add(pref)
                    CITY_TO_LATLNG[m.group(1)] = PREF_LATLNG[pref]
                parts = _re.findall(r'[^\s]{2,}', city_part)
                for part in parts:
                    if len(part) >= 2:
                        pref_map[part].add(pref)
                        CITY_TO_LATLNG[part] = PREF_LATLNG[pref]
        for city, prefs in pref_map.items():
            if len(prefs) == 1:
                CITY_TO_PREF[city] = next(iter(prefs))
            else:
                CITY_TO_PREF_MULTI[city] = list(prefs)
        print(f'[INFO] CITY_TO_PREF構築完了: {len(CITY_TO_PREF)}件, 同名地名: {len(CITY_TO_PREF_MULTI)}件')
    except Exception as e:
        print(f'[WARN] CITY_TO_PREF構築失敗: {e}')

build_city_to_pref()

# ──────────────── LINE Webhook ────────────────
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("[WARN] Invalid signature.")
        abort(400)
    except Exception as e:
        print(f"[ERROR] Webhook error: {e}")

    return 'OK', 200

@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):
    user_id = event.source.user_id
    lat = event.message.latitude
    lng = event.message.longitude
    USER_LOCATION[user_id] = {"lat": lat, "lng": lng}
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=f"現在地を登録しました。この場所を起点に撮影地をご提案します。\n撮影したい日程や地域があればお知らせください。")
    )
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    with open('/tmp/debug.log', 'a') as f:
        f.write(f"[DEBUG] Message received: {event.message.text}\n")

    reply_token = event.reply_token

    # 即座に「お待ちください」を送信
    user_id = event.source.user_id
    try:
        line_bot_api.push_message(user_id, TextSendMessage(text="少々お待ちください。今旬の撮影地を探しております。🔍"))
    except:
        pass

    try:
        with open('/tmp/debug.log', 'a') as f:
            f.write("[DEBUG] About to call select_three_points\n")

        user_message = event.message.text.strip()
        # 問い返し待ちの回答処理
        if user_id in AMBIGUOUS_PENDING:
            pending = AMBIGUOUS_PENDING[user_id]
            prefs = pending["prefs"]
            city = pending["city"]
            resolved_pref = None
            if user_message.strip() in ["1", "１"]:
                resolved_pref = prefs[0]
            elif user_message.strip() in ["2", "２"]:
                resolved_pref = prefs[1]
            else:
                for p in prefs:
                    short = p.replace("県","").replace("都","").replace("府","").replace("道","")
                    if p in user_message or short in user_message:
                        resolved_pref = p
                        break
            if resolved_pref:
                del AMBIGUOUS_PENDING[user_id]
                latlng = geocode(f"{resolved_pref}{city}") or CITY_TO_LATLNG.get(city) or PREF_LATLNG.get(resolved_pref)
                target_date = parse_target_date(user_message)
                area_name, area_latlng, area_display = resolved_pref, latlng, city
            else:
                target_date = parse_target_date(user_message)
                area_name, area_latlng, area_display = parse_target_area(user_message)
        else:
            target_date = parse_target_date(user_message)
            area_name, area_latlng, area_display = parse_target_area(user_message)
        with open('/tmp/debug.log', 'a') as f:
            f.write(f"[DEBUG] area_name={area_name}, area_latlng={area_latlng}\n")
        # 同名地名の問い返し
        if area_name == "AMBIGUOUS":
            prefs = CITY_TO_PREF_MULTI.get(area_display, [])
            AMBIGUOUS_PENDING[user_id] = {"city": area_display, "prefs": prefs}
            msg = TextSendMessage(
                text=f"{area_display}は複数の地域にあります。\n" + "\n".join(f"{i+1}．{p}{area_display}" for i, p in enumerate(prefs)) + "\n\n番号でお答えください。"
            )
            line_bot_api.reply_message(reply_token, msg)
            return

        city_specified = any(c in user_message for c in ["市","町","村","区","郡"])
        # CITY_TO_PREFでヒットした場合（市町村名指定）はWIDE_PREFSスキップ
        city_from_dict = any(city in user_message or re.sub(r'[市区町村郡]', '', city) in user_message for city in CITY_TO_PREF)
        _radius = 150 if (city_specified or city_from_dict) else None

        if area_name and area_name in WIDE_PREFS and not city_specified and not city_from_dict:
            msg = TextSendMessage(
                text=f"{area_name[:-1]}ですか。それは楽しみですね。どのあたりに行かれますか？市町村名や地域名を教えていただけますか。"
            )
            line_bot_api.reply_message(reply_token, msg)
            return
        masterpiece, near, attention = select_three_points(base_date=target_date, base_latlng=area_latlng, radius=_radius, place_name=area_display)

        with open('/tmp/debug.log', 'a') as f:
            f.write(f"[DEBUG] select_three_points returned: masterpiece={masterpiece is not None}, near={near is not None}, attention={attention is not None}\n")

        if not masterpiece or not near:
            msg = TextSendMessage(
                text="申し訳ございません。現在条件に合う撮影地の検索ができておりません。"
            )
            line_bot_api.reply_message(reply_token, msg)
            return

        greeting = TextSendMessage(
            text=build_greeting(target_date, area_display)
        )

        bubbles = [
            build_carousel_bubble(masterpiece, "🏆", "傑作ポイント"),
            build_carousel_bubble(near, "🚗", "近場で楽しむ"),
            build_carousel_bubble(attention if attention and attention["pic"] != masterpiece["pic"] else near, "✨", "注目のポイント"),
        ]

        carousel = FlexSendMessage(
            alt_text="風景写真コンシェルジュ・今日の3選",
            contents={
                "type": "carousel",
                "contents": bubbles
            }
        )

        line_bot_api.reply_message(reply_token, [greeting, carousel])

        with open('/tmp/debug.log', 'a') as f:
            f.write("[DEBUG] Reply sent successfully\n")

    except Exception as e:
        import traceback
        err = traceback.format_exc()
        sys.stderr.write(f"[ERROR] Exception in handle_message: {err}\n")
        with open('/tmp/debug.log', 'a') as f:
            f.write(f"[ERROR] Exception in handle_message: {err}\n")
        try:
            msg = TextSendMessage(
                text="申し訳ございません。処理中にエラーが発生しました。"
            )
            line_bot_api.reply_message(reply_token, msg)
        except:
            pass

@handler.add(PostbackEvent)
def handle_postback(event):
    reply_token = event.reply_token

    try:
        data = event.postback.data
        params = dict(item.split('=') for item in data.split('&'))
        action = params.get('action')
        pic_filename = params.get('pic', '')

        if action == 'detail':
            msg = TextSendMessage(
                text=f"📸 スペック画面\n（スペック情報の取得準備中）\n\nファイル: {pic_filename}"
            )
            line_bot_api.reply_message(reply_token, msg)

        elif action == 'record':
            if db:
                route_data = {
                    'timestamp': date.today().isoformat(),
                    'pic_filename': pic_filename,
                    'user_id': event.source.user_id if hasattr(event.source, 'user_id') else 'unknown',
                }
                db.collection('Saved_Routes').add(route_data)

            msg = TextSendMessage(
                text="✨ ルート記録完了\nコンシェルジュの部屋に保存しました。"
            )
            line_bot_api.reply_message(reply_token, msg)

    except Exception as e:
        print(f"[ERROR] Postback handling error: {e}")
        msg = TextSendMessage(
            text="処理中にエラーが発生しました。"
        )
        line_bot_api.reply_message(reply_token, msg)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
