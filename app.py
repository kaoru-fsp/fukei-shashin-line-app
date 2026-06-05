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
from linebot.models import MessageEvent, TextMessage, LocationMessage, PostbackEvent, TextSendMessage, FlexSendMessage, QuickReply, QuickReplyButton, PostbackAction
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

# ──────────────── 市区町村の座標表（オフライン辞書引き）────────────────
# 全国の市区町村→緯度経度。実行時のジオコーディング(API)を避け、距離計算を即時化する。
CITY_LATLNG = {}
CITY_NAMES_BY_PREF = {}
try:
    _cpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'city_latlng.json')
    with open(_cpath, encoding='utf-8') as _f:
        CITY_LATLNG = {k: tuple(v) for k, v in json.load(_f).items()}
    for _key in CITY_LATLNG:
        for _p in PREF_LATLNG:
            if _key.startswith(_p):
                CITY_NAMES_BY_PREF.setdefault(_p, []).append(_key[len(_p):])
                break
    for _p in CITY_NAMES_BY_PREF:
        CITY_NAMES_BY_PREF[_p].sort(key=len, reverse=True)  # 長い名前優先(さいたま市桜区>さいたま市)
    print(f"[INFO] city_latlng loaded: {len(CITY_LATLNG)} municipalities", flush=True)
except Exception as _e:
    print(f"[WARN] city_latlng.json load failed: {_e}", flush=True)

SHINJUKU = (35.70044, 139.71827)      # デフォルト起点: 東京都新宿区
DEFAULT_ORIGIN_NAME = "東京都新宿区"

def work_latlng(area, pref=None):
    """作品のArea文字列から市区町村の座標を返す。見つからなければNone（呼び出し側で県重心にフォールバック）。"""
    a = str(area or '').strip()
    if not a:
        return None
    if pref is None:
        pref = extract_pref(a)
    if not pref:
        return None
    rest = (a[len(pref):] if a.startswith(pref) else a).strip()
    for city in CITY_NAMES_BY_PREF.get(pref, ()):
        if city and rest.startswith(city):
            return CITY_LATLNG.get(pref + city)
    # 救済: 市区町村種別が抜けている表記（例: 草津→草津町／みなかみ→みなかみ町）
    head = re.split(r'[\s　0-9０-９]', rest)[0] if rest else ''
    if head:
        for suf in ('市', '町', '村', '区'):
            hit = CITY_LATLNG.get(pref + head + suf)
            if hit:
                return hit
    return None

def format_loc_city(address):
    """LINEの位置情報addressから『県+市区町村』を抽出。失敗時は空文字。"""
    m = re.search(r'([^\s　0-9〒]+?[都道府県])\s*([^\s　0-9]+?[市区町村])', str(address or ''))
    return (m.group(1) + m.group(2)) if m else ''

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

def format_period(month, day):
    """撮影時期を ［◯月x旬］ 形式で返す。日があれば上/中/下旬に変換、月のみなら旬を省略。"""
    try:
        m = int(month)
    except:
        return ''
    jun = junkun(day)  # 上旬/中旬/下旬 or None
    return f"［{m}月{jun}］" if jun else f"［{m}月］"

JUN_LABELS = ['上旬', '中旬', '下旬']
# 「見頃」という表現が自然な季節被写体（花・季節現象）
SEASONAL_SUBJECTS = {'桜', '紅葉', '雪', 'ひまわり', 'コスモス', 'ススキ', '紫陽花', '菜の花', '芝桜', '藤', 'ラベンダー'}

def _jun_offset(day):
    return {'上旬': 0, '中旬': 1, '下旬': 2}.get(junkun(day), 1)  # 日不明は中旬扱い

def bin_index(month, day):
    return (int(month) - 1) * 3 + _jun_offset(day)

def bin_label(idx):
    return f"{idx // 3 + 1}月{JUN_LABELS[idx % 3]}"

def compute_peaks(bin_counter, min_count=3, max_peaks=2):
    """旬(上中下)単位のヒストグラムから見頃を検出。
    3旬(≈1か月)のローリング窓で点数が min_count 以上集中している中心を、重複を避けて上位 max_peaks 件返す。
    戻り値: 中心の旬インデックス(0..35)のリスト。基準を満たすものが無ければ空。"""
    if not bin_counter:
        return []
    wins = sorted(((c, sum(bin_counter.get((c + o) % 36, 0) for o in (-1, 0, 1))) for c in range(36)),
                  key=lambda x: -x[1])
    peaks, used, first_tot = [], set(), None
    for c, tot in wins:
        if tot < min_count:
            break
        if first_tot is not None and tot < first_tot * 0.34:
            break  # 一番手に比べて弱いピークは見頃と見なさない(冬桜など少数の別季節を除外)
        if c in used:
            continue
        if first_tot is None:
            first_tot = tot
        peaks.append(c)
        for o in range(-4, 5):   # 採用したピークの前後約1.3か月を除外(隣接旬の重複・尾引きを防ぐ)
            used.add((c + o) % 36)
        if len(peaks) >= max_peaks:
            break
    return peaks

def peaks_text(peaks):
    return "・".join(bin_label(c) for c in peaks)

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

# ── 壊れた画像(サーバに実体が無い/エラーページ)の除外 ──
VERIFY_IMAGES = True          # 問題があれば False で無効化
_IMG_OK_CACHE = {}            # url -> bool (このプロセス内キャッシュ)

def image_available(url, timeout=2.5):
    """画像URLが実在し画像として返るかを保守的に判定。判定不能なら True(表示維持)。"""
    if not url:
        return False
    if url in _IMG_OK_CACHE:
        return _IMG_OK_CACHE[url]
    ok = True
    try:
        import urllib.request, urllib.error
        req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ct = (r.headers.get('Content-Type') or '').lower()
            # Content-Typeが分かる場合のみ判定。画像でなければ壊れ扱い。不明なら表示維持。
            if ct and not ct.startswith('image'):
                ok = False
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):   # 明確に存在しない場合のみ除外
            ok = False
    except Exception:
        ok = True                  # ネットワーク不調等は表示を維持
    _IMG_OK_CACHE[url] = ok
    return ok

def filter_broken_images(results, max_workers=8):
    """(emoji,label,item) のリストから、画像が壊れている候補を除外して返す。"""
    if not VERIFY_IMAGES or not results:
        return results
    try:
        from concurrent.futures import ThreadPoolExecutor
        urls = [it.get('url') for _, _, it in results]
        with ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as ex:
            oks = list(ex.map(image_available, urls))
        return [r for r, ok in zip(results, oks) if ok]
    except Exception:
        return results  # 判定処理自体が失敗したら従来どおり全件表示

def subject_matches(variants, title='', place='', area='', subject_field=''):
    """被写体語が作品に該当するか判定。
    Subject/タイトル一致は確実。地名・エリアでは複合地名(瀧谷・滝沢・滝川など)の
    誤ヒットを避けるため、被写体語の直後がCJK文字でない(=地名の途中でない)場合のみ採用。"""
    title = str(title or ''); place = str(place or ''); area = str(area or ''); subject_field = str(subject_field or '')
    for v in variants:
        if v and (v in subject_field or v in title):
            return True
    for fld in (place, area):
        for v in variants:
            if not v:
                continue
            for m in re.finditer(re.escape(v), fld):
                nxt = fld[m.end():m.end() + 1]
                if not nxt or not re.match(r'[ぁ-んァ-ヶ一-龥ー]', nxt):
                    return True
    return False

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
AMBIGUOUS_PENDING = {}
EXPAND_PENDING = {}  # 検索拡張待ち  # user_id -> {"city": "小国町", "prefs": ["熊本県", "山形県"]}
SUBJECT_PENDING = {}  # 地域＋被写体が0件のときの選択待ち
USER_LOCATION = {}  # user_id -> {"lat": 35.xxx, "lng": 139.xxx}
USER_HOME = {}  # user_id -> {"lat":.., "lng":.., "name": "..."}  自宅(帰路の基準点)
USER_SEEN = set()  # 初回メッセージ済みuser_id

# ── ユーザー情報(位置・初回フラグ)のFirestore永続化 ──
# メモリ上の USER_LOCATION / USER_SEEN は再起動で消えるため、
# Firestoreの Users コレクション(doc id = user_id)に読み書きして永続化する。
# 書き込みは「メモリ＋Firestore」両方、読み込みは初回だけFirestoreから復元(以後はメモリ)。
_HYDRATED = set()  # このプロセスで既にFirestoreから読み込み済みのuser_id

def hydrate_user(user_id):
    """初回アクセス時にFirestoreからユーザー情報を読み、メモリに復元する。"""
    if user_id in _HYDRATED:
        return
    _HYDRATED.add(user_id)
    if not db:
        return
    try:
        snap = db.collection('Users').document(user_id).get()
        if snap.exists:
            data = snap.to_dict() or {}
            if data.get('seen'):
                USER_SEEN.add(user_id)
            if data.get('lat') is not None and data.get('lng') is not None:
                USER_LOCATION[user_id] = {"lat": data['lat'], "lng": data['lng'], "city": data.get('city', '')}
            if data.get('home_lat') is not None and data.get('home_lng') is not None:
                USER_HOME[user_id] = {"lat": data['home_lat'], "lng": data['home_lng'], "name": data.get('home_name', '')}
    except Exception:
        import traceback
        print(f"[ERROR] hydrate_user failed: {traceback.format_exc()}", flush=True)

