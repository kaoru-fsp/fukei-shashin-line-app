import os
import json
import random
import re
import traceback
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi
from linebot.models import TextSendMessage, FlexSendMessage
# 🎯 公式の最深部接続パーツと認証パーツで、エラーを100%回避
from google.cloud import firestore
from google.oauth2 import service_account
from collections import Counter

app = Flask(__name__)
IMAGE_BASE_VIEW = "https://fupc.photo/PicsDB/PicsDB4Search"
TOKYO_LAT, TOKYO_LON = 35.6895, 139.6917

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

PREFECTURES = [
    "北海道", "青森", "岩手", "宮城", "秋田", "山形", "福島", "茨城", "栃木", "群馬",
    "埼玉", "千葉", "東京", "神奈川", "新潟", "富山", "石川", "福井", "山梨", "長野",
    "岐阜", "静岡", "愛知", "三重", "滋賀", "京都", "大阪", "兵庫", "奈良", "和歌山",
    "鳥取", "島根", "岡山", "広島", "山口", "徳島", "香川", "愛媛", "高知", "福岡",
    "佐賀", "長崎", "熊本", "大分", "宮崎", "鹿児島", "沖縄"
]

db_default = None  # 1つ目：アジア金庫 (default) -> Location master & 13号分
db_us = None       # 2つ目：アメリカ金庫 (fupc-db14など) -> 14号分〜

try:
    firebase_creds_json = os.environ.get('FIREBASE_CREDENTIALS')
    if firebase_creds_json:
        creds_dict = json.loads(firebase_creds_json)
        project_id = creds_dict.get('project_id')
        cred = service_account.Credentials.from_service_account_info(creds_dict)
        
        # 🎯 アジア(default)とUSの両方の金庫の鍵を公式手順で安全に解錠
        db_default = firestore.Client(project=project_id, database='(default)', credentials=cred)
        
        secondary_db_name = os.environ.get('FIRESTORE_SECONDARY_DB_NAME')
        if secondary_db_name:
            db_us = firestore.Client(project=project_id, database=secondary_db_name, credentials=cred)
except Exception as e:
    print(f"Firebase Init Error: {e}")

def generate_fupc_url(photo_data):
    published = str(photo_data.get('Published', '')).strip()
    pic_file_name = str(photo_data.get('PicFileName', '')).strip()
    
    if published.endswith('.0'): published = published[:-2]
    if pic_file_name.endswith('.0'): pic_file_name = pic_file_name[:-2]
    
    if published and pic_file_name and len(published) >= 4:
        # 🎯 あなたが実証した「パターン1」の絶対ルール
        raw_url = f"{IMAGE_BASE_VIEW}/{published[:4]}/{published}/{pic_file_name}"
        return re.sub(r'(?<!:)/+', '/', raw_url)
    return f"{IMAGE_BASE_VIEW}/default.jpg"

def get_location_guides(current_month, current_day, focus_keyword=None):
    """【第1段階】時期（PeriodIdx）を持つ Location master から案内データを抽出"""
    if db_default is None: return []
    
    if current_day <= 10: d = 1
    elif current_day <= 20: d = 2
    else: d = 3
    
    curr_idx = (current_month - 1) * 3 + d
    prev_idx = 36 if curr_idx == 1 else curr_idx - 1
    next_idx = 1 if curr_idx == 36 else curr_idx + 1
    target_slots = [prev_idx, curr_idx, next_idx]
    
    loc_cols = ["Location master", "Location_master"]
    raw_guides = []
    
    # アジアルート・USルートの両方から案内を回収
    for db_client in [db_default, db_us]:
        if not db_client: continue
        for col in loc_cols:
            try:
                query = db_client.collection(col).where('PeriodIdx', 'in', target_slots)
                for doc in query.stream():
                    gdata = doc.to_dict()
                    if gdata: raw_guides.append(gdata)
            except:
                continue
                
    # キーワード（「長野」など）があれば絞り込み
    filtered_guides = []
    for g in raw_guides:
        loc_pool = str(g.get('Area', '')) + str(g.get('Place', '')) + str(g.get('Title', '')) + str(g.get('Notes', ''))
        
        # 台湾・海外の完全弾きフィルター
        if any(x in loc_pool for x in ["台湾", "海外", "中国", "韓国", "アメリカ"]): continue
        if not any(pref in loc_pool for pref in PREFECTURES): continue
        
        if focus_keyword:
            if focus_keyword not in loc_pool: continue
            
        filtered_guides.append(g)
        
    return filtered_guides

