# -*- coding: utf-8 -*-
"""
風景写真コンシェルジュ 完全版 v2
仕様書に完全準拠。3分類選定×乱数×除外2系統×LINE Flex カルーセル×postback

LINE v2 import, Firestore Master_Photos 正本読み込み、
旬×250km×画像あり×除外をすべてクリアした母集合から
【傑作ポイント】【近場で楽しむ】【注目のポイント】を各枠ランダム選出し、
本物写真(閲覧用URL)付きカルーセルで爆射する。
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
from linebot.models import MessageEvent, TextMessage, PostbackEvent, TextSendMessage, FlexSendMessage
from linebot.exceptions import InvalidSignatureError
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
    """Area → 都道府県名（化け県名救済＆表記ゆれ救済）"""
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
    """日 → 上旬/中旬/下旬"""
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
    """2点間距離(km)"""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    h = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlmb/2)**2
    return 2 * R * math.asin(math.sqrt(h))

def half_month_window(base_date):
    """基準日 → 前5後10の(月,旬)ペア集合"""
    pairs = set()
    for delta in range(-5, 11):
        d = base_date + timedelta(days=delta)
        pairs.add((d.month, junkun(d.day)))
    return pairs

def view_image_url(published, pic_filename):
    """画像URL組み立て（閲覧用・透かし入り）"""
    return "/".join([SERVER_BASE, VIEW_DIR, str(published)[:4], str(published), str(pic_filename)])

def has_valid_image(pic_filename):
    """画像欠損チェック"""
    fn = str(pic_filename or '').strip()
    return fn and fn not in ('なし.jpg', 'default.jpg', 'なし', 'none', '')

def calc_award_score(award_rank):
    """賞ランク → スコア"""
    r = str(award_rank or '').strip()
    for k, v in AWARD_SCORE.items():
        if k in r:
            return v
    return 10 if r else 0

def load_exclusions():
    """設定から除外2系統を読む"""
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
    """Area/Place が立入禁止リストに引っかかるか"""
    if not blocked_list:
        return False
    s = str(place or '') + ' ' + str(area or '')
    return any(b and b in s for b in blocked_list)

# ──────────────── 3分類選定エンジン ────────────────
def select_three_points():
    """
    明日の旬×東京250km圏内から、3分類(傑作/近場/注目)を選定
    """

    if not db:
        sys.stderr.write(f"[DEBUG] select_three_points: db={db}\n")
        return None, None, None

    excl_authors, blocked_areas = load_exclusions()
    tomorrow = date.today() + timedelta(days=1)
    junkun_window = half_month_window(tomorrow)
    tokyo = PREF_LATLNG["東京都"]

    pool = []
    place_years = defaultdict(list)

    # 母集合構築
    for doc in db.collection('Master_Photos').stream():
        d = doc.to_dict()

        # 時間軸フィルタ
        try:
            mo = int(d.get('Month'))
        except:
            continue
        if (mo, junkun(d.get('Day'))) not in junkun_window:
            continue

        # 空間軸フィルタ
        pref = extract_pref(d.get('Area'))
        if not pref:
            continue
        lat, lng = PREF_LATLNG[pref]
        dist = haversine(tokyo[0], tokyo[1], lat, lng)
        if dist > 250:
            continue

        # 除外フィルタ
        if d.get('Winner') in excl_authors:
            continue
        if is_area_blocked(d.get('Place'), d.get('Area'), blocked_areas):
            continue
        if not has_valid_image(d.get('PicFileName')):
            continue

        # 母集合に追加
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
        }
        pool.append(item)

        # 注目度集計（近年入賞数）
        try:
            place_years[d.get('Area', '')].append(int(d.get('Year')))
        except:
            pass

    if not pool:
        return None, None, None

    # 枠1：傑作ポイント（賞スコア優先）
    top_pool = sorted(pool, key=lambda x: (-x['ascore'], x['dist']))[:max(8, len(pool)//10)]
    masterpiece = random.choice(top_pool)

    # 枠2：近場で楽しむ（距離優先、県をずらす）
    near_pool = sorted(pool, key=lambda x: x['dist'])[:max(8, len(pool)//8)]
    near_cand = [p for p in near_pool if p['pref'] != masterpiece['pref']] or near_pool
    near = random.choice(near_cand)

    # 枠3：注目のポイント（近年入賞数優先、県をずらす）
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
    hot_cand = [p for p in hot_pool if p['pref'] not in used_prefs] or hot_pool
    hot_cand = hot_cand[:max(8, len(hot_pool)//10)]
    attention = random.choice(hot_cand) if hot_cand else None

    return masterpiece, near, attention

# ──────────────── Flex Message 組み立て ────────────────
def build_carousel_bubble(item, label_emoji, area_note=""):
    """1つのバブルを作成（傑作/近場/注目）"""
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
                    "size": "sm",
                    "color": "#666666"
                },
                {
                    "type": "text",
                    "text": item['title'],
                    "weight": "bold",
                    "size": "md",
                    "margin": "md",
                    "wrap": True,
                    "color": "#111111"
                },
                {
                    "type": "text",
                    "text": f"{item['winner']}  ({item['award'] or '記録'})",
                    "size": "xs",
                    "color": "#999999",
                    "margin": "sm"
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "md",
                    "spacing": "xs",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"{item['area']}",
                            "size": "xs",
                            "color": "#666666"
                        },
                        {
                            "type": "text",
                            "text": f"{item['place']}",
                            "size": "xs",
                            "color": "#666666"
                        },
                        {
                            "type": "text",
                            "text": f"東京より {item['dist']:.0f}km",
                            "size": "xs",
                            "color": "#999999",
                            "margin": "sm"
                        }
                    ]
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "link",
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": "詳しく",
                        "data": f"action=detail&pic={item['pic']}"
                    }
                },
                {
                    "type": "button",
                    "style": "link",
                    "height": "sm",
                    "action": {
                        "type": "uri",
                        "label": "このルート記録",
                        "uri": f"https://maps.google.com/maps?q={item['area']}"
                    }
                }
            ]
        }
    }
    return bubble

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

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    sys.stderr.write(f"[DEBUG] Message received: {event.message.text}\n")
    with open('/tmp/debug.log', 'a') as f:
        f.write(f"[DEBUG] Message received: {event.message.text}\n")
    reply_token = event.reply_token
    user_message = event.message.text.strip()

    try:
        # 3分類選定を実行
        masterpiece, near, attention = select_three_points()

        if not masterpiece or not near:
            msg = TextSendMessage(
                text="申し訳ございません。現在条件に合う撮影地の検索ができておりません。"
            )
            line_bot_api.reply_message(reply_token, msg)
            return

        # 冒頭メッセージ
        greeting = TextSendMessage(
            text=f"本日のコンシェルジュがお薦めする、今が旬の撮影地3選です。どうぞご高覧ください。"
        )

        # カルーセル組み立て
        bubbles = [
            build_carousel_bubble(masterpiece, "🏆", "傑作ポイント"),
            build_carousel_bubble(near, "🚗", "近場で楽しむ"),
            build_carousel_bubble(attention or masterpiece, "✨", "注目のポイント"),
        ]

        carousel = FlexSendMessage(
            alt_text="風景写真コンシェルジュ・今日の3選",
            contents={
                "type": "carousel",
                "contents": bubbles
            }
        )

        # 同時に送信
        line_bot_api.reply_message(reply_token, [greeting, carousel])

    except Exception as e:
        import traceback
        sys.stderr.write(f"[ERROR] Exception: {traceback.format_exc()}\n")
        msg = TextSendMessage(
            text="申し訳ございません。処理中にエラーが発生しました。"
        )
        line_bot_api.reply_message(reply_token, msg)

@handler.add(PostbackEvent)
def handle_postback(event):
    """postback（「詳しく」「記録」ボタン）"""
    from linebot.models import PostbackEvent

    reply_token = event.reply_token

    try:
        data = event.postback.data
        # data = "action=detail&pic=FK_001.jpg" など
        params = dict(item.split('=') for item in data.split('&'))
        action = params.get('action')
        pic_filename = params.get('pic', '')

        if action == 'detail':
            # 「詳しく」 → スペック画面（簡易版）
            msg = TextSendMessage(
                text=f"📸 スペック画面\n（スペック情報の取得準備中）\n\nファイル: {pic_filename}"
            )
            line_bot_api.reply_message(reply_token, msg)

        elif action == 'record':
            # 「記録」 → Firestore Saved_Routes へ
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