import os
import json
import random
import math
import traceback
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi
from linebot.models import (
    TextSendMessage, FlexSendMessage
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


# ─── 🛡️ 【null/nan 撃退カウンター】撮影地名を安全に美しく返す新ルール ───
def get_photo_place_name(pdata):
    place = str(pdata.get('Place', '')).strip()
    # 空っぽ、またはシステム用語の 'nan', 'null', 'none' だった場合は徹底スルー
    if place and place.lower() not in ['nan', 'null', 'none', '']: 
        return place
    area = str(pdata.get('Area', '')).strip()
    if area and area.lower() not in ['nan', 'null', 'none', '']: 
        return area
    return "厳選撮影地"


# ─── 🌸 【FUPC公式】閲覧用画像URL生成関数 ───
def generate_fupc_url(photo_data):
    published = str(photo_data.get('Published', '')).strip()
    pic_file_name = str(photo_data.get('PicFileName', '')).strip()
    if len(published) >= 4 and pic_file_name and pic_file_name.lower() not in ['nan', 'null', 'none']:
        return f"{IMAGE_BASE_VIEW.rstrip('/')}/{published[:4]}/{published}/{pic_file_name}"
    return "https://fupc.photo/PicsDB/PicsDB4Search/default.jpg"


# ─── 🛡️ 【3段階セーフティネット対応】鉄壁のデータ抽出エンジン ───
def get_filtered_photos(target_month, target_period=None, focus_keyword=None, force_ignore_date=False, force_ignore_month=False):
    if db is None: return []
    photos_ref = db.collection('contest_data_v2')
    
    m = int(target_month.replace("月", "").strip())
    
    if force_ignore_month:
        docs = photos_ref.limit(100).stream()
    else:
        docs = photos_ref.where('Month', '==', m).stream()
    
    p = 1 if target_period == "初旬" else 2 if target_period == "中旬" else 3
    target_slots = [(m, p)]
    if p == 1: target_slots.append((12 if m == 1 else m - 1, 3))
    else: target_slots.append((m, p - 1))
    if p == 3: target_slots.append((1 if m == 12 else m + 1, 1))
    else: target_slots.append((m, p + 1))
    
    filtered_photos = []
    for doc in docs:
        pdata = doc.to_dict()
        if not pdata: continue
        
        if not force_ignore_date and not force_ignore_month and target_period:
            try:
                db_month = int(pdata.get('Month', 0))
                db_day = int(pdata.get('Day', 0))
                db_p = 1 if 1 <= db_day <= 10 else 2 if 11 <= db_day <= 20 else 3
                
                if (db_month, db_p) not in target_slots:
                    continue
            except:
                continue
                
        pub = pdata.get('Published')
        pic = pdata.get('PicFileName')
        if not pub or not pic: continue

        if focus_keyword:
            search_pool = (
                str(pdata.get('Title', '')) + 
                str(pdata.get('Area', '')) + 
                str(pdata.get('Place', '')) + 
                str(pdata.get('Subject', ''))
            )
            if focus_keyword not in search_pool:
                continue
        else:
            area_str = str(pdata.get('Area', ''))
            if area_str and not any(x in area_str for x in ["長野", "山梨", "静岡", "群馬", "新潟", "埼玉", "東京", "千葉", "神奈川"]):
                continue
                
        filtered_photos.append(pdata)
        
    return filtered_photos


# --- 🗃️ 大文字・大ボタン仕様のカスタムメニュー作成 ---
def create_大文字選択肢_ui(reply_text, choices_list):
    buttons_contents = []
    for item in choices_list:
        buttons_contents.append({
            "type": "button",
            "action": {"type": "message", "label": item["label"][:15], "text": item["text"]},
            "style": "secondary", "color": "#f0f0f0", "margin": "sm"
        })
    return {
        "type": "bubble",
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md",
            "contents": [
                {"type": "text", "text": reply_text, "wrap": True, "size": "md", "color": "#111111", "weight": "bold"},
                {"type": "box", "layout": "vertical", "spacing": "xs", "contents": buttons_contents}
            ]
        }
    }