def save_user_home(user_id, lat, lng, name=None):
    """自宅(帰路の基準点)をメモリとFirestoreの両方に保存する。"""
    USER_HOME[user_id] = {"lat": lat, "lng": lng, "name": name or ''}
    if not db:
        return
    try:
        payload = {"home_lat": lat, "home_lng": lng, "updated": firestore.SERVER_TIMESTAMP}
        if name:
            payload["home_name"] = name
        db.collection('Users').document(user_id).set(payload, merge=True)
    except Exception:
        import traceback
        print(f"[ERROR] save_user_home failed: {traceback.format_exc()}", flush=True)

def save_user_location(user_id, lat, lng, city=None):
    """位置情報をメモリとFirestoreの両方に保存する。"""
    USER_LOCATION[user_id] = {"lat": lat, "lng": lng, "city": city or ''}
    if not db:
        return
    try:
        payload = {"lat": lat, "lng": lng, "updated": firestore.SERVER_TIMESTAMP}
        if city:
            payload["city"] = city
        db.collection('Users').document(user_id).set(payload, merge=True)
    except Exception:
        import traceback
        print(f"[ERROR] save_user_location failed: {traceback.format_exc()}", flush=True)

def mark_user_seen(user_id):
    """初回フラグをメモリとFirestoreの両方に立てる。"""
    USER_SEEN.add(user_id)
    if not db:
        return
    try:
        db.collection('Users').document(user_id).set(
            {"seen": True, "updated": firestore.SERVER_TIMESTAMP},
            merge=True,
        )
    except Exception:
        import traceback
        print(f"[ERROR] mark_user_seen failed: {traceback.format_exc()}", flush=True)

def record_search(user_id, query):
    """利用状況の観察用。検索回数と最終利用日時を更新し、検索内容を記録する。
    テスト公開中は上限などの制限はかけず、数えて記録するだけ。"""
    if not db:
        return
    try:
        db.collection('Users').document(user_id).set(
            {"search_count": firestore.Increment(1),
             "last_used": firestore.SERVER_TIMESTAMP,
             "last_query": query},
            merge=True,
        )
        db.collection('SearchLogs').add(
            {"user_id": user_id, "query": query, "ts": firestore.SERVER_TIMESTAMP}
        )
    except Exception:
        import traceback
        print(f"[ERROR] record_search failed: {traceback.format_exc()}", flush=True)

def feedback_quick_reply():
    """検索結果に対する満足度フィードバックのクイックリプライ(タップ式)。"""
    return QuickReply(items=[
        QuickReplyButton(action=PostbackAction(
            label="👍 ちょうど良い", data="action=feedback&rating=good", display_text="ちょうど良い")),
        QuickReplyButton(action=PostbackAction(
            label="🤔 ピンとこない", data="action=feedback&rating=meh", display_text="ピンとこない")),
        QuickReplyButton(action=PostbackAction(
            label="📍 場所に違和感", data="action=feedback&rating=place", display_text="場所に違和感")),
    ])

def delete_user_data(user_id):
    """ユーザー本人の記録(Users / SearchLogs / Feedback)をすべて削除する。同意撤回・削除依頼用。"""
    # メモリ上の状態もクリア
    USER_LOCATION.pop(user_id, None)
    USER_SEEN.discard(user_id)
    _HYDRATED.discard(user_id)
    if not db:
        return
    try:
        db.collection('Users').document(user_id).delete()
        for coll in ('SearchLogs', 'Feedback'):
            for d in db.collection(coll).where('user_id', '==', user_id).stream():
                d.reference.delete()
    except Exception:
        import traceback
        print(f"[ERROR] delete_user_data failed: {traceback.format_exc()}", flush=True)

def usage_guide_messages():
    """初回案内・「使い方」コマンドで表示する使い方ガイド。
    読みやすいよう話題ごとに分割したメッセージのリストを返す(最大5通)。"""
    return [
        (
            "【使い方】\n"
            "行きたい「地域」「被写体」「日付」を送ると、『風景写真』の傑作が撮られた撮影地をご提案します。\n"
            "\n"
            "▼送り方の例\n"
            "・地域で探す：栃木県／美瑛／箱根\n"
            "・被写体で探す：滝／桜／紅葉／星空／海\n"
            "・日付を添える：週末 京都／明日 滝／3日後"
        ),
        (
            "▼使える日付の言い方\n"
            "明日・明後日・今週末・来週末・3日後・6月15日 など\n"
            "（指定しない場合は今の時期に合わせてご提案します)"
        ),
        (
            "▼位置情報を登録すると\n"
            "地域を指定しなくても、今いる場所の近くからご提案します。\n"
            "\n"
            "【登録方法】このトーク画面で位置情報を送るだけです。\n"
            "1. 入力欄の左の「＋」をタップ\n"
            "2. メニューから「位置情報」を選ぶ\n"
            "3. 地図で場所を指定(現在地のまま／検索／地図を動かして調整)\n"
            "4. 右上の「送信」をタップ\n"
            "詳しい解説→ https://guide.line.me/ja/services/location-information.html"
        ),
        (
            "ご提案の下に出るボタンで感想(ちょうど良い／ピンとこない／場所に違和感)を教えていただけると、今後の精度向上に役立ちます。\n"
            "\n"
            "この説明は「使い方」と送るといつでも表示できます。"
        ),
    ]

KEYWORD_NORMALIZE = {
    '滝': ['滝', '瀧', 'たき', 'タキ'],
    '桜': ['桜', '櫻', 'さくら', 'サクラ', '桜花'],
    '紅葉': ['紅葉', 'もみじ', 'モミジ', '紅葉狩り'],
    '雪': ['雪', 'ゆき', '積雪', '雪景色', '吹雪'],
    '富士': ['富士', '富士山', 'ふじさん', 'Mt.Fuji'],
    '棚田': ['棚田', 'たなだ'],
    '海': ['海', '海岸', '海辺', 'うみ', '波'],
    '湖': ['湖', 'みずうみ', '池', '沼'],
    '川': ['川', '河川', '渓流', '河原'],
    '渓谷': ['渓谷', '谷', '峡谷'],
    '朝焼け': ['朝焼け', '朝焼', '夜明け', '日の出'],
    '夕焼け': ['夕焼け', '夕焼', '夕日', '日没', 'サンセット'],
    '星': ['星', '星空', '天体', '星景'],
    '天の川': ['天の川', '天の川', '銀河'],
    '霧': ['霧', '霞', '雲海', 'きり'],
    '氷': ['氷', '霜', '結氷', '氷点', 'つらら'],
    'ひまわり': ['ひまわり', 'ヒマワリ', '向日葵'],
    'コスモス': ['コスモス', 'こすもす', '秋桜'],
    'ススキ': ['ススキ', 'すすき', '薄'],
    '紫陽花': ['紫陽花', 'あじさい', 'アジサイ'],
    '菜の花': ['菜の花', 'なのはな', '菜花', '菜の花畑'],
    '芝桜': ['芝桜', 'しばざくら'],
    '藤': ['藤', 'ふじ', '藤の花'],
    'ラベンダー': ['ラベンダー', 'らべんだー'],
    '鉄道': ['鉄道', '列車', '電車', '汽車', 'SL', '蒸気機関車', 'ローカル線'],
    '灯台': ['灯台', 'とうだい'],
    '城': ['城', 'お城', '城郭'],
    '神社': ['神社', '神宮', '社', '鳥居'],
    '寺': ['寺', 'お寺', '寺院', '仏閣'],
    '白鳥': ['白鳥', 'はくちょう', 'スワン'],
    'タンチョウ': ['タンチョウ', 'たんちょう', '丹頂', '鶴'],
    'ツツジ': ['ツツジ', 'つつじ', '躑躅', 'ミヤマキリシマ', 'アケボノツツジ', 'イワツツジ', 'シャクナゲ', 'しゃくなげ'],
}

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
    return today

def parse_target_area(text):
    for pref in PREF_LATLNG:
        if pref == "北海道":
            short = "北海道"
        else:
            short = pref.replace("都","").replace("府","").replace("県","")
        if pref in text or short in text:
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

def build_greeting(target_date, area_name, date_specified=False):
    today = date.today()
    delta = (target_date - today).days
    if delta == 1:
        date_str = f"明日（{format_date_jp(target_date)}）に"
    elif delta == 2:
        date_str = f"明後日（{format_date_jp(target_date)}）に"
    elif 3 <= delta <= 14:
        date_str = f"{delta}日後（{format_date_jp(target_date)}）に"
    elif date_specified:
        date_str = f"{format_date_jp(target_date)}に"
    else:
        date_str = ""
    area_str = f"{area_name}に" if area_name and area_name != "現在地" else ""
    if date_str or area_str:
        return (
            f"ようこそ風景写真コンシェルジュの部屋へ。"
            f"{date_str}{area_str}撮影にお出かけですか。"
            f"それでしたらこんなところはいかがでしょう。"
        )
    else:
        return "ようこそ風景写真コンシェルジュの部屋へ。こんなところはいかがでしょう。"

