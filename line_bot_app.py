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
# 🎯 スラッシュの重なりを防ぐため、末尾のスラッシュを削除した綺麗なベースURL
IMAGE_BASE_VIEW = "https://fupc.photo/PicsDB/PicsDB4Search"
TOKYO_LAT, TOKYO_LON = 35.6895, 139.6917

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

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
    
    if published and pic_file_name and pic_file_name.lower() not in ['nan', 'null', 'none', '']:
        # 🎯 【完全正常化】ご提示いただいたお手本の「正」のURLと1文字も違わず、寸分狂わずに結合します
        return f"{IMAGE_BASE_VIEW}/{published[:4]}/{published}/{pic_file_name}"
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
    
    # 🎯 全件検索NG・海外除外の厳格インデックスクエリ
    query = db.collection('contest_data_v2').where('PeriodIdx', 'in', target_slots)
    docs = query.stream()
    
    filtered_photos = []
    for doc in docs:
        pdata = doc.to_dict()
        if not pdata: continue
        
        # 海外候補の完全除外
        if "海外" in str(pdata.get('Area', '')) or "海外" in str(pdata.get('Place', '')):
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
    
    # 🎯 左右対称の2枚構成。下部に完全標準の「ここに行く」ボタンを配置。フチカット適用。
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
                    "type": "box", "layout": "horizontal", "margin": "md",
                    "contents": [
                        {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [
                            {"type": "text", "text": f"作品名: {title} (撮影: {author} 様)", "wrap": True, "color": "#111111", "size": "md"},
                            {"type": "text", "text": f"推奨機材: {camera} / {lens}", "wrap": True, "color": "#111111", "size": "md"},
                            {"type": "text", "text": f"撮影設定: {settings}", "wrap": True, "color": "#111111", "size": "md"}
                        ]}
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
            else: decade_str = "下旬"
            
            extracted_loc = None
            for k in ["長野", "山梨", "静岡", "福島", "新潟", "山形", "群馬", "栃木", "岩手", "大分", "鹿児島", "和歌山", "奈良", "山口"]:
                if k in user_message: extracted_loc = k; break
            
            base_photos = get_filtered_photos(target_m, target_d, focus_keyword=extracted_loc)
            
            if not base_photos:
                reply_text = f"お出かけの条件でお探ししました。\n\nあいにく、ご指定の時期（{target_m}月{decade_str} 前後30日間）の撮影地データはまだ登録されていないようです。\n現在、11月や12月の秋・冬の名作データが非常に充実しています。何月の撮影地をご覧になりますか？"
                choices = [
                    {"label": "🍁 11月の撮影地を見る", "text": "11月の撮影地を探す"},
                    {"label": "❄️ 12月の撮影地を見る", "text": "12月の撮影地を探す"},
                    {"label": "❌ やめる", "text": "やめる"}
                ]
                session_ref.set({"target_m": target_m, "target_d": target_d, "menu_text": reply_text, "menu_choices_json": json.dumps(choices)})
                line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="時期の選択", contents=create_ui_buttons(reply_text, choices)))
                return

            photo_keywords = ["新緑", "滝", "富士山", "残雪", "桜", "茶畑", "新幹線", "清流", "海岸", "雲海", "ツツジ", "雪景色", "山焼き", "ナノハナ", "紅葉", "落葉", "冬桜"]
            subjects, point_names = [], []
            for p in base_photos:
                combined_text = str(p.get('Title', '')) + str(p.get('Subject', '')) + str(p.get('Area', ''))
                for kw in photo_keywords:
                    if kw in combined_text: subjects.append(kw)
                pt = get_photo_place_name(p)
                if pt and "県" not in pt and pt.lower() not in ["null", "nan", "none", "厳選撮影地"]: point_names.append(pt)

            sub_ranks = [w[0] for w in Counter(subjects).most_common(3) if w[0]]
            point_ranks = [w[0] for w in Counter(point_names).most_common(3) if w[0]]
            if not sub_ranks: sub_ranks = ["風景"]
            if not point_ranks: point_ranks = ["厳選撮影地"]

            sub_top_str = "や".join(sub_ranks[:2]) if len(sub_ranks) >= 2 else sub_ranks[0]
            point_top_str = "や".join(point_ranks[:2]) if len(point_ranks) >= 2 else point_ranks[0]
            
            reply_text = f"お出かけの条件でお探ししました。\n\n{target_m}月{decade_str}頃の時期（前後あわせて30日間）ですと、{sub_top_str}などの被写体が人気のようです。撮影ポイントとしては{point_top_str}などがございます。興味を感じるものはありますか？"
            
            choices = []
            for s in sub_ranks[:2]: choices.append({"label": f"📸 被写体: {s}", "text": f"選ぶ被写体: {s}"})
            for p in point_ranks[:2]: choices.append({"label": f"📍 ポイント: {p}", "text": f"選ぶポイント: {p}"})
            choices.append({"label": "❌ やめる", "text": "やめる"})

            session_ref.set({"target_m": target_m, "target_d": target_d, "menu_text": reply_text, "menu_choices_json": json.dumps(choices)})
            line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="ご提案", contents=create_ui_buttons(reply_text, choices)))
            return

        state = session_doc.to_dict() or {}
        raw_m = state.get("target_m") or state.get("month") or curr_m
        if isinstance(raw_m, str):
            m_match = re.search(r'(\d+)', raw_m)
            target_m = int(m_match.group(1)) if m_match else curr_m
        else:
            target_m = int(raw_m)

        raw_d = state.get("target_d") or curr_d
        target_d = int(raw_d) if raw_d else curr_d
        
        if "選ぶ被写体:" in user_message or "選ぶポイント:" in user_message:
            word_name = user_message.replace("選ぶ被写体:", "").replace("選ぶポイント:", "").strip()
            base_photos = get_filtered_photos(target_m, target_d, focus_keyword=word_name)
            
            if not base_photos:
                line_bot_api.reply_message(reply_token, TextSendMessage(text="あいにく作品情報が見つかりませんでした。"))
                return
            
            p1 = base_photos[0]
            p2 = base_photos[1] if len(base_photos) > 1 else base_photos[0]
            line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="作品プレビュー", contents=create_preview_carousel(p1, p2, word_name)))
            return

        if "ここに行く:" in user_message:
            word_name = user_message.replace("ここに行く:", "").strip()
            base_photos = get_filtered_photos(target_m, target_d, focus_keyword=word_name)

            if not base_photos:
                 line_bot_api.reply_message(reply_token, TextSendMessage(text="あいにくルート情報が見つかりませんでした。"))
                 return
            target_photo = random.choice(base_photos)

            location = get_photo_place_name(target_photo)
            session_ref.delete()

            map_url = f"https://www.google.com/maps/search/?api=1&query={location}"
            route_url = f"https://www.google.com/maps/dir/?api=1&origin={TOKYO_LAT},{TOKYO_LON}&destination={location}&travelmode=driving"

            title = target_photo.get('Title') or "無題"
            author = target_photo.get('Winner') or "不明"
            camera = target_photo.get('Camera') or "情報なし"
            lens = target_photo.get('Lens') or "情報なし"
            settings = target_photo.get('Exposure') or "情報なし"
            guide = target_photo.get('Selection Comments') or '詳細な選評情報はありません。'

            # 🎯 ご指定いただいた温かいセリフを完全反映
            reply_wait_text = f"かしこまりました。では{location}の詳しい案内をご用意いたしますのでしばらくお待ちください。"
            reply_final_text = "こちらでございます。どうか安全で楽しく撮影を！"
            
            line_bot_api.reply_message(reply_token, [
                TextSendMessage(text=reply_wait_text),
                TextSendMessage(text=reply_final_text),
                FlexSendMessage(alt_text="ルート案内", contents=create_detail_ui(location, title, author, camera, lens, settings, target_photo.get('Weather'), guide, map_url, route_url, generate_fupc_url(target_photo)))
            ])
            return

    except:
        print(traceback.format_exc())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