# ─── 🖼️ 【アスペクト比完全維持】入賞作品2点紙芝居UI ───
def create_作品閲覧_ui(photo1, photo2, word_name):
    title1 = photo1.get('Title') or "無題"
    author1 = photo1.get('Winner') or "写真家"
    if str(title1).lower() in ['null', 'nan', 'none', '']: title1 = "無題"
    if str(author1).lower() in ['null', 'nan', 'none', '']: author1 = "写真家"
    loc1 = get_photo_place_name(photo1)
    img_url1 = generate_fupc_url(photo1)

    title2 = photo2.get('Title') or "無題"
    author2 = photo2.get('Winner') or "写真家"
    if str(title2).lower() in ['null', 'nan', 'none', '']: title2 = "無題"
    if str(author2).lower() in ['null', 'nan', 'none', '']: author2 = "写真家"
    loc2 = get_photo_place_name(photo2)
    img_url2 = generate_fupc_url(photo2)

    return {
        "type": "carousel",
        "contents": [
            {
                "type": "bubble",
                "backgroundColor": "#111111",
                "hero": {"type": "image", "url": img_url1, "size": "full", "aspectRatio": "20:13", "aspectMode": "fit"},
                "body": {
                    "type": "box", "layout": "vertical", "spacing": "sm",
                    "contents": [
                        {"type": "text", "text": f"📍 {loc1}", "weight": "bold", "size": "md", "wrap": True, "color": "#ffffff"},
                        {"type": "text", "text": f"「{title1}」 (撮影: {author1} 様)", "size": "sm", "color": "#cccccc", "wrap": True}
                    ]
                }
            },
            {
                "type": "bubble",
                "backgroundColor": "#111111",
                "hero": {"type": "image", "url": img_url2, "size": "full", "aspectRatio": "20:13", "aspectMode": "fit"},
                "body": {
                    "type": "box", "layout": "vertical", "spacing": "sm",
                    "contents": [
                        {"type": "text", "text": f"📍 {loc2}", "weight": "bold", "size": "md", "wrap": True, "color": "#ffffff"},
                        {"type": "text", "text": f"「{title2}」 (撮影: {author2} 様)", "size": "sm", "color": "#cccccc", "wrap": True}
                    ]
                }
            },
            {
                "type": "bubble",
                "body": {
                    "type": "box", "layout": "vertical", "spacing": "md",
                    "contents": [
                        {"type": "text", "text": f"🏁 【{word_name}】の選択", "weight": "bold", "size": "md", "margin": "md"},
                        {"type": "button", "action": {"type": "message", "label": "👉 ここに行く", "text": f"ここに行く: {word_name}"}, "style": "primary", "color": "#1DB954", "margin": "sm"},
                        {"type": "button", "action": {"type": "message", "label": "⬅️ 戻る", "text": "戻る"}, "style": "secondary", "margin": "sm"},
                        {"type": "button", "action": {"type": "message", "label": "❌ やめる", "text": "やめる"}, "style": "link", "color": "#ff0000", "margin": "sm"}
                    ]
                }
            }
        ]
    }