# ──────────────── 3分類選定エンジン ────────────────
def select_three_points(base_date=None, base_latlng=None, radius=None, place_name=None, keyword=None, expand_time=False, target_city=None, origin_latlng=None, origin_name=None):

    if not db:
        return []

    try:
        # radius未指定(None)時は距離制限なしとして扱う(dist > None のTypeError防止)
        if radius is None:
            radius = float('inf')
        # 距離計算の基準点と、表示用の基準地名("◯◯より △△km")
        tokyo = PREF_LATLNG["東京都"]
        # 距離の起点(現在地 or 新宿区)と、表示用の起点名("◯◯より △△km")。検索中心(base_latlng)とは別概念。
        origin = origin_latlng if origin_latlng else SHINJUKU
        base_name = origin_name or DEFAULT_ORIGIN_NAME
        excl_authors, blocked_areas = load_exclusions()
        tomorrow = base_date if base_date else date.today() + timedelta(days=1)
        if expand_time:
            junkun_window = set()
            for delta in range(-30, 31):
                d2 = tomorrow + timedelta(days=delta)
                junkun_window.add((d2.month, junkun(d2.day)))
        else:
            junkun_window = half_month_window(tomorrow)

        pool = []
        place_years = defaultdict(list)


        # 指定都道府県を特定
        target_pref = None
        if base_latlng:
            target_pref = min(PREF_LATLNG.keys(), key=lambda k: haversine(base_latlng[0], base_latlng[1], PREF_LATLNG[k][0], PREF_LATLNG[k][1]))

        target_months = list(set(str(m) for m, k in junkun_window))
        query = db.collection('Master_Photos').where('Month', 'in', target_months)
        for doc in query.stream():
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
            dist = haversine(tokyo[0], tokyo[1], lat, lng)  # 既存の絞り込み用(従来通り)
            wll = work_latlng(d.get('Area'), pref)
            wlat, wlng = wll if wll else (lat, lng)          # 表示用座標: 市区町村, なければ県重心
            disp_dist = haversine(origin[0], origin[1], wlat, wlng)  # 起点→撮影地の実距離

            # 指定都道府県がある場合は同県を優先、足りなければ半径内も追加
            if target_pref:
                if target_city and base_latlng:
                    # 市指定時は「指定地点中心」で近隣を判定（撮影地の市座標で精密に）
                    base_dist = haversine(base_latlng[0], base_latlng[1], wlat, wlng)
                    if pref != target_pref and base_dist > radius:
                        continue
                else:
                    if pref != target_pref and dist > radius:
                        continue
            else:
                if dist > radius:
                    continue

            if d.get('Winner') in excl_authors:
                continue
            if is_area_blocked(d.get('Place'), d.get('Area'), blocked_areas):
                continue
            if not has_valid_image(d.get('PicFileName')):
                continue
            # 風景写真祭作品は検索対象外
            pub = d.get('Published', '')
            if pub and pub.endswith('N'):
                continue

            matched_kw = None
            if keyword:
                kw_variants = KEYWORD_NORMALIZE.get(keyword, [keyword])
                if not subject_matches(kw_variants, title=d.get('Title', ''), place=d.get('Place', ''),
                                       area=d.get('Area', ''), subject_field=d.get('Subject', '')):
                    continue
                _blob = d.get('Subject', '') + d.get('Title', '') + d.get('Place', '') + d.get('Area', '')
                matched_kw = next((v for v in kw_variants if v in _blob), keyword)

            item = {
                'dist': disp_dist,
                'wlatlng': (wlat, wlng),
                'pref': pref,
                'area': d.get('Area', ''),
                'place': d.get('Place', ''),
                'title': d.get('Title', ''),
                'period': format_period(d.get('Month'), d.get('Day')),
                'winner': d.get('Winner', ''),
                'winner_area': d.get('WinnerArea', ''),
                'award': d.get('AwardRank', ''),
                'ascore': calc_award_score(d.get('AwardRank')),
                'pic': d.get('PicFileName', ''),
                'pub': d.get('Published', ''),
                'url': view_image_url(d.get('Published', ''), d.get('PicFileName', '')),
                'base_name': base_name,
                'maplink': d.get('MapLink', ''),
                'dnumb': str(d.get('dNumb', '')),
                'matched_kw': matched_kw,
            }
            pool.append(item)

            try:
                place_years[d.get('Area', '')].append(int(d.get('Year')))
            except:
                pass


        # 地域指定時にpoolが空の場合はTOO_FEWを返す
        if not pool and target_pref:
            return 'TOO_FEW', target_pref, 0
        # 地域未指定時にpoolが空の場合、旬ウィンドウを前後1ヶ月に広げてリトライ
        if not pool and base_latlng and not target_pref:
            wider_window = set()
            for delta in range(-30, 31):
                d2 = tomorrow + timedelta(days=delta)
                wider_window.add((d2.month, junkun(d2.day)))
            wider_months = list(set(str(m) for m, k in wider_window))
            wider_query = db.collection('Master_Photos').where('Month', 'in', wider_months)
            for doc in wider_query.stream():
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
                if dist > radius:
                    continue
                if d.get('Winner') in excl_authors:
                    continue
                if not has_valid_image(d.get('PicFileName')):
                    continue
                pub = d.get('Published', '')
                if pub and pub.endswith('N'):
                    continue
                item = {
                    'dist': disp_dist,
                    'wlatlng': (wlat, wlng),
                    'pref': pref,
                    'area': d.get('Area', ''),
                    'place': d.get('Place', '') or '',
                    'title': d.get('Title', ''),
                    'period': format_period(d.get('Month'), d.get('Day')),
                    'winner': d.get('Winner', ''),
                    'winner_area': d.get('WinnerArea', ''),
                    'award': d.get('AwardRank', ''),
                    'ascore': calc_award_score(d.get('AwardRank')),
                    'pic': d.get('PicFileName', ''),
                    'pub': d.get('Published', ''),
                    'url': view_image_url(d.get('Published', ''), d.get('PicFileName', '')),
                    'base_name': base_name,
                    'maplink': d.get('MapLink', ''),
                    'dnumb': str(d.get('dNumb', '')),
                    'matched_kw': None,
                }
                pool.append(item)
                try:
                    place_years[d.get('Area', '')].append(int(d.get('Year')))
                except:
                    pass

        if not pool:
            if target_pref:
                return 'TOO_FEW', target_pref, 0
            return []

        # 市町村が明示された場合: 市一致をベストマッチ、それ以外を「◯◯周辺の撮影地」に分けて返す
        if target_pref and target_city:
            city_base = re.sub(r'[市区町村郡]', '', target_city).strip()
            CITY_NEARBY_RADIUS_KM = 75  # 市指定時の「周辺」範囲（指定地点中心）
            # 指定地点(base_latlng=検索中心)から撮影地の市座標までの距離（なければ県重心）
            def _city_dist(p):
                if not base_latlng:
                    return 99999
                ll = p.get('wlatlng') or PREF_LATLNG.get(p['pref'])
                if not ll:
                    return 99999
                return haversine(base_latlng[0], base_latlng[1], ll[0], ll[1])
            sorted_pool = sorted(pool, key=lambda x: (-x['ascore'], x['dist']))
            city_pool = [p for p in sorted_pool if city_base and city_base in p['area']]
            nearby_pool = sorted(
                [p for p in sorted_pool
                 if not (city_base and city_base in p['area']) and _city_dist(p) <= CITY_NEARBY_RADIUS_KM],
                key=lambda x: (_city_dist(x), -x['ascore'])
            )
            used_pics = set()
            cresults = []
            # ベストマッチ(市一致): 同一作品のみ除去し、同じ市の作品は複数見せる(撮影地重複を許容)
            for p in city_pool:
                if len(cresults) >= 7:
                    break
                if p['pic'] in used_pics:
                    continue
                cresults.append(('🎯', 'ベストマッチ', p))
                used_pics.add(p['pic'])
            city_count = len(cresults)
            # 周辺候補: 撮影地の重複を避けて補完
            nearby_label = f"{city_base}周辺の撮影地"
            used_areas = set()
            for p in nearby_pool:
                if len(cresults) >= 7:
                    break
                if p['pic'] in used_pics or p['area'] in used_areas:
                    continue
                cresults.append(('📍', nearby_label, p))
                used_pics.add(p['pic'])
                used_areas.add(p['area'])
            return ('CITY', city_base, city_count, filter_broken_images(cresults))

        used_pics = set()
        results = []

        ibaraki_in_pool = [p for p in pool if p['pref'] == '茨城県']
        # 🎯 ベストマッチ（同県優先、最大7枚）
        if target_pref:
            best_pool = [p for p in sorted(pool, key=lambda x: (-x['ascore'], x['dist'])) if p['pref'] == target_pref]
            if len(best_pool) < 3:
                return 'TOO_FEW', target_pref, len(best_pool)
        else:
            best_pool = sorted(pool, key=lambda x: (-x['ascore'], x['dist']))
        used_areas = set()
        for p in best_pool:
            if len(results) >= 7:
                break
            if p['area'] in used_areas:
                continue
            results.append(('🎯', 'ベストマッチ', p))
            used_pics.add(p['pic'])
            used_areas.add(p['area'])

        # ✨ 注目・傑作（同県優先、最大2枚）
        recent_cutoff = date.today().year - 5
        attention_score = {
            a: sum(1 for y in ys if y >= recent_cutoff)
            for a, ys in place_years.items()
        }
        hot_pool = sorted(pool, key=lambda x: (-attention_score.get(x['area'], 0), -x['ascore']))
        if target_pref:
            hot_cand = [p for p in hot_pool if p['pref'] == target_pref and p['pic'] not in used_pics] or [p for p in hot_pool if p['pic'] not in used_pics]
        else:
            hot_cand = [p for p in hot_pool if p['pic'] not in used_pics]
        used_areas_hot = set()
        for p in hot_cand:
            if len([r for r in results if r[1] == '注目・傑作']) >= 2:
                break
            if p['area'] in used_areas_hot:
                continue
            results.append(('✨', '注目・傑作', p))
            used_pics.add(p['pic'])
            used_areas_hot.add(p['area'])

        masterpiece = results[0][2] if results else None
        near = results[1][2] if len(results) > 1 else masterpiece

        # 🎲 気まぐれチョイス（地域・キーワード未指定の時のみ、最大2枚）
        show_gamble = not base_latlng and not keyword
        if show_gamble:
            all_docs = list(db.collection('Master_Photos').stream())
        else:
            all_docs = []
        random.shuffle(all_docs)
        gamble_count = 0
        for doc in all_docs:
            if gamble_count >= 2:
                break
            d = doc.to_dict()
            if d.get('PicFileName') in used_pics:
                continue
            if not has_valid_image(d.get('PicFileName')):
                continue
            pub = d.get('Published', '')
            if pub and pub.endswith('N'):
                continue
            item = {
                'dist': haversine(origin[0], origin[1],
                                  *( work_latlng(d.get('Area', '')) or PREF_LATLNG.get(extract_pref(d.get('Area', '')) or '', SHINJUKU) )),
                'pref': extract_pref(d.get('Area', '')),
                'area': d.get('Area', ''),
                'place': d.get('Place', '') or '',
                'title': d.get('Title', ''),
                'period': format_period(d.get('Month'), d.get('Day')),
                'winner': d.get('Winner', ''),
                'winner_area': d.get('WinnerArea', ''),
                'award': d.get('AwardRank', ''),
                'ascore': calc_award_score(d.get('AwardRank')),
                'pic': d.get('PicFileName', ''),
                'pub': d.get('Published', ''),
                'url': view_image_url(d.get('Published', ''), d.get('PicFileName', '')),
                'base_name': base_name,
                'maplink': d.get('MapLink', ''),
                'dnumb': str(d.get('dNumb', '')),
                'matched_kw': matched_kw,
            }
            results.append(('🎲', '気まぐれチョイス', item))
            used_pics.add(item['pic'])
            gamble_count += 1


        # 地域指定がある場合はベストマッチ（同県）を前に並べ替え
        if base_latlng:
            same_pref = [(e, l, p) for e, l, p in results if l == 'ベストマッチ']
            others = [(e, l, p) for e, l, p in results if l != 'ベストマッチ']
            results = same_pref + others

        return filter_broken_images(results)

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        # Renderのログ(stdout)にも出す。ファイルだけだと画面で気づけないため
        print(f"[ERROR] select_three_points exception: {tb}", flush=True)
        return []

