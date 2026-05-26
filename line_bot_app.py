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


# ─── 🌸 【CSV構造厳守】画像URL生成関数（一切のキー変更を廃止） ───
def generate_fupc_url(photo_data):
    published = str(photo_data.get('Published', '')).strip()
    pic_file_name = str(photo_data.get('PicFileName', '')).strip()
    if len(published) >= 4 and pic_file_name:
        return f"{IMAGE_BASE_VIEW.rstrip('/')}/{published[:4]}/{published}/{pic_file_name}"
    return "https://fupc.photo/PicsDB/PicsDB4Search/default.jpg"


# ─── 🛡️ 【構造完全維持】一切フィールド名を変えないデータ抽出エンジン ───
def get_filtered_photos(target_month, target_period, focus_keyword=None):
    photos_ref = db.collection('Master_Photos')
    
    # 月の表記ゆれ候補
    m_num = target_month.replace("月", "").strip()
    month_candidates = [m_num, m_num.zfill(2), f"{m_num}月", f"{m_num}月 "]
    try: month_candidates.append(int(m_num))
    except: pass

    # インデックス自爆を避けるため、Month単一クエリでストリームロード
    docs = photos_ref.where('Month', 'in', month_candidates).stream()
    
    filtered_photos = []
    for doc in docs:
        pdata = doc.to_dict()
        if not pdata: continue
        
        # 🚨 キーの小文字統一（.lower()）を完全撤廃。CSVと100%同じフィールド名で直接判定
        db_period = str(pdata.get('Period', '')).strip()
        if target_period not in db_period: continue
            
        pub = pdata.get('Published')
        pic = pdata.get('PicFileName')
        if not pub or not pic: continue

        # 2往復目のキーワード指定がある場合の部分一致抽出
        if focus_keyword:
            search_pool = (
                str(pdata.get('Title', '')) + 
                str(pdata.get('Location', '')) + 
                str(pdata.get('Prefecture', ''))
            )
            if focus_keyword not in search_pool:
                continue
        else:
            # 1往復目は東京近郊エリアをカバー（裏設定として完全隠蔽）
            pref = str(pdata.get('Prefecture', ''))
            if pref and not any(x in pref for x in ["長野", "山梨", "静岡", "群馬", "新潟", "埼玉", "東京", "神奈川", "千葉", "茨城", "栃木", "福島"]):
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


# ─── 🖼️ 【アスペクト比完全維持・CSV構造100%準拠】入賞作品2点紙芝居UI ───
def create_作品閲覧_ui(photo1, photo2, word_name):
    title1 = photo1.get('Title') or "無題"
    author1 = photo1.get('Author') or "写真家"
    loc1 = photo1.get('Location') or photo1.get('Prefecture') or "厳選撮影地"
    img_url1 = generate_fupc_url(photo1)

    title2 = photo2.get('Title') or "無題"
    author2 = photo2.get('Author') or "写真家"
    loc2 = photo2.get('Location') or photo2.get('Prefecture') or "厳選撮影地"
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