# ─── 🏛️ 【CSV構造100%完全直結】本物の選評案内UI ───
def create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment, map_url, route_url, image_url):
    if str(title).lower() in ['null', 'nan', 'none', '']: title = "無題"
    if str(author).lower() in ['null', 'nan', 'none', '']: author = "写真家"
    if str(camera).lower() in ['null', 'nan', 'none', '']: camera = "情報なし"
    if str(lens).lower() in ['null', 'nan', 'none', '']: lens = "情報なし"
    if str(settings).lower() in ['null', 'nan', 'none', '']: settings = "情報なし"
    return {
      "type": "bubble",
      "backgroundColor": "#ffffff",
      "hero": {"type": "image", "url": image_url, "size": "full", "aspectRatio": "20:13", "aspectMode": "fit"},
      "body": {
        "type": "box", "layout": "vertical",
        "contents": [
          {"type": "text", "text": "🌸 AIコンシェルジュ厳選提案", "weight": "bold", "color": "#1DB954", "size": "sm"},
          {"type": "text", "text": location, "weight": "bold", "size": "xl", "margin": "md", "wrap": True},
          {
            "type": "box", "layout": "vertical", "margin": "lg", "spacing": "sm",
            "contents": [
              {"type": "box", "layout": "baseline", "spacing": "sm", "contents": [{"type": "text", "text": "作品名", "color": "#aaaaaa", "size": "sm", "flex": 2}, {"type": "text", "text": f"{title} (撮影: {author} 様)", "wrap": True, "color": "#666666", "size": "sm", "flex": 5}]},
              {"type": "box", "layout": "baseline", "spacing": "sm", "contents": [{"type": "text", "text": "推奨機材", "color": "#aaaaaa", "size": "sm", "flex": 2}, {"type": "text", "text": f"{camera}\n{lens}", "wrap": True, "color": "#666666", "size": "sm", "flex": 5}]},
              {"type": "box", "layout": "baseline", "spacing": "sm", "contents": [{"type": "text", "text": "撮影設定", "color": "#aaaaaa", "size": "sm", "flex": 2}, {"type": "text", "text": settings, "wrap": True, "color": "#666666", "size": "sm", "flex": 5}]}
            ]
          },
          {"type": "separator", "margin": "xxl"},
          {"type": "box", "layout": "vertical", "margin": "xxl", "contents": [{"type": "text", "text": "📖 【現地ナビ・アクセス】", "weight": "bold", "size": "md", "color": "#111111"}, {"type": "text", "text": guide, "wrap": True, "size": "sm", "color": "#555555", "margin": "md"}]},
          {"type": "separator", "margin": "xxl"},
          {"type": "box", "layout": "vertical", "margin": "xxl", "backgroundColor": "#f7f8fa", "cornerRadius": "md", "paddingAll": "md", "contents": [{"type": "text", "text": "🎓 【レベルアップ相談室・選評】", "weight": "bold", "size": "md", "color": "#e67e22"}, {"type": "text", "text": judge_comment, "wrap": True, "size": "sm", "color": "#333333", "margin": "sm"}]},
          {"type": "separator", "margin": "xxl"},
          {
            "type": "box",
            "layout": "vertical", "margin": "md", "spacing": "sm",
            "contents": [
                {"type": "button", "action": {"type": "uri", "label": "🗺️ Googleマップで場所を確認", "uri": map_url}, "style": "secondary"},
                {"type": "button", "action": {"type": "uri", "label": "🚗 東京からの高速ルートナビ", "uri": route_url}, "style": "primary", "color": "#1DB954"}
            ]
          }
        ]
      }
    }


# --- Webhook 受信口 ---
@app.route("/callback", methods=['POST'])
def callback():
    try:
        request_json = request.get_json()
        events = request_json.get('events', [])
        for event in events:
            if event.get('type') == 'message' and event['message'].get('type') == 'text':
                handle_line_message(event)
    except Exception as e:
        print(f"🔥 Webhook Error: {traceback.format_exc()}")
    return 'OK', 200