def fetch_photo_by_dnumb(dnumb_value):
    """【第2段階】共通の鍵（dNumb）を使って、15,000件の photo master から写真を一本釣り"""
    if not dnumb_value: return None
    
    # 型のブレ（文字列の'105'、数値の105）を両方一発で仕留めるクエリを生成
    search_ids = [dnumb_value, str(dnumb_value)]
    try:
        search_ids.append(int(float(dnumb_value)))
    except:
        pass
        
    photo_cols = ["photo master", "photo_master"]
    
    for db_client in [db_default, db_us]:
        if not db_client: continue
        for col in photo_cols:
            try:
                query = db_client.collection(col).where('dNumb', 'in', search_ids)
                for doc in query.stream():
                    pdata = doc.to_dict()
                    if pdata: return pdata
            except:
                continue
    return None

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
    t1, a1, l1, u1 = photo1.get('Title') or "無題", photo1.get('Winner') or "写真家", photo1.get('Place') or "厳選撮影地", generate_fupc_url(photo1)
    t2, a2, l2, u2 = photo2.get('Title') or "無題", photo2.get('Winner') or "写真家", photo2.get('Place') or "厳選撮影地", generate_fupc_url(photo2)
    
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

def create_detail_ui(location, title, author, camera, lens, settings, guide_info, image_url):
    """🎯 【レベルアップリレーション】写真データと、新CSVのガイド情報を完全ドッキング"""
    access = guide_info.get('Access') or "現地案内を参照してください。"
    best_time = guide_info.get('BestTime') or "終日"
    light = guide_info.get('Light') or "現場の状況に合わせて調整"
    filters = guide_info.get('Filter') or "なし"
    notes = guide_info.get('Notes') or ""
    
    # 地図リンクの生成
    map_url = f"https://www.google.com/maps/search/?api=1&query={location}"
    route_url = f"https://www.google.com/maps/dir/?api=1&origin={TOKYO_LAT},{TOKYO_LON}&destination={location}&travelmode=driving"

    return {
        "type": "bubble",
        "backgroundColor": "#ffffff",
        "hero": {"type": "image", "url": image_url, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "🌸 AIコンシェルジュ撮影ナビ", "weight": "bold", "color": "#1DB954", "size": "md"},
                {"type": "text", "text": location, "weight": "bold", "size": "xxl", "margin": "md", "wrap": True},
                {
                    "type": "box", "layout": "vertical", "margin": "md", "spacing": "xs",
                    "contents": [
                        {"type": "text", "text": f"作品名: {title} (撮影: {author} 様)", "wrap": True, "color": "#111111", "size": "sm"},
                        {"type": "text", "text": f"推奨機材: {camera} / {lens}", "wrap": True, "color": "#555555", "size": "sm"},
                        {"type": "text", "text": f"撮影設定: {settings} / フィルター: {filters}", "wrap": True, "color": "#555555", "size": "sm"}
                    ]
                },
                {"type": "separator", "margin": "md"},
                {
                    "type": "box", "layout": "vertical", "margin": "md", "spacing": "xs",
                    "contents": [
                        {"type": "text", "text": "🧭 【アクセス・攻略情報】", "weight": "bold", "size": "md", "color": "#111111"},
                        {"type": "text", "text": f"■ 行き方:\n{access}", "wrap": True, "size": "sm", "color": "#222222", "margin": "xs"},
                        {"type": "text", "text": f"■ ベスト時間帯: {best_time} / 光線: {light}", "wrap": True, "size": "sm", "color": "#222222"},
                        {"type": "text", "text": f"■ 注意事項: {notes}" if notes else "", "wrap": True, "size": "sm", "color": "#cc0000"}
                    ]
                },
                {"type": "separator", "margin": "md"},
                {
                    "type": "box", "layout": "vertical", "margin": "md", "spacing": "sm",
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
    if db_default is None: return
    now = datetime.now()
    curr_m = now.month
    curr_d = now.day

    try:
        session_ref = db_default.collection('User_Sessions').document(user_id)
        session_doc = session_ref.get()

        if user_message == "やめる":
            session_ref.delete()
            line_bot_api.reply_message(reply_token, TextSendMessage(text="ご用がありましたらお声がけください。"))
            return
        if user_message == "戻る" and session_doc.exists:
            state = session_doc.to_dict()
            menu_payload = {
                "type": "flex", "altText": "メニュー",
                "contents": create_ui_buttons(state.get("menu_text", ""), json.loads(state.get("menu_choices_json", "[]")))
            }
            line_bot_api.reply_message(reply_token, FlexSendMessage.new_from_json_dict(menu_payload))
            return

        requested_month = None
        m_match = re.search(r'(\d+)月', user_message)
        if m_match: requested_month = int(m_match.group(1))

        if not session_doc.exists or any(k in user_message for k in ["明日", "おすすめ", "お勧め", "撮影"]) or requested_month:
            target_m = requested_month if requested_month else curr_m
            target_d = 15 if requested_month else curr_d
            
            if target_d <= 10: decade_str = "上旬"
            elif target_d <= 20: decade_str = "中旬"
            else: decade_str = "下旬"
            
            extracted_loc = None
            for k in ["長野", "山梨", "静岡", "福島", "新潟", "山形", "群馬", "栃木", "岩手", "大分", "鹿児島", "和歌山", "奈良", "山口"]:
                if k in user_message: extracted_loc = k; break
            
            # 【第1段階】Location masterから今月のおすすめ案内を全回収
            guides = get_location_guides(target_m, target_d, focus_keyword=extracted_loc)
            
            if not guides:
                reply_text = f"お出かけの条件でお探ししました。\n\nあいにく、ご指定の時期（{target_m}月{decade_str} 前後30日間）の撮影ガイドはまだ登録されていないようです。\n現在、11月や12月の秋・冬の名作ガイドが非常に充実しています。何月の撮影地をご覧になりますか？"
                choices = [
                    {"label": "🍁 11月の撮影地を見る", "text": "11月の撮影地を探す"},
                    {"label": "❄️ 12月の撮影地を見る", "text": "12月の撮影地を探す"},
                    {"label": "❌ やめる", "text": "やめる"}
                ]
                session_ref.set({"target_m": target_m, "target_d": target_d, "menu_text": reply_text, "menu_choices_json": json.dumps(choices)})
                init_payload = {"type": "flex", "altText": "時期の選択", "contents": create_ui_buttons(reply_text, choices)}
                line_bot_api.reply_message(reply_token, FlexSendMessage.new_from_json_dict(init_payload))
                return

            # ガイドから被写体や地名を集計してバラエティ豊かなボタンを生成
            photo_keywords = ["新緑", "滝", "富士山", "残雪", "桜", "茶畑", "新幹線", "清流", "海岸", "雲海", "ツツジ", "雪景色", "山焼き", "ナノハナ", "紅葉", "落葉", "冬桜"]
            subjects, point_names = [], []
            for g in guides:
                combined_text = str(g.get('Title', '')) + str(g.get('Notes', '')) + str(g.get('Place', ''))
                for kw in photo_keywords:
                    if kw in combined_text: subjects.append(kw)
                pt = str(g.get('Place', '')).strip()
                if pt and "県" not in pt and pt.lower() not in ["null", "nan", "none"]: point_names.append(pt)

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
            suggest_payload = {"type": "flex", "altText": "ご提案", "contents": create_ui_buttons(reply_text, choices)}
            line_bot_api.reply_message(reply_token, FlexSendMessage.new_from_json_dict(suggest_payload))
            return

        state = session_doc.to_dict() or {}
        target_m = int(state.get("target_m", curr_m))
        target_d = int(state.get("target_d", curr_d))
        
        if "選ぶ被写体:" in user_message or "選ぶポイント:" in user_message:
            word_name = user_message.replace("選ぶ被写体:", "").replace("選ぶポイント:", "").strip()
            guides = get_location_guides(target_m, target_d, focus_keyword=word_name)
            
            if not guides:
                line_bot_api.reply_message(reply_token, TextSendMessage(text="あいにく作品情報が見つかりませんでした。"))
                return
            
            # 🎯 【リレーション発動】案内データに紐づく写真を photo master から一本釣り
            photos = []
            for g in guides:
                p = fetch_photo_by_dnumb(g.get('Related_dNumb'))
                if p: photos.append(p)
                if len(photos) >= 2: break
                
            if not photos:
                line_bot_api.reply_message(reply_token, TextSendMessage(text="撮影地データはありますが、作品写真がまだ登録されていないようです。"))
                return
                
            p1 = photos[0]
            p2 = photos[1] if len(photos) > 1 else photos[0]
            preview_payload = {"type": "flex", "altText": "作品プレビュー", "contents": create_preview_carousel(p1, p2, word_name)}
            line_bot_api.reply_message(reply_token, FlexSendMessage.new_from_json_dict(preview_payload))
            return

        if "ここに行く:" in user_message:
            word_name = user_message.replace("ここに行く:", "").strip()
            guides = get_location_guides(target_m, target_d, focus_keyword=word_name)

            if not guides:
                 line_bot_api.reply_message(reply_token, TextSendMessage(text="あいにくルート情報が見つかりませんでした。"))
                 return
                 
            # ランダムに1つの案内をチョイス
            target_guide = random.choice(guides)
            target_photo = fetch_photo_by_dnumb(target_guide.get('Related_dNumb'))
            
            if not target_photo:
                 line_bot_api.reply_message(reply_token, TextSendMessage(text="作品詳細写真の読み込みに失敗しました。"))
                 return

            location = target_guide.get('Place') or target_photo.get('Place') or "厳選撮影地"
            session_ref.delete()

            title = target_photo.get('Title') or "無題"
            author = target_photo.get('Winner') or "不明"
            camera = target_photo.get('Camera') or "情報なし"
            lens = target_photo.get('Lens') or "情報なし"
            settings = target_photo.get('Exposure') or "情報なし"

            reply_wait_text = f"かしこまりました。では{location}の詳しい案内をご用意いたしますのでしばらくお待ちください。"
            reply_final_text = "こちらでございます。どうか安全で楽しく撮影を！"
            
            # 🎯 写真データとガイド情報をガチャンとマージして送信
            detail_payload = {"type": "flex", "altText": "ルート案内", "contents": create_detail_ui(location, title, author, camera, lens, settings, target_guide, generate_fupc_url(target_photo))}
            
            line_bot_api.reply_message(reply_token, [
                TextSendMessage(text=reply_wait_text),
                TextSendMessage(text=reply_final_text),
                FlexSendMessage.new_from_json_dict(detail_payload)
            ])
            return

    except:
        print(traceback.format_exc())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