# ──────────────── Flex Message 組み立て ────────────────
def search_by_place(place_query, base_date=None, origin_latlng=None, origin_name=None, subject=None, center_latlng=None, radius_km=None, home_latlng=None):
    """地点名(Place/Area/Title)の自由文検索。
    今の時期に一致する作品があればそれを、無ければ全期間からその地点の作品を返す。
    center_latlng+radius_km を指定すると、その中心から半径内の作品に絞り近い順に返す。
    home_latlng も指定すると、自宅に近づく方向(帰路)の作品だけに絞り、寄り道の少ない順に返す。
    返り値: {'status': 'in_season'|'off_season'|'not_found', 'results': [(emoji,label,item),...]}"""
    if not db:
        return {'status': 'not_found', 'results': []}
    base = base_date if base_date else date.today() + timedelta(days=1)
    window = half_month_window(base)
    tokyo = PREF_LATLNG["東京都"]
    origin = origin_latlng if origin_latlng else SHINJUKU
    base_name = origin_name or DEFAULT_ORIGIN_NAME
    try:
        excl_authors, blocked_areas = load_exclusions()
    except Exception:
        excl_authors, blocked_areas = set(), []
    in_season, all_time = [], []
    bin_counter = Counter()  # マッチした公開作品の旬分布(見頃クラスタ算出用)
    subject_variants = KEYWORD_NORMALIZE.get(subject, [subject]) if subject else None
    place_terms = place_query if isinstance(place_query, (list, tuple)) else [place_query]
    place_terms = [t for t in place_terms if t]
    try:
        for doc in db.collection('Master_Photos').stream():
            d = doc.to_dict()
            place = d.get('Place', '') or ''
            area = d.get('Area', '') or ''
            title = d.get('Title', '') or ''
            if place_terms and not any(t in place or t in area or t in title for t in place_terms):
                continue
            if subject_variants and not subject_matches(subject_variants, title=title, place=place, area=area, subject_field=d.get('Subject', '')):
                continue
            if d.get('Winner') in excl_authors:
                continue
            if is_area_blocked(d.get('Place'), d.get('Area'), blocked_areas):
                continue
            if not has_valid_image(d.get('PicFileName')):
                continue
            pub = d.get('Published', '')
            if pub and pub.endswith('N'):
                continue
            pref = extract_pref(area)
            wll = work_latlng(area, pref)
            cll = wll if wll else (PREF_LATLNG.get(pref) if (pref and pref in PREF_LATLNG) else None)
            if center_latlng and radius_km:
                if not cll or haversine(center_latlng[0], center_latlng[1], cll[0], cll[1]) > radius_km:
                    continue
            cdist = haversine(center_latlng[0], center_latlng[1], cll[0], cll[1]) if (center_latlng and cll) else 0
            detour = 0
            if home_latlng and center_latlng:
                if not cll:
                    continue
                d_ch = haversine(center_latlng[0], center_latlng[1], home_latlng[0], home_latlng[1])
                d_wh = haversine(cll[0], cll[1], home_latlng[0], home_latlng[1])
                if d_wh >= d_ch:   # 自宅に近づかない(=帰路方向でない)ものは除外
                    continue
                detour = cdist + d_wh - d_ch   # 寄り道距離(現在地→作品→自宅 と 現在地→自宅 の差)
            if wll:
                dist = haversine(origin[0], origin[1], wll[0], wll[1])
            elif pref and pref in PREF_LATLNG:
                dist = haversine(origin[0], origin[1], PREF_LATLNG[pref][0], PREF_LATLNG[pref][1])
            else:
                dist = 0
            try:
                year = int(d.get('Year'))
            except Exception:
                year = 0
            item = {
                'dist': dist, 'pref': pref or '', 'area': area, 'place': place, 'cdist': cdist, 'detour': detour,
                'title': title, 'period': format_period(d.get('Month'), d.get('Day')), 'winner': d.get('Winner', ''), 'winner_area': d.get('WinnerArea', ''),
                'award': d.get('AwardRank', ''), 'ascore': calc_award_score(d.get('AwardRank')),
                'pic': d.get('PicFileName', ''), 'pub': pub,
                'url': view_image_url(pub, d.get('PicFileName', '')),
                'base_name': base_name, 'maplink': d.get('MapLink', ''),
                'dnumb': str(d.get('dNumb', '')), 'matched_kw': None, '_year': year,
            }
            all_time.append(item)
            try:
                _mo = int(d.get('Month'))
                if 1 <= _mo <= 12:
                    bin_counter[bin_index(_mo, d.get('Day'))] += 1
                if (_mo, junkun(d.get('Day'))) in window:
                    in_season.append(item)
            except Exception:
                pass
    except Exception:
        import traceback
        print(f"[ERROR] search_by_place failed: {traceback.format_exc()}", flush=True)
        return {'status': 'not_found', 'results': []}

    if in_season:
        pool, status = in_season, 'in_season'
    elif all_time:
        pool, status = all_time, 'off_season'
    else:
        return {'status': 'not_found', 'results': []}
    if home_latlng and center_latlng:
        pool.sort(key=lambda x: (x.get('detour', 0), x.get('cdist', 0)))
    elif center_latlng:
        pool.sort(key=lambda x: (x.get('cdist', 0), -x['ascore']))
    else:
        pool.sort(key=lambda x: (-x['ascore'], -x.get('_year', 0)))
    results, used = [], set()
    for p in pool:
        if len(results) >= 7:
            break
        if p['pic'] in used:
            continue
        results.append(('🎯', 'ベストマッチ', p))
        used.add(p['pic'])
    results = filter_broken_images(results)
    if not results:
        return {'status': 'not_found', 'results': []}
    peaks = compute_peaks(bin_counter)
    return {'status': status, 'results': results, 'peaks': peaks}

def subjects_in_peak_near(center_latlng, radius_km, base_date=None):
    """中心から半径内の公開作品を被写体別に集計し、現在(base_date)が見頃にあたる被写体を返す。
    戻り値: [(subject, peaks_text, count), ...] を件数の多い順で。"""
    if not db or not center_latlng:
        return []
    base = base_date or date.today()
    cur_bin = bin_index(base.month, base.day)
    try:
        excl_authors, blocked_areas = load_exclusions()
    except Exception:
        excl_authors, blocked_areas = set(), []
    from collections import defaultdict
    bins = defaultdict(Counter)
    try:
        for doc in db.collection('Master_Photos').stream():
            d = doc.to_dict()
            pub = d.get('Published', '')
            if pub and pub.endswith('N'):
                continue
            if not has_valid_image(d.get('PicFileName')):
                continue
            if d.get('Winner') in excl_authors:
                continue
            area = d.get('Area', '') or ''
            place = d.get('Place', '') or ''
            title = d.get('Title', '') or ''
            if is_area_blocked(place, area, blocked_areas):
                continue
            pref = extract_pref(area)
            wll = work_latlng(area, pref) or (PREF_LATLNG.get(pref) if (pref and pref in PREF_LATLNG) else None)
            if not wll or haversine(center_latlng[0], center_latlng[1], wll[0], wll[1]) > radius_km:
                continue
            try:
                mo = int(d.get('Month'))
            except Exception:
                continue
            if not (1 <= mo <= 12):
                continue
            bi = bin_index(mo, d.get('Day'))
            sfield = d.get('Subject', '')
            for canon, variants in KEYWORD_NORMALIZE.items():
                if subject_matches(variants, title=title, place=place, area=area, subject_field=sfield):
                    bins[canon][bi] += 1
    except Exception:
        import traceback
        print(f"[ERROR] subjects_in_peak_near: {traceback.format_exc()}", flush=True)
        return []
    out = []
    for canon, bc in bins.items():
        peaks = compute_peaks(bc)
        if not peaks:
            continue
        for c in peaks:
            if min((cur_bin - c) % 36, (c - cur_bin) % 36) <= 1:  # 現在が見頃クラスタの±1旬以内
                out.append((canon, peaks_text(peaks), sum(bc.values())))
                break
    out.sort(key=lambda x: -x[2])
    return out