# ─── 🏛️ 【CSV構造100%準拠】元の添削指導UI ───
def create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment, map_url, route_url, image_url):
    return {
      "type": "bubble",
      "backgroundColor": "#ffffff",
      "hero": {
          "type": "image", 
          "url": image_url, 
          "size": "full", 
          "aspectRatio": "20:13", 
          "aspectMode": "fit"
      },
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
          {"type": "box", "layout": "vertical", "margin": "xxl", "backgroundColor": "#f7f8fa", "cornerRadius": "md", "paddingAll": "md", "contents": [{"type": "text", "text": "🎓 【レベルアップ相談室・添削指導】", "weight": "bold", "size": "md", "color": "#e67e22"}, {"type": "text", "text": judge_comment, "wrap": True, "size": "sm", "color": "#333333", "margin": "sm"}]},
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
        print(f"🔥 Webhook Critical Error: {traceback.format_exc()}")
    return 'OK', 200


# --- 対話アナリティクスエンジン ---
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
                menu_obj = BubbleContainer.new_from_json_dict(create_大文字選択肢_ui(menu_text, choices))
                line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="コンシェルジュ提案メニュー", contents=menu_obj))
                return

        # ─── 📊 ①＆②: 【1往復目】 36分割マトリクス集計 ───
        if not session_doc.exists or any(k in user_message for k in ["明日", "おすすめ", "お勧め", "撮影"]):
            print("🚀 純度100%のCSVフィールド直結集計を開始...")
            
            extracted_loc = None
            for k in ["長野", "山梨", "静岡", "福島", "新潟", "山形"]:
                if k in user_message: extracted_loc = k
                
            base_photos = get_filtered_photos(default_month, default_period, focus_keyword=extracted_loc)

            if not base_photos:
                line_bot_api.reply_message(reply_token, TextSendMessage(text="誠に恐れ入ります。ただいま書棚をお探しいたしましたが、明日のご案内路にふさわしい名作の記録が、あいにく見つかりませんでした。少し時期やキーワードを変えてお声がけいただけますと幸いです。"))
                return

            photo_keywords = ["新緑", "滝", "富士山", "残雪", "桜", "紅葉", "茶畑", "新幹線", "清流", "海岸", "雲海", "ツツジ"]
            
            subjects, point_names, trends = [], [], []
            for p in base_photos:
                title_str = str(p.get('Title', ''))
                loc_str = str(p.get('Location', ''))
                combined_text = title_str + loc_str + get_photo_place_name(p)
                
                for kw in photo_keywords:
                    if kw in combined_text: subjects.append(kw)
                
                pt = get_photo_place_name(p)
                if pt and pt != "厳選撮影地": point_names.append(pt)
                
                pub = p.get('Published')
                try:
                    pub_year = int(str(pub)[:4])
                    if (now.year - 3) <= pub_year <= now.year:
                        for kw in photo_keywords:
                            if kw in combined_text: trends.append(kw)
                        if pt and pt != "厳選撮影地": trends.append(pt)
                except: pass

            sub_ranks = [w[0] for w in Counter(subjects).most_common(3) if w[0]]
            point_ranks = [w[0] for w in Counter(point_names).most_common(3) if w[0]]
            trend_ranks = [w[0] for w in Counter(trends).most_common(3) if w[0]]

            if not sub_ranks: sub_ranks = ["風景"]
            if not point_ranks: point_ranks = [get_photo_place_name(base_photos[0]) if base_photos else "厳選地"]

            sub_top_str = "や".join(sub_ranks[:2]) if len(sub_ranks) >= 2 else sub_ranks[0]
            point_top_str = "や".join(point_ranks[:2]) if len(point_ranks) >= 2 else point_ranks[0]
            trend_str = f"最近は{trend_ranks[0]}を取りに行く方が増えているようです。" if trend_ranks else ""

            reply_text = (
                "お出かけは明日、東京都内からお車で、ということでよろしいですか？\n\n"
                f"今の時期ですと、{sub_top_str}を撮りに行く方が多いようですね。 "
                f"撮影ポイントとしては{point_top_str}が人気です。{trend_str}この中で興味を感じるものはありますか？"
            )

            choices = []
            for s in sub_ranks[:2]: choices.append({"label": f"📸 被写体: {s}", "text": f"選ぶ被写体: {s}"})
            for p in point_ranks[:2]: choices.append({"label": f"📍 ポイント: {p}", "text": f"選ぶポイント: {p}"})
            choices.append({"label": "❌ やめる", "text": "やめる"})

            session_ref.set({
                "month": default_month, "period": default_period,
                "menu_text": reply_text, "menu_choices_json": json.dumps(choices)
            })

            menu_obj = BubbleContainer.new_from_json_dict(create_大文字選択肢_ui(reply_text, choices))
            line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="コンシェルジュからのご提案", contents=menu_obj))
            return

        # ─── 🗄️ 2往復目以降 ───
        state = session_doc.to_dict()
        target_month = state.get("month", default_month)
        target_period = state.get("period", default_period)
        
        if "選ぶ被写体:" in user_message or "選ぶポイント:" in user_message:
            word_name = user_message.replace("選ぶ被写体:", "").replace("選ぶポイント:", "").strip()

            base_photos = get_filtered_photos(target_month, target_period, focus_keyword=word_name)
            if not base_photos: 
                base_photos = get_filtered_photos(target_month, target_period, focus_keyword=None)

            matched = []
            for p in base_photos:
                combined_all_text = str(p.get('Title', '')) + str(p.get('Location', '')) + get_photo_place_name(p)
                if word_name in combined_all_text: matched.append(p)
                        
            if not matched: matched = base_photos[:2]

            p1 = matched[0]
            p2 = matched[1] if len(matched) > 1 else matched[0]

            carousel_obj = CarouselContainer.new_from_json_dict(create_作品閲覧_ui(p1, p2, word_name))
            line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="入賞作品プレビュー", contents=carousel_obj))
            return

        # ─── 🏁 「👉 ここに行く」が押された場合の最終クロージング ───
        if "ここに行く:" in user_message:
            word_name = user_message.replace("ここに行く:", "").strip()

            base_photos = get_filtered_photos(target_month, target_period, focus_keyword=word_name)
            if not base_photos:
                base_photos = get_filtered_photos(target_month, target_period, focus_keyword=None)

            matched = []
            for p in base_photos:
                combined_all_text = str(p.get('Title', '')) + str(p.get('Location', '')) + get_photo_place_name(p)
                if word_name in combined_all_text: matched.append(p)
            if not matched: matched = base_photos
            target_photo = random.choice(matched)

            location = get_photo_place_name(target_photo) or word_name
            session_ref.delete()

            map_url = f"https://www.google.com/maps/search/?api=1&query={location}"
            route_url = f"https://www.google.com/maps/dir/?api=1&origin={TOKYO_LAT},{TOKYO_LON}&destination={location}&travelmode=driving"

            title = target_photo.get('Title') or "無題"
            author = target_photo.get('Author') or "不明"
            camera = target_photo.get('Camera_Body') or "情報なし"
            lens = target_photo.get('Lens') or "情報なし"
            settings = target_photo.get('Exposure') or f"F{target_photo.get('Aperture', '-')} / ISO {target_photo.get('ISO', '-')}"
            weather = target_photo.get('Weather') or "不明"
            guide = target_photo.get('Guide_Page') or target_photo.get('Context_Advice') or 'ルートナビ情報は本棚に保管されています。'
            judge_comment = target_photo.get('Judge_Comment_Summary') or target_photo.get('Logic_Advice') or '素晴らしい構図の名作です。'

            final_image_url = generate_fupc_url(target_photo)
            reply_text = f"「{location}ですね。わかりました。では{location}へのルートをご案内致します。」"
            
            final_bubble_obj = BubbleContainer.new_from_json_dict(create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment, map_url, route_url, final_image_url))
            line_bot_api.reply_message(reply_token, [TextSendMessage(text=reply_text), FlexSendMessage(alt_text="最終ルート案内レポート", contents=final_bubble_obj)])
            return

    except Exception as e:
        print(f"🔥 Critical: {traceback.format_exc()}")
        try:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="誠に恐れ入ります。ただいま書棚の通信が一時的に混み合っております。お手数ですが、もう一度お声がけいただけますと幸いです。"))
        except: pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