# --- 对话分析引擎 ---
def handle_line_message(event):
    user_id = event['source']['userId']
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    
    if db is None: return

    now = datetime.now()
    default_month = f"{now.month}月"
    default_period = "初旬" if now.day <= 10 else "中旬" if now.day <= 20 else "下旬"

    try:
        session_ref = db.collection('User_Sessions').document(user_id)
        session_doc = session_ref.get()

        if user_message == "やめる":
            session_ref.delete()
            line_bot_api.reply_message(reply_token, TextSendMessage(text="ご用がありましたら、いつでもお声がけください。"))
            return

        if user_message == "戻る" and session_doc.exists:
            state = session_doc.to_dict()
            menu_text = state.get("menu_text", "")
            choices = json.loads(state.get("menu_choices_json", "[]"))
            if menu_text and choices:
                flex_message = FlexSendMessage(
                    alt_text="コンシェルジュ提案メニュー",
                    contents=create_大文字選択肢_ui(menu_text, choices)
                )
                line_bot_api.reply_message(reply_token, flex_message)
                return

        # ─── 📊 1往復目 ───
        if not session_doc.exists or any(k in user_message for k in ["明日", "おすすめ", "お勧め", "撮影"]):
            extracted_loc = None
            is_fallback_mode = False
            for k in ["長野", "山梨", "静岡", "福島", "新潟", "山形"]:
                if k in user_message: extracted_loc = k
                
            base_photos = get_filtered_photos(default_month, default_period, focus_keyword=extracted_loc)

            # 救済第2段階
            if not base_photos and extracted_loc:
                base_photos = get_filtered_photos(default_month, target_period=None, focus_keyword=extracted_loc, force_ignore_date=True)

            # 代替提案ルートの起動（250km圏内スキャン）
            if not base_photos and extracted_loc:
                is_fallback_mode = True
                base_photos = get_filtered_photos(default_month, default_period, focus_keyword=None)
                if not base_photos:
                    base_photos = get_filtered_photos(default_month, target_period=None, focus_keyword=None, force_ignore_date=True)
                if not base_photos:
                    base_photos = get_filtered_photos(default_month, focus_keyword=None, force_ignore_month=True)

            if not base_photos:
                line_bot_api.reply_message(reply_token, TextSendMessage(text="誠に恐れ入ります。ただいまライブラリをお探しいたしましたが、あいにく名作の記録がまだ見つかりませんでした。データを追加して、再度お声がけいただけますと幸いです。"))
                return

            photo_keywords = ["新緑", "滝", "富士山", "残雪", "桜", "紅葉", "茶畑", "新幹線", "清流", "海岸", "雲海", "ツツジ"]
            
            subjects, point_names = [], []
            for p in base_photos:
                combined_text = str(p.get('Title', '')) + str(p.get('Area', '')) + str(p.get('Subject', ''))
                for kw in photo_keywords:
                    if kw in combined_text: subjects.append(kw)
                
                pt = get_photo_place_name(p)
                # ボタン用ランキング集計時、'null' や '厳選撮影地' などのノイズ名を除外
                if pt and "県" not in pt and pt.lower() not in ["null", "nan", "none", "厳選撮影地"]: 
                    point_names.append(pt)

            sub_ranks = [w[0] for w in Counter(subjects).most_common(3) if w[0]]
            point_ranks = [w[0] for w in Counter(point_names).most_common(3) if w[0]]

            if not sub_ranks: sub_ranks = ["風景"]
            if not point_ranks: point_ranks = ["厳選撮影地"]

            # ─── 🌟 セリフ構築（改行を完全美化） ───
            if is_fallback_mode:
                top_suggestions = sub_ranks[:1] + point_ranks[:1]
                if len(top_suggestions) < 2: top_suggestions = sub_ranks[:2]
                
                word1 = top_suggestions[0]
                word2 = top_suggestions[1] if len(top_suggestions) > 1 else "絶景"
                
                reply_text = (
                    f"申し訳ありません。あいにく明日の条件に合う【{extracted_loc}】の名作データが現在のライブラリにございませんでした。\n\n"
                    f"代わりと言うわけではありませんが、今頃の情報といたしましては東京近郊（250km圏内）では【{word1}】や【{word2}】などがよく撮られているようです。よろしければご案内致しましょうか？"
                )
                choices = [
                    {"label": f"📸 {word1}をご案内", "text": f"選ぶ被写体: {word1}"},
                    {"label": f"📍 {word2}をご案内", "text": f"選ぶポイント: {word2}"},
                    {"label": "❌ やめる", "text": "やめる"}
                ]
            else:
                sub_top_str = "や".join(sub_ranks[:2]) if len(sub_ranks) >= 2 else sub_ranks[0]
                point_top_str = "や".join(point_ranks[:2]) if len(point_ranks) >= 2 else point_ranks[0]
                reply_text = (
                    "お出かけは明日、東京都内からお車で、ということでよろしいですか？\n\n"
                    f"今の時期ですと、{sub_top_str}を撮りに行く方が多いようですね。 "
                    f"撮影ポイントとしては{point_top_str}が人気です。この中で興味を感じるものはありますか？"
                )
                choices = []
                for s in sub_ranks[:2]: choices.append({"label": f"📸 被写体: {s}", "text": f"選ぶ被写体: {s}"})
                for p in point_ranks[:2]: choices.append({"label": f"📍 ポイント: {p}", "text": f"選ぶポイント: {p}"})
                choices.append({"label": "❌ やめる", "text": "やめる"})

            session_ref.set({
                "month": default_month, "period": default_period,
                "menu_text": reply_text, "menu_choices_json": json.dumps(choices)
            })

            flex_message = FlexSendMessage(
                alt_text="コンシェルジュからのご提案",
                contents=create_大文字選択肢_ui(reply_text, choices)
            )
            line_bot_api.reply_message(reply_token, flex_message)
            return

        # ─── 🗄️ 2往復目以降 ───
        state = session_doc.to_dict()
        target_month = state.get("month", default_month)
        target_period = state.get("period", default_period)
        
        if "選ぶ被写体:" in user_message or "選ぶポイント:" in user_message:
            word_name = user_message.replace("選ぶ被写体:", "").replace("選ぶポイント:", "").strip()

            base_photos = get_filtered_photos(target_month, target_period, focus_keyword=word_name)
            if not base_photos:
                base_photos = get_filtered_photos(target_month, target_period=None, focus_keyword=word_name, force_ignore_date=True)
            if not base_photos:
                base_photos = get_filtered_photos(target_month, focus_keyword=word_name, force_ignore_month=True)

            matched = []
            for p in base_photos:
                combined_all_text = str(p.get('Title', '')) + str(p.get('Area', '')) + get_photo_place_name(p) + str(p.get('Subject', ''))
                if word_name in combined_all_text: matched.append(p)
                        
            if not matched: matched = base_photos[:2]

            p1 = matched[0]
            p2 = matched[1] if len(matched) > 1 else matched[0]

            flex_message = FlexSendMessage(
                alt_text="入賞作品プレビュー",
                contents=create_作品閲覧_ui(p1, p2, word_name)
            )
            line_bot_api.reply_message(reply_token, flex_message)
            return

        # ─── 🏁 「👉 ここに行く」最終案内 ───
        if "ここに行く:" in user_message:
            word_name = user_message.replace("ここに行く:", "").strip()

            base_photos = get_filtered_photos(target_month, target_period, focus_keyword=word_name)
            if not base_photos:
                base_photos = get_filtered_photos(target_month, target_period=None, focus_keyword=word_name, force_ignore_date=True)
            if not base_photos:
                base_photos = get_filtered_photos(target_month, focus_keyword=word_name, force_ignore_month=True)

            matched = []
            for p in base_photos:
                combined_all_text = str(p.get('Title', '')) + str(p.get('Area', '')) + get_photo_place_name(p) + str(p.get('Subject', ''))
                if word_name in combined_all_text: matched.append(p)
            if not matched: matched = base_photos
            target_photo = random.choice(matched)

            location = get_photo_place_name(target_photo)
            session_ref.delete()

            map_url = f"https://www.google.com/maps/search/?api=1&query={location}"
            route_url = f"https://www.google.com/maps/dir/?api=1&origin={TOKYO_LAT},{TOKYO_LON}&destination={location}&travelmode=driving"

            title = target_photo.get('Title') or "無題"
            author = target_photo.get('Winner') or "不明"
            camera = target_photo.get('Camera') or "情報なし"
            lens = target_photo.get('Lens') or "情報なし"
            settings = target_photo.get('Exposure') or "情報なし"
            weather = target_photo.get('Weather') or "不明"
            
            # 選評やコメント欄に 'null' が入っていた場合の防衛
            guide = target_photo.get('Selection Comments') or target_photo.get('SelectionComments') or ''
            judge_comment = guide
            if not guide or str(guide).lower() in ['null', 'nan', 'none']:
                guide = 'ルートナビ情報はライブラリに保管されています。'
                judge_comment = '素晴らしい構図の名作です。'

            final_image_url = generate_fupc_url(target_photo)
            reply_text = f"「{location}ですね。わかりました。では{location}へのルートをご案内致します。」"
            
            final_bubble_obj = FlexSendMessage(
                alt_text="最終ルート案内レポート",
                contents=create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment, map_url, route_url, final_image_url)
            )
            line_bot_api.reply_message(reply_token, [TextSendMessage(text=reply_text), final_bubble_obj])
            return

    except Exception as e:
        print(f"🔥 Critical: {traceback.format_exc()}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
