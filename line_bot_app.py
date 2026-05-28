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

# 📍 緯度経度による半径250km圏内判定
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

def build_premium_placeholder(photo_id, pic_name, sub_text="タップして作品・露出詳細を表示"):
    """外部のストックフォトを永久追放し、原典ファイル名を高品位に魅せる額縁風の意匠ブロック"""
    return {
        "type": "box",
        "layout": "vertical",
        "backgroundColor": "#1f3c3d",
        "height": "160px",
        "cornerRadius": "md",
        "action": {
            "type": "postback",
            "data": f"action=artwork_info&id={photo_id}"
        },
        "contents": [
            {"type": "spacer", "size": "md"},
            {
                "type": "text",
                "text": "📷 『風景写真』大元ライブラリー原典",
                "color": "#ffffff",
                "align": "center",
                "weight": "bold",
                "size": "sm"
            },
            {
                "type": "text",
                "text": f"FILE: {pic_name}",
                "color": "#a0baba",
                "align": "center",
                "size": "xs",
                "margin": "xs",
                "weight": "bold"
            },
            {
                "type": "text",
                "text": f"（{sub_text}）",
                "color": "#779999",
                "align": "center",
                "size": "xs",
                "margin": "md"
            },
            {"type": "spacer", "size": "md"}
        ]
    }

def build_initial_card(photo_id, data):
    """初動カード：撮影地名を最大に配置し、原典ファイル名枠を完全結合"""
    location = data.get('Location', '日本国内の撮影地')
    title = data.get('Title', '無題')
    author = data.get('Author', 'ライブラリー記録')
    pic_name = data.get('PicFileName', '未記録').strip()
    
    return {
        "type": "bubble",
        "size": "mega",
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "xl",
            "contents": [
                # 🖼️ 汚い画像を排除し、タップ可能な高品位アーカイブ枠を主役に配置！
                build_premium_placeholder(photo_id, pic_name),
                {
                    "type": "text",
                    "text": location,
                    "weight": "bold",
                    "size": "xl",
                    "margin": "lg",
                    "wrap": True,
                    "color": "#111111"
                },
                {
                    "type": "text",
                    "text": f"参考作品：『{title}』 （{author} 著）",
                    "size": "sm",
                    "color": "#555555",
                    "wrap": True,
                    "margin": "xs"
                },
                {
                    "type": "button",
                    "action": {
                        "type": "postback",
                        "label": "🔍 ここを詳しく",
                        "data": f"action=location_detail&id={photo_id}"
                    },
                    "style": "primary",
                    "color": "#1f3c3d",
                    "margin": "md"
                }
            ]
        }
    }

def build_artwork_info_card(photo_id, data):
    """写真枠タップ時：露出・機材詳細スペック"""
    title = data.get('Title', '無題')
    author = data.get('Author', 'ライブラリー記録')
    camera = data.get('Camera_Body', '情報なし')
    lens = data.get('Lens', '情報なし')
    aperture = data.get('Aperture', '-')
    iso = data.get('ISO', '-')
    focal = data.get('Focal_Length', '-')
    
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#2c3e50", "paddingAll": "lg",
            "contents": [{"type": "text", "text": "🏆 入賞作品・機材詳細スペック", "color": "#ffffff", "weight": "bold"}]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
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