def expand_pref_name(s):
    """短縮県名を正式名に展開（例: 東京→東京都、大阪→大阪府、北海道→北海道）"""
    s = str(s or '').strip()
    if not s:
        return ''
    for full in PREF_LATLNG:
        short = re.sub(r'[都府県]$', '', full)
        if s == full or s == short:
            return full
    return s

def build_carousel_bubble(item, label_emoji, area_note="", matched_kw=None):
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
            "aspectMode": "cover",
            "action": {
                "type": "uri",
                "uri": item['url']
            }
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
                    "text": (f"{item['title']} {item['period']}" if item.get('period') else item['title']),
                    "size": "sm",
                    "margin": "sm",
                    "wrap": True,
                    "color": "#444444"
                },
                {
                    "type": "text",
                    "text": (f"{item['winner']}（{expand_pref_name(item.get('winner_area',''))}）" if item.get('winner_area') else f"{item['winner']}"),
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
            ] + ([{
                    "type": "text",
                    "text": f"🔍 '{matched_kw}'を含む",
                    "size": "xs",
                    "color": "#aaaaaa",
                    "margin": "xs"
                }] if matched_kw else [])
        },
        "footer": {
            "type": "box",
            "layout": "horizontal",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "詳細情報",
                        "data": f"action=detail&pic={item['pic']}&dnumb={item.get('dnumb', '')}"
                    }
                },
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


def build_info_bubble(text):
    """カルーセル先頭に置く説明バブル。テキストがカードと一緒に必ず表示されるようにする。"""
    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "justifyContent": "center",
            "spacing": "md",
            "paddingAll": "20px",
            "contents": [
                {"type": "text", "text": "📷 風景写真コンシェルジュ", "size": "md", "weight": "bold", "color": "#1DB446"},
                {"type": "separator", "margin": "md"},
                {"type": "text", "text": text, "wrap": True, "size": "xl", "weight": "bold", "color": "#222222", "margin": "lg"},
                {"type": "text", "text": "→ 右にスワイプ", "size": "sm", "color": "#AAAAAA", "margin": "lg", "align": "end"},
            ],
        },
    }


def reply_with_carousel(reply_token, head_text, results, alt_text="撮影地のご提案"):
    """説明文をカルーセルの先頭バブルに入れて返信する(テキストが画面外に流れて見落とされるのを防ぐ)。"""
    bubbles = [build_carousel_bubble(it, e, l, matched_kw=it.get('matched_kw')) for e, l, it in results]
    if head_text:
        bubbles = [build_info_bubble(head_text)] + bubbles
    carousel = FlexSendMessage(
        alt_text=alt_text,
        contents={"type": "carousel", "contents": bubbles},
        quick_reply=feedback_quick_reply(),
    )
    line_bot_api.reply_message(reply_token, carousel)


def format_published(pub):
    if not pub:
        return ''
    import re
    if re.match(r'^\d{4}N$', pub):
        return f"{pub[:4]}年風景写真祭入選作品"
    m = re.match(r'^(\d{4})(\d{2})(\d{2})$', pub)
    if m:
        year, m1, m2 = m.group(1), int(m.group(2)), int(m.group(3))
        if m2 == 0:
            return f"{year}年{m1}月号"
        else:
            return f"風景写真{year}年{m1}-{m2}月号"
    return pub

def normalize_award(award):
    if not award:
        return ''
    a = award.strip()
    title = 'タイトル賞' if 'タイトル' in a else ''
    if '最優秀' in a:
        base = '最優秀作品賞'
    elif '準優秀' in a or '準優勝' in a:
        base = '準優秀作品賞'
    elif '優秀' in a:
        base = '優秀作品賞'
    elif '佳作' in a:
        base = '佳作'
    elif '秀作' in a:
        base = '秀作'
    elif '奨励' in a:
        base = '奨励賞'
    else:
        base = a.split()[0] if a else ''
    return f"{base}　{title}".strip() if title else base

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
                # 注: 以前は市区町村以外のバラ地名(例:「志賀高原」)も登録していたが、
                # それらは地点名検索(search_by_place)に回すため、ここでは登録しない。
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
    city = format_loc_city(getattr(event.message, 'address', '') or '')
    hydrate_user(user_id)
    save_user_location(user_id, lat, lng, city)
    where = f"現在地（{city}）" if city else "現在地"
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=f"{where}を登録しました。この場所を起点に撮影地をご提案します。\n撮影したい日程や地域があればお知らせください。")
    )
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):

    reply_token = event.reply_token

    # 即座に「お待ちください」を送信
    user_id = event.source.user_id
    # Firestoreに保存済みのユーザー情報(位置・初回フラグ)をメモリへ復元
    hydrate_user(user_id)
    # 「使い方」「ヘルプ」でいつでも案内を表示
    if event.message.text.strip() in ("使い方", "つかいかた", "ヘルプ", "help", "Help"):
        line_bot_api.reply_message(reply_token, [TextSendMessage(text=t) for t in usage_guide_messages()])
        return
    # データ削除コマンド(同意の撤回・記録消去)。検索として記録される前に処理する
    if event.message.text.strip() in ("データ削除", "データ消去", "記録削除"):
        delete_user_data(user_id)
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text="あなたの記録(検索された言葉・ご提案への評価・登録された位置情報)をすべて削除しました。\nご協力ありがとうございました。またいつでもご利用いただけます。")
        )
        return
    try:
        line_bot_api.push_message(user_id, TextSendMessage(text="少々お待ちください。今旬の撮影地を探しております。🔍"))
    except:
        pass

    try:

        user_message = event.message.text.strip()
        # 利用状況の観察用に記録(制限はかけない)
        record_search(user_id, user_message)
        # 初回メッセージ時に歓迎＋使い方を案内
        if user_id not in USER_SEEN:
            mark_user_seen(user_id)
            from linebot.models import TextSendMessage as TSM
            line_bot_api.push_message(user_id, TSM(text="ようこそ風景写真コンシェルジュの部屋へ。ここでは『風景写真』の誌面を飾った数々の傑作とその生まれた場所へと皆さんをご案内します。"))
            line_bot_api.push_message(user_id, [TSM(text=t) for t in usage_guide_messages()])

        # 地域＋被写体が0件だったときの選択（1.条件を広げる 2.全国 3.戻る）
        if user_id in SUBJECT_PENDING:
            sp = SUBJECT_PENDING[user_id]
            ch = user_message.strip()
            if ch in ("1", "１"):
                del SUBJECT_PENDING[user_id]
                rr = search_by_place([], base_date=sp['date'], origin_latlng=sp['origin_latlng'],
                                     origin_name=sp['origin_name'], subject=sp['subject'],
                                     center_latlng=sp['place_latlng'], radius_km=100)
                if rr['status'] == 'not_found' or not rr['results']:
                    line_bot_api.reply_message(reply_token, TextSendMessage(
                        text=f"「{sp['place_disp']}」の周辺（約100km）にも{sp['subject']}の作品が見つかりませんでした。全国で探す場合はもう一度「{sp['place_disp']} {sp['subject']}」と送って2をお選びください。"))
                    return
                reply_with_carousel(reply_token, f"「{sp['place_disp']}」の周辺（約100km）で{sp['subject']}の作品をご紹介します。", rr['results'])
                return
            elif ch in ("2", "２"):
                del SUBJECT_PENDING[user_id]
                prn = search_by_place([], base_date=sp['date'], origin_latlng=sp['origin_latlng'], origin_name=sp['origin_name'], subject=sp['subject'])
                if prn['status'] == 'not_found':
                    line_bot_api.reply_message(reply_token, TextSendMessage(text=f"全国でも{sp['subject']}の作品が見つかりませんでした。"))
                    return
                speaks = prn.get('peaks', [])
                if sp['subject'] in SEASONAL_SUBJECTS and speaks:
                    head = f"全国の{sp['subject']}の作品です（見頃は{peaks_text(speaks)}ごろ）。"
                else:
                    head = f"全国の{sp['subject']}の作品をご紹介します。"
                reply_with_carousel(reply_token, head, prn['results'])
                return
            elif ch in ("3", "３", "戻る", "もどる"):
                del SUBJECT_PENDING[user_id]
                line_bot_api.reply_message(reply_token, TextSendMessage(text="承知しました。地域名や被写体（例：弘前 桜）をお知らせください。"))
                return
            else:
                del SUBJECT_PENDING[user_id]  # 番号以外は新規クエリとして続行

        # 検索拡張の回答処理
        if user_id in EXPAND_PENDING:
            pending = EXPAND_PENDING[user_id]
            choice = user_message.strip()
            if choice in ['4', '４']:
                del EXPAND_PENDING[user_id]
                line_bot_api.reply_message(reply_token, TextSendMessage(text="別の地域やキーワードを入力してください。"))
                return
            del EXPAND_PENDING[user_id]
            expand_time = choice in ['1', '１', '3', '３']
            expand_area = choice in ['2', '２', '3', '３']
            new_radius = 300 if expand_area else 150
            _eu = USER_LOCATION.get(user_id)
            _eo = (_eu["lat"], _eu["lng"]) if _eu else None
            _en = (_eu.get("city") or "現在地") if _eu else DEFAULT_ORIGIN_NAME
            results = select_three_points(
                base_date=pending['date'],
                base_latlng=pending['latlng'],
                radius=new_radius,
                place_name=pending['display'],
                keyword=pending['keyword'],
                expand_time=expand_time,
                origin_latlng=_eo,
                origin_name=_en,
            )
            if not results or isinstance(results, tuple):
                line_bot_api.reply_message(reply_token, TextSendMessage(text="条件を広げても見つかりませんでした。別の地域やキーワードをお試しください。"))
                return
            reply_with_carousel(reply_token, "条件を広げて探しました。こんなところはいかがでしょう。", results)
            return

        # ── 便利コマンド ──
        # 「<被写体>現在地<半径>」(例: アジサイ現在地100) / 「見頃<半径>」(例: 見頃150)
        _u = USER_LOCATION.get(user_id)
        _ccenter = (_u["lat"], _u["lng"]) if _u else SHINJUKU
        _cname = (_u.get("city") or "現在地") if _u else "東京"
        _co = (_u["lat"], _u["lng"]) if _u else None
        _con = (_u.get("city") or "現在地") if _u else DEFAULT_ORIGIN_NAME

        m_now = re.match(r'^\s*(.+?)\s*現在地\s*(\d+)\s*(?:km|キロ\S*)?\s*$', user_message)
        if m_now:
            subj_txt, radius = m_now.group(1), max(5, min(int(m_now.group(2)), 2000))
            _cs = None
            for canon, variants in KEYWORD_NORMALIZE.items():
                if any(v in subj_txt for v in variants):
                    _cs = canon
                    break
            if _cs:
                rr = search_by_place([], base_date=date.today(), origin_latlng=_co, origin_name=_con,
                                     subject=_cs, center_latlng=_ccenter, radius_km=radius)
                if rr['status'] == 'not_found' or not rr['results']:
                    line_bot_api.reply_message(reply_token, TextSendMessage(
                        text=f"{_cname}から半径{radius}km圏内に{_cs}の作品が見つかりませんでした。半径を広げてお試しください。"))
                    return
                speaks = rr.get('peaks', [])
                if _cs in SEASONAL_SUBJECTS and speaks:
                    head = f"{_cname}から半径{radius}km圏内の{_cs}の作品です（見頃は{peaks_text(speaks)}ごろ）。近い順にご紹介します。"
                else:
                    head = f"{_cname}から半径{radius}km圏内の{_cs}の作品を近い順にご紹介します。"
                reply_with_carousel(reply_token, head, rr['results'])
                return
            # 被写体が認識できなければ通常処理へフォールスルー

        m_peak = re.match(r'^\s*見頃\s*(\d+)?\s*(?:km|キロ\S*)?\s*$', user_message)
        if m_peak:
            radius = max(5, min(int(m_peak.group(1) or 100), 2000))
            lst = subjects_in_peak_near(_ccenter, radius, date.today())
            if not lst:
                line_bot_api.reply_message(reply_token, TextSendMessage(
                    text=f"{_cname}から半径{radius}km圏内では、今が見頃の被写体が見つかりませんでした。半径を広げてお試しください。"))
                return
            lines = "\n".join(f"・{s}（見頃 {pk}・{n}件）" for s, pk, n in lst[:12])
            line_bot_api.reply_message(reply_token, TextSendMessage(
                text=f"{_cname}から半径{radius}km圏内で、今が見頃の被写体です。\n{lines}\n\n気になる被写体名を送ると撮影地をご案内します。"))
            return

        # 自宅(帰路の基準点)の登録: 「自宅 川越市」「帰宅先 ○○」
        m_home = re.match(r'^\s*(?:自宅|帰宅先|帰路先)\s*[:：]?\s*(.+?)\s*$', user_message)
        if m_home:
            hname = m_home.group(1).strip()
            hll = geocode(hname)
            if not hll:
                _an, _all, _ad = parse_target_area(hname)
                if _all:
                    hll = _all
            if not hll:
                line_bot_api.reply_message(reply_token, TextSendMessage(text=f"「{hname}」の場所が特定できませんでした。市区町村名でお試しください（例：自宅 川越市）。"))
                return
            save_user_home(user_id, hll[0], hll[1], hname)
            line_bot_api.reply_message(reply_token, TextSendMessage(text=f"自宅を「{hname}」に登録しました。『現在地R150』のように送ると、現在地から{hname}方向（帰路）で半径150km圏内の撮影地を寄り道の少ない順にご案内します。"))
            return

        # 「[被写体]R<半径>」(例: 現在地R150 / アジサイR150) → 現在地から自宅方向(帰路)で半径内を検索
        m_route = re.match(r'^\s*(.*?)[RＲｒr]\s*(\d+)\s*(?:km|キロ\S*)?\s*$', user_message)
        if m_route and ('R' in user_message.upper().replace('Ｒ', 'R')):
            pre, radius = m_route.group(1), max(5, min(int(m_route.group(2)), 2000))
            if not _u:
                line_bot_api.reply_message(reply_token, TextSendMessage(text="現在地が分からないため帰路方向を計算できません。先にLINEの位置情報を送ってから『現在地R150』とお試しください。"))
                return
            _cs = None
            for canon, variants in KEYWORD_NORMALIZE.items():
                if any(v in pre for v in variants):
                    _cs = canon
                    break
            _hu = USER_HOME.get(user_id)
            home_ll = (_hu["lat"], _hu["lng"]) if _hu else SHINJUKU
            home_nm = (_hu.get("name") if _hu else None) or "東京（自宅未登録）"
            rr = search_by_place([], base_date=date.today(), origin_latlng=_co, origin_name=_con,
                                 subject=_cs, center_latlng=_ccenter, radius_km=radius, home_latlng=home_ll)
            if rr['status'] == 'not_found' or not rr['results']:
                line_bot_api.reply_message(reply_token, TextSendMessage(
                    text=f"{_cname}から{home_nm}方向・半径{radius}km圏内に{(_cs or '撮影地')}が見つかりませんでした。半径を広げてお試しください。"))
                return
            subj_txt = (_cs + "の") if _cs else ""
            reply_with_carousel(reply_token, f"{_cname}から{home_nm}方向（帰路）・半径{radius}km圏内の{subj_txt}撮影地を、寄り道の少ない順にご紹介します。", rr['results'])
            return

        # 「[被写体]<地名><半径>」(例: 美瑛150 / 弘前 桜 100 / 美瑛 ひまわり 150)
        #  → その地名を中心に半径内の「今の時期に撮れる」撮影地を近い順に。地名が解決できる場合のみ発動。
        m_pl = re.match(r'^\s*(.+?)\s*(\d{2,4})\s*(?:km|キロ\S*)?\s*$', user_message)
        if m_pl:
            body, radius = m_pl.group(1), max(10, min(int(m_pl.group(2)), 2000))
            _cs = None
            for canon, variants in KEYWORD_NORMALIZE.items():
                if any(v in body for v in variants):
                    _cs = canon
                    for v in variants:
                        body = body.replace(v, ' ')
                    break
            place_txt = re.sub(r'[、,。.・/／｜|\s　]+', ' ', body)
            place_txt = re.sub(r'現在地', ' ', place_txt).strip()
            center = center_name = None
            if len(place_txt) >= 2:
                _an, _all, _ad = parse_target_area(place_txt)
                if _all and _an not in (None, "AMBIGUOUS"):
                    center, center_name = _all, (_ad or place_txt)
                else:
                    g = geocode(place_txt)
                    if g:
                        center, center_name = g, place_txt
            if center is None and not place_txt and _cs and radius <= 999:
                center, center_name = _ccenter, _cname  # 地名なし＋被写体 → 現在地中心(年号誤認回避のため999km以下)
            if center is not None:  # 地名が解決できたときだけコマンドとして処理
                rr = search_by_place([], base_date=date.today(), origin_latlng=_co, origin_name=_con,
                                     subject=_cs, center_latlng=center, radius_km=radius)
                if rr['status'] == 'not_found' or not rr['results']:
                    line_bot_api.reply_message(reply_token, TextSendMessage(
                        text=f"{center_name}から半径{radius}km圏内に{(_cs or '撮影地')}が見つかりませんでした。半径を広げてお試しください。"))
                    return
                subj_txt = (_cs + "の") if _cs else ""
                speaks = rr.get('peaks', [])
                if rr['status'] == 'in_season':
                    head = f"{center_name}から半径{radius}km圏内で、今の時期に撮れる{subj_txt}撮影地を近い順にご紹介します。"
                elif _cs in SEASONAL_SUBJECTS and speaks:
                    head = f"{center_name}から半径{radius}km圏内は、今の時期の{subj_txt}作品が少なめです（{_cs}の見頃は{peaks_text(speaks)}ごろ）。これまでの作品を近い順にご紹介します。"
                else:
                    head = f"{center_name}から半径{radius}km圏内は、今の時期の作品が少なめでした。これまでの{subj_txt}作品を近い順にご紹介します。"
                reply_with_carousel(reply_token, head, rr['results'])
                return
            # 地名が解決できなければ通常処理へフォールスルー

        # 問い返し待ちの回答処理
        if user_id in AMBIGUOUS_PENDING:
            pending = AMBIGUOUS_PENDING[user_id]
            prefs = pending["prefs"]
            city = pending["city"]
            kw_option = pending.get('kw_option')
            kw_num = str(len(prefs) + 1)
            choice = user_message.strip()
            resolved_pref = None
            if choice in ("1", "１") and prefs:
                resolved_pref = prefs[0]
            elif choice in ("2", "２") and len(prefs) >= 2:
                resolved_pref = prefs[1]
            else:
                for p in prefs:
                    short = p.replace("県", "").replace("都", "").replace("府", "").replace("道", "")
                    if p in user_message or short in user_message:
                        resolved_pref = p
                        break
            if kw_option and choice == kw_num:
                # 被写体候補を選択
                del AMBIGUOUS_PENDING[user_id]
                search_keyword = kw_option[0]
                target_date = parse_target_date(user_message)
                area_name, area_latlng, area_display = None, None, None
            elif resolved_pref:
                # 地域を確定（番号や県名で選択）
                del AMBIGUOUS_PENDING[user_id]
                latlng = geocode(f"{resolved_pref}{city}") or CITY_TO_LATLNG.get(city) or PREF_LATLNG.get(resolved_pref)
                target_date = parse_target_date(user_message)
                area_name, area_latlng, area_display = resolved_pref, latlng, city
            else:
                # 番号でも県名でもない → 新規クエリとして処理
                del AMBIGUOUS_PENDING[user_id]
                target_date = parse_target_date(user_message)
                area_name, area_latlng, area_display = parse_target_area(user_message)
        else:
            target_date = parse_target_date(user_message)
            area_name, area_latlng, area_display = parse_target_area(user_message)
        # キーワード正規化辞書
        # キーワード抽出（正規化辞書を使用）
        search_keyword = None
        if not (area_name and area_name not in [None, 'AMBIGUOUS']):
            for canonical, variants in KEYWORD_NORMALIZE.items():
                if any(v in user_message for v in variants):
                    search_keyword = canonical
                    break
        # 「地域名＋被写体」(例: 吉野山 桜 / 奈良、京都 滝 / 青森県 紅葉) → その地域・被写体で絞り込む。
        # 同名地名の問い返しより前に処理（被写体があれば地名はその語で直接検索でき、問い返し不要）。
        _subj = None
        for _canon, _vars in KEYWORD_NORMALIZE.items():
            if any(v in user_message for v in _vars):
                _subj = _canon
                break
        if _subj:
            txt = user_message
            for v in KEYWORD_NORMALIZE.get(_subj, []):
                txt = txt.replace(v, ' ')
            txt = re.sub(r'(見頃|みごろ|時期|いつ|頃|ごろ)', ' ', txt)
            txt = re.sub(r'\d{1,2}月\d{0,2}日?|\d+日後|明日|あした|明後日|あさって|今日|本日|来週末|今週末|来週|今週|週末', ' ', txt)
            txt = re.sub(r'[、,。.・/／｜|\s　]+', ' ', txt)
            place_terms = []
            for tok in txt.split():
                tok = re.sub(r'^[のはをがでとへもに]+|[のはをがでとへもに]+$', '', tok).strip()
                if len(tok) >= 2:
                    place_terms.append(tok)
            place_terms = list(dict.fromkeys(place_terms))  # 重複除去・順序維持
            _u = USER_LOCATION.get(user_id)
            _ol = (_u["lat"], _u["lng"]) if _u else None
            _on = (_u.get("city") or "現在地") if _u else DEFAULT_ORIGIN_NAME
            place_disp = "・".join(place_terms)
            # ① 地域＋被写体
            if place_terms:
                pr = search_by_place(place_terms, base_date=target_date, origin_latlng=_ol, origin_name=_on, subject=_subj)
                if pr['status'] != 'not_found':
                    speaks = pr.get('peaks', [])
                    if _subj in SEASONAL_SUBJECTS and speaks:
                        shead = f"「{place_disp}」の{_subj}の見頃は{peaks_text(speaks)}ごろのようです。これまでの作品をご紹介します。"
                    elif pr['status'] == 'off_season':
                        shead = f"「{place_disp}」の{_subj}は今の時期の作品が見当たらず、これまでの作品をご紹介します。"
                    else:
                        shead = f"「{place_disp}」の{_subj}の撮影地はこちらです。"
                    reply_with_carousel(reply_token, shead, pr['results'])
                    return
                # 0件 → 「見つかりませんでした」と伝えたうえで選択肢を提示
                SUBJECT_PENDING[user_id] = {
                    'subject': _subj, 'place_disp': place_disp,
                    'place_latlng': area_latlng or geocode(place_terms[0]),
                    'date': target_date, 'origin_latlng': _ol, 'origin_name': _on,
                }
                line_bot_api.reply_message(reply_token, TextSendMessage(
                    text=(f"「{place_disp}」では{_subj}の作品が見つかりませんでした。\nどうしますか？\n"
                          f"1. 条件を広げて探す（期間と距離）\n2. 全国で探す\n3. 戻る")))
                return
            # 地名なしの被写体のみ → 現在地(既定は東京)中心・約100kmで探し、近くに無ければ全国
            center = _ol or SHINJUKU
            prn = search_by_place([], base_date=target_date, origin_latlng=_ol, origin_name=_on, subject=_subj, center_latlng=center, radius_km=100)
            if prn['status'] != 'not_found' and prn['results']:
                speaks = prn.get('peaks', [])
                near_name = _on if _ol else "東京"
                if _subj in SEASONAL_SUBJECTS and speaks:
                    shead = f"{near_name}周辺の{_subj}の作品です（見頃は{peaks_text(speaks)}ごろ）。"
                else:
                    shead = f"{near_name}周辺の{_subj}の作品をご紹介します。"
                reply_with_carousel(reply_token, shead, prn['results'])
                return
            prn = search_by_place([], base_date=target_date, origin_latlng=_ol, origin_name=_on, subject=_subj)
            if prn['status'] != 'not_found':
                speaks = prn.get('peaks', [])
                if _subj in SEASONAL_SUBJECTS and speaks:
                    shead = f"近くには見当たらないため、全国の{_subj}の作品です（見頃は{peaks_text(speaks)}ごろ）。"
                else:
                    shead = f"近くには見当たらないため、全国の{_subj}の作品をご紹介します。"
                reply_with_carousel(reply_token, shead, prn['results'])
                return
            # 被写体でも全く該当が無ければ通常フローへフォールスルー

        # 同名地名の問い返し
        if area_name == "AMBIGUOUS":
            prefs = CITY_TO_PREF_MULTI.get(area_display, [])
            # キーワード候補があるか確認
            keyword_variants = {
                '朝日': ('朝焼け', '朝日（風景・被写体）'),
                '桜': ('桜', '桜（花）'),
            }
            kw_option = keyword_variants.get(area_display) or keyword_variants.get(re.sub(r'[市区町村郡]', '', area_display).strip())
            AMBIGUOUS_PENDING[user_id] = {"city": area_display, "prefs": prefs, "kw_option": kw_option}
            msg = TextSendMessage(
                text=f"{area_display}は複数の地域にあります。\n" + "\n".join(f"{i+1}．{p}{area_display}" for i, p in enumerate(prefs)) + (f"\n{len(prefs)+1}．{kw_option[1]}" if kw_option else "") + "\n\n番号でお答えください。"
            )
            line_bot_api.reply_message(reply_token, msg)
            return

        city_specified = any(c in user_message for c in ["市","町","村","区","郡"])

        # 地域・キーワードに解決できない具体的な語は「地点名検索」を試みる(無関係な全国結果を出さない)
        place_query = None
        if not area_name and not search_keyword and not city_specified:
            residual = user_message.strip()
            for w in ['明日','あした','明後日','あさって','今日','本日','今週末','来週末','来週','今週','週末']:
                residual = residual.replace(w, '')
            residual = re.sub(r'\d+日後', '', residual)
            residual = re.sub(r'\d{1,2}月\d{1,2}日', '', residual)
            residual = re.sub(r'\d{1,2}月', '', residual)
            residual = residual.strip()
            if len(residual) >= 2:
                place_query = residual
        # 距離の起点: 現在地(あれば市区町村名つき) / なければ新宿区。検索中心とは独立。
        _uloc = USER_LOCATION.get(user_id)
        if _uloc:
            origin_latlng = (_uloc["lat"], _uloc["lng"])
            origin_name = _uloc.get("city") or "現在地"
        else:
            origin_latlng = None
            origin_name = DEFAULT_ORIGIN_NAME

        if place_query:
            pr = search_by_place(place_query, base_date=target_date, origin_latlng=origin_latlng, origin_name=origin_name)
            if pr['status'] == 'not_found':
                line_bot_api.reply_message(reply_token, TextSendMessage(
                    text=f"「{place_query}」に合う撮影地は見つかりませんでした。\n地域名(県名・市町村名)や被写体(滝・桜・紅葉・星空など)でもお試しください。"))
                return
            results = pr['results']
            if pr['status'] == 'in_season':
                head = f"「{place_query}」の今の時期の撮影地はこちらです。"
            else:
                cur = f"{target_date.month}月{junkun(target_date.day) or ''}"
                peaks = [c for c in pr.get('peaks', []) if (c // 3 + 1) != target_date.month]
                if peaks:
                    head = (f"「{place_query}」は今の時期（{cur}）の作品が少ないようです。"
                            f"見頃は{peaks_text(peaks)}あたり。参考にこれまでの作品をご紹介します。")
                else:
                    head = f"「{place_query}」は今の時期の作品が見つかりませんでしたが、これまでの作品をご紹介します。"
            reply_with_carousel(reply_token, head, results)
            return


        # CITY_TO_PREFでヒットした場合（市町村名指定）はWIDE_PREFSスキップ
        city_from_dict = any(city in user_message or re.sub(r'[市区町村郡]', '', city) in user_message for city in CITY_TO_PREF)
        _radius = 150 if (city_specified or city_from_dict) else (300 if search_keyword else None)

        if area_name and area_name in WIDE_PREFS and not city_specified and not city_from_dict:
            msg = TextSendMessage(
                text=f"{area_name[:-1]}ですか。それは楽しみですね。どのあたりに行かれますか？市町村名や地域名を教えていただけますか。"
            )
            line_bot_api.reply_message(reply_token, msg)
            return
        if area_latlng is None and user_id in USER_LOCATION:
            loc = USER_LOCATION[user_id]
            area_latlng = (loc["lat"], loc["lng"])
            if not area_display:
                area_display = "現在地"
        elif area_latlng is None:
            pass  # 位置情報未登録時は何も言わない
        target_city = area_display if (city_specified or city_from_dict) else None
        results = select_three_points(base_date=target_date, base_latlng=area_latlng, radius=_radius, place_name=area_display, keyword=search_keyword, target_city=target_city, origin_latlng=origin_latlng, origin_name=origin_name)
        if isinstance(results, tuple) and results[0] == 'CITY':
            _, city_base, city_count, results = results
            if not results:
                line_bot_api.reply_message(reply_token, TextSendMessage(
                    text=f"{target_date.month}月{target_date.day}日の前後で{city_base}とその周辺を調べましたが、該当する作品が見つかりませんでした。\n時期や地域を変えてお試しください。"))
                return
            if city_count == 0:
                head = f"{target_date.month}月{target_date.day}日の前後で{city_base}を調べましたが該当はありませんでした。{city_base}周辺の候補をご紹介します。"
            elif city_count <= 3:
                head = f"{target_date.month}月{target_date.day}日の前後で{city_base}で調べたところ該当は{city_count}件でした。周辺の候補も合わせて表示します。"
            else:
                head = f"{city_base}の今の時期の撮影地はこちらです。"
            reply_with_carousel(reply_token, head, results)
            return
        if isinstance(results, tuple) and results[0] == 'TOO_FEW':
            _, found_pref, count = results
            EXPAND_PENDING[user_id] = {
                'pref': found_pref,
                'date': target_date,
                'latlng': area_latlng,
                'display': area_display,
                'keyword': search_keyword,
            }
            msg = TextSendMessage(
                text=f"{found_pref}の今の時期の作品が少ししか見つかりません（{count}件）。\nどうしますか？\n1. 時期を広げて探す\n2. 近隣地域も含めて探す\n3. 両方広げて探す\n4. やめる（別の条件で探す）"
            )
            line_bot_api.reply_message(reply_token, msg)
            return
        if not results:
            results = []
        masterpiece = results[0][2] if results else None
        near = results[1][2] if len(results) > 1 else None


        if not masterpiece or not near:
            msg = TextSendMessage(
                text="今の時期にぴったりの作品が見つかりませんでした。\n地域名やキーワード（例：滝、桜、紅葉）を変えてもう一度お試しください。位置情報を登録していただくと、お近くの撮影地もご提案できます。"
            )
            line_bot_api.reply_message(reply_token, msg)
            return

        _date_specified = any(w in user_message for w in ['明日','明後日','今日','来週','週末','月','日後'])
        reply_with_carousel(
            reply_token,
            build_greeting(target_date, area_display, date_specified=_date_specified),
            results,
            alt_text="風景写真コンシェルジュ・今日の3選",
        )


    except Exception as e:
        import traceback
        err = traceback.format_exc()
        sys.stderr.write(f"[ERROR] Exception in handle_message: {err}\n")
        try:
            msg = TextSendMessage(
                text="申し訳ございません。処理中にエラーが発生しました。"
            )
            line_bot_api.reply_message(reply_token, msg)
        except:
            pass

@handler.default()
def handle_default(event):
    """テキスト・位置情報・ポストバック以外(スタンプ・画像・友だち追加など)の
    フォールバック。SDK 2.4.3 では未対応イベントは _default に回る。
    返信できるイベント(reply_tokenあり)にだけ、使い方をやさしく案内する。"""
    reply_token = getattr(event, 'reply_token', None)
    if not reply_token:
        return  # Unfollow等、返信トークンが無いイベントは何もしない
    try:
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text="ありがとうございます。撮影したい『地域名』や『日程』、被写体の『キーワード』をテキストで送っていただくと、その場所にちなんだ作品をご提案します。\n例：「宮城県」「来週末 北海道」「滝」")
        )
    except Exception as e:
        print(f"[ERROR] handle_default error: {e}", flush=True)