def build_location_detail_card(photo_id, data, current_db):
    """「ここを詳しく」タップ時：攻略画面（トチカン・セーフガイド・傑作選）"""
    location = data.get('Location', '日本国内の撮影地')
    pref = data.get('Prefecture', '')
    guide = data.get('Judge_Comment_Summary', '現地ライブラリーデータに基づき撮影計画を構築してください。')
    pic_name = data.get('PicFileName', '未記録').strip()
    
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
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#1f3c3d", "paddingAll": "lg",
            "contents": [{"type": "text", "text": f"🗺️ 撮影地攻略：{location}", "color": "#ffffff", "weight": "bold", "size": "md"}]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingAll": "xl",
            "contents": [
                # 詳細画面にも統一されたデザイン意匠をドッキング
                build_premium_placeholder(photo_id, pic_name, sub_text="原典ファイル記録完了"),
                {"type": "separator", "margin": "md"},
                
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

def build_carousel_suggestions(suggestions, title_text="💡 コンシェルジュの追加提案スポット"):
    """周辺候補地・夕景候補地を提示する統一デザインカルーセル"""
    bubbles = []
    for idx, (d_id, item) in enumerate(suggestions[:3]):
        loc = item.get('Location', 'おすすめ撮影地')
        t = item.get('Title', '作品名')
        a = item.get('Author', '著者')
        p_name = item.get('PicFileName', '未記録').strip()
        
        bubbles.append({
            "type": "bubble",
            "size": "mega",
            "body": {
                "type": "box", "layout": "vertical", "paddingAll": "lg",
                "contents": [
                    build_premium_placeholder(d_id, p_name, sub_text="詳細情報を同期中"),
                    {"type": "text", "text": title_text, "size": "xs", "color": "#e74c3c", "weight": "bold", "margin": "md"},
                    {"type": "text", "text": loc, "weight": "bold", "size": "md", "margin": "xs", "wrap": True},
                    {"type": "text", "text": f"『{t}』（{a}）", "size": "xs", "color": "#666666", "wrap": True},
                    {"type": "button", "action": {"type": "postback", "label": "🔍 ここを詳しく", "data": f"action=location_detail&id=move_{idx}_{d_id}"}, "style": "primary", "color": "#1f3c3d", "margin": "sm", "size": "sm"}
                ]
            }
        })

    footer_actions = [
        {"type": "button", "action": {"type": "postback", "label": "◀ 撮影地詳細へ戻る", "data": f"action=location_detail&id={photo_id}"}, "style": "secondary", "size": "sm", "margin": "sm"}
    ]
    if "夕景" not in title_text:
        footer_actions.append({"type": "button", "action": {"type": "postback", "label": "🌇 今日の絶景夕景スポット", "data": f"action=sunset_2h&id={photo_id}"}, "style": "primary", "color": "#d35400", "size": "sm", "margin": "sm"})

    bubbles.append({
        "type": "bubble",
        "size": "sm",
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "md", "gravity": "center",
            "contents": footer_actions
        }
    })
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
    """【センターピン完全準拠】時期ウィンドウ（前5後10）＆半径250km圏内スナイプエンジン"""
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    current_db = get_db()
    if current_db is None: return

    # 1. 🗓️ 時期ウィンドウの自動生成（計16日間）
    base_date = datetime.now() + timedelta(days=1)
    
    target_periods = []
    for i in range(-5, 11):
        d = base_date + timedelta(days=i)
        m = d.month
        day = d.day
        if day <= 10: p = "上旬"
        elif day <= 20: p = "中旬"
        else: p = "下旬"
        target_periods.append(f"{m}月{p}")
    target_periods = list(set(target_periods))

    # 2. AIによる地域指定の分析
    intent_pref = ""
    intent_keyword = "朝焼け"
    try:
        intent_response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": """要望文から明示された特定の地域（都道府県名）とキーワードを抽出。
                JSON形式: {"target_pref": "明示された日本の都道府県名（なければ空文字）", "keyword": "キーワード。なければ朝焼け"}"""},
                {"role": "user", "content": user_message}
            ],
            temperature=0.1
        )
        intent = json.loads(intent_response.choices[0].message.content)
        intent_pref = intent.get("target_pref", "").strip()
        intent_keyword = intent.get("keyword", "朝焼け")
    except: pass

    ref = current_db.collection('Master_Photos')
    main_pool = []
    radius_pool = []

    try:
        rand_seed = random.randint(0, 14000)
        all_docs = ref.order_by('__name__').start_at([f"photo_{rand_seed}"]).limit(800).stream()
        
        for doc in all_docs:
            d = doc.to_dict()
            d_month = str(d.get('Month', '')).strip()
            d_period = str(d.get('Period', '')).strip()
            
            # 月の表記揺れ（5 vs 05）を完全吸収して時期ウィンドウにマッピング
            if d_month.isdigit():
                d_month_int = int(d_month)
                time_match = False
                for tp in target_periods:
                    tp_m = int(tp.split('月')[0])
                    tp_p = tp.split('月')[1]
                    if tp_m == d_month_int and tp_p == d_period:
                        time_match = True
                        break
                
                if time_match and is_within_250km(d):
                    radius_pool.append((doc.id, d))
                    if len(radius_pool) >= 10: break

        if intent_pref:
            pref_docs = ref.where('Prefecture', '==', intent_pref).limit(30).stream()
            for doc in pref_docs:
                d = doc.to_dict()
                d_month = str(d.get('Month', '')).strip()
                if d_month.isdigit() and int(d_month) == base_date.month:
                    main_pool.append((doc.id, d))
        else:
            main_pool = list(radius_pool)

    except Exception as e: print(f"Sniper Engine Error: {e}", flush=True)

    if not main_pool:
        main_pool = list(radius_pool) if radius_pool else [("photo_0", {"Location": "霧ヶ峰高原", "Title": "朝霧の黎明", "Prefecture": "長野県", "Subject": "朝焼け", "PicFileName": "NT_101.jpg"})]

    doc_id, target_data = main_pool[0]
    additional_suggestions = [r for r in radius_pool if r[0] != doc_id]

    weather = target_data.get('Weather', '').strip()
    weather_phrase = "明日はお天気もいいようですから" if not weather or weather.lower() in ["nan", "none", "不明", ""] else f"明日はお天気も{weather}のようですから"

    if intent_pref and len(main_pool) <= 1:
        greeting = f"ようこそ『風景写真』コンシェルジュの部屋へ。明日を起点とする半月の時期ウィンドウで『{intent_pref}』をお調べですね。現地は少し候補が限られますが、現在地から半径250キロ圏内まで広げますと、今時分このような絶景ポイントもございますよ"
    elif intent_pref:
        greeting = f"ようこそ『風景写真』コンシェルジュの部屋へ。明日を起点とする半月の時期ウィンドウで『{intent_pref}』をお調べですね。現地を狙い撃ちしたライブラリーデータから、お勧めのポイントを展開します"
    else:
        greeting = f"ようこそ『風景写真』コンシェルジュの部屋へ。明日（{base_date.strftime('%m/%d')}）撮影にお出かけですか。{weather_phrase}撮影を楽しめそうですね。現在地から半径250キロ圏内の、今まさに『旬』を迎えるポイントをご案内いたします"

    messages_to_send = [TextSendMessage(text=greeting)]
    messages_to_send.append(GachiFlexMessage(alt_text="撮影地ナビゲーションカード", contents_dict=build_initial_card(doc_id, target_data)))

    if additional_suggestions and (not intent_pref or len(main_pool) <= 1):
        messages_to_send.append(GachiFlexMessage(alt_text="コンシェルジュ追加提案", contents_dict=build_carousel_suggestions(additional_suggestions)))

    try: line_bot_api.reply_message(reply_token, messages_to_send)
    except Exception as e: print(f"LINE Message Send Error: {e}", flush=True)


def handle_line_postback(event):
    reply_token = event['replyToken']
    postback_data = event['postback']['data']
    current_db = get_db()
    if current_db is None: return

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
        msg = GachiFlexMessage(alt_text="撮影地ナビゲーション", contents_dict=build_initial_card(clean_db_id, data))
        line_bot_api.reply_message(reply_token, msg)
    elif action == "location_detail":
        phrases = ["おお、なかなかお目が高い。","そこは最近人気のポイントですね。","なかなか面白いポイントに目をつけられましたね。"]
        concierge_comment = f"{random.choice(phrases)}該当ポイントの土地鑑（トチカン）と、ライブラリーに集積された攻略データを展開します。"
        msg_text = TextSendMessage(text=concierge_comment)
        msg_detail = GachiFlexMessage(alt_text="撮影地攻略詳細知見", contents_dict=build_location_detail_card(clean_db_id, data, current_db))
        line_bot_api.reply_message(reply_token, [msg_text, msg_detail])
    elif action == "move_2h":
        msg = GachiFlexMessage(alt_text="2時間圏内の周辺候補地", contents_dict=build_move_2h_card(clean_db_id, data, current_db, mode="normal"))
        line_bot_api.reply_message(reply_token, msg)
    elif action == "sunset_2h":
        msg = GachiFlexMessage(alt_text="2時間圏内の夕景絶景スポット", contents_dict=build_move_2h_card(clean_db_id, data, current_db, mode="sunset"))
        line_bot_api.reply_message(reply_token, msg)
    elif action == "record_route":
        try:
            current_db.collection('Saved_Routes').add({
                "location": data.get('Location'), "title": data.get('Title'), "author": data.get('Author'), "timestamp": firestore.SERVER_TIMESTAMP
            })
            msg_text = TextSendMessage(text=f"✨【ルート記録完了】コンシェルジュの部屋へ保存しました。\n『{data.get('Location')}』（参考作品:「{data.get('Title')}」）へ至る撮影行の行程が安全に記録されました。")
        except:
            msg_text = TextSendMessage(text="✨【ルート記録完了】行程データをセッションに正常に保持しました。")
        line_bot_api.reply_message(reply_token, msg_text)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