@handler.add(PostbackEvent)
def handle_postback(event):
    reply_token = event.reply_token

    try:
        data = event.postback.data
        params = dict(item.split('=') for item in data.split('&'))
        action = params.get('action')
        pic_filename = params.get('pic', '')

        if action == 'feedback':
            rating = params.get('rating', '')
            user_id = event.source.user_id
            last_query = ''
            if db:
                try:
                    snap = db.collection('Users').document(user_id).get()
                    if snap.exists:
                        last_query = (snap.to_dict() or {}).get('last_query', '')
                    db.collection('Feedback').add({
                        "user_id": user_id,
                        "rating": rating,
                        "query": last_query,
                        "ts": firestore.SERVER_TIMESTAMP,
                    })
                except Exception:
                    import traceback
                    print(f"[ERROR] feedback save failed: {traceback.format_exc()}", flush=True)
            line_bot_api.reply_message(reply_token, TextSendMessage(text="ありがとうございます。いただいた声は今後のご提案の参考にいたします。"))
            return

        if action == 'detail':
            # Master_Photosから写真情報を取得
            photo_data = None
            if db:
                dnumb = params.get('dnumb', '')
                if dnumb:
                    docs = db.collection('Master_Photos').where('dNumb', '==', dnumb).limit(1).stream()
                else:
                    docs = db.collection('Master_Photos').where('PicFileName', '==', pic_filename).limit(1).stream()
                for doc in docs:
                    photo_data = doc.to_dict()
                    break

            if not photo_data:
                line_bot_api.reply_message(reply_token, TextSendMessage(text="詳細情報が見つかりませんでした。"))
            else:
                # Location masterから地域情報を取得
                loc_data = None
                dnumb = str(photo_data.get('dNumb', ''))
                if db and dnumb:
                    loc_docs = db.collection('Location master').where('Related_dNumb', '==', dnumb).limit(1).stream()
                    for doc in loc_docs:
                        loc_data = doc.to_dict()
                        break

                # 作品情報テキスト組み立て
                lines = []
                lines.append(f"📸 {photo_data.get('Title', '')}")
                if photo_data.get('SubTitle'):
                    lines.append(f"　{photo_data.get('SubTitle')}")
                lines.append(f"\n📍 {photo_data.get('Area', '')}")
                if photo_data.get('Place'):
                    lines.append(f"　{photo_data.get('Place')}")
                lines.append(f"\n👤 {photo_data.get('Winner', '')}")
                if photo_data.get('AwardRank'):
                    lines.append(f"🏅 {normalize_award(photo_data.get('AwardRank'))}")
                if photo_data.get('Published'):
                    lines.append(f"📖 {format_published(photo_data.get('Published', ''))}")
                if photo_data.get('Selection Comments'):
                    judge = photo_data.get('Judge', '')
                    comment = photo_data.get('Selection Comments', '')
                    lines.append(f'\n［選評］\n{comment}\n（{judge}）')

                if loc_data:
                    lines.append(f"\n━━━━━━━━━━")
                    lines.append(f"🗺 撮影地情報")
                    if loc_data.get('Best_Season'):
                        lines.append(f"🌸 ベストシーズン: {loc_data.get('Best_Season')}")
                    if loc_data.get('Best_Time'):
                        lines.append(f"🕐 ベスト時間: {loc_data.get('Best_Time')}")
                    if loc_data.get('Lighting'):
                        lines.append(f"💡 光の条件: {loc_data.get('Lighting')}")
                    if loc_data.get('Lens_Selection'):
                        lines.append(f"📷 レンズ: {loc_data.get('Lens_Selection')}")
                    if loc_data.get('Point_Description'):
                        lines.append(f"\n📝 ポイント\n{loc_data.get('Point_Description')}")
                    if loc_data.get('Access_Info'):
                        lines.append(f"\n🚗 アクセス・装備\n{loc_data.get('Access_Info')}")

                # MapLinkはカルーセルのマップボタンと同じため省略

                text = "\n".join(lines)
                # LINEのテキストメッセージは5000文字まで
                if len(text) > 4900:
                    text = text[:4900] + "..."
                line_bot_api.reply_message(reply_token, TextSendMessage(text=text))

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
