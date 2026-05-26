import os
import json
import random
import math
import traceback
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi
from linebot.models import TextSendMessage, FlexSendMessage
import firebase_admin
from firebase_admin import credentials, firestore
from collections import Counter

app = Flask(__name__)

# ==========================================================
# 📸 定数定義（仕様書に完全準拠）
# ==========================================================
IMAGE_BASE_VIEW = "https://fupc.photo/PicsDB/PicsDB4Search/"
TOKYO_LAT = 35.6895  # 現在地リファレンス：新宿
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


# --- ドキュメントから安全に緯度経度を抽出 ---
def get_lat_lon(data):
    flat = {str(k).lower(): v for k, v in data.items() if v}
    lat = flat.get('latitude') or flat.get('lat')
    lon = flat.get('longitude') or flat.get('lon')
    try:
        if lat is not None and lon is not None:
            return float(lat), float(lon)
    except: pass
    return None


# --- 項目「Place」が空欄の場合「Area」を表示するルール ---
def get_photo_place_name(pdata):
    flat = {str(k).lower(): v for k, v in pdata.items() if v}
    place = flat.get('place') or pdata.get('Place')
    if place and str(place).lower() != 'nan' and str(place).strip():
        return str(place).strip()
    area = flat.get('area') or pdata.get('Area') or flat.get('location') or pdata.get('Location')
    if area and str(area).lower() != 'nan' and str(area).strip():
        return str(area).strip()
    return ""


# --- 🔗 仕様書に完全準拠した閲覧用画像URL生成 ---
def generate_fupc_url(photo_data):
    flat = {str(k).lower(): v for k, v in photo_data.items() if v}
    published = str(flat.get('published') or photo_data.get('Published', '')).strip()
    pic_file_name = str(flat.get('picfilename') or flat.get('pic_file_name') or photo_data.get('PicFileName', '')).strip()
    return f"{IMAGE_BASE_VIEW.rstrip('/')}/{published[:4]}/{published}/{pic_file_name}"


# --- 🛡️ 表記ゆれをinクエリで完全中和してロードする高速関数 ---
def get_filtered_photos(target_month, target_period):
    photos_ref = db.collection('Master_Photos')
    
    # "5月" から ["5", "05", "5月", "5月 "] という候補を作り、inクエリで最速抽出
    m_num = target_month.replace("月", "").strip()
    month_candidates = [m_num, m_num.zfill(2), f"{m_num}月", f"{m_num}月 "]
    
    docs = photos_ref.where('Month', 'in', month_candidates).stream()

    filtered_photos = []
    for doc in docs:
        pdata = doc.to_dict()
        if not pdata: continue
        
        db_period = str(pdata.get('Period', '')).strip()
        if target_period not in db_period: continue
            
        flat_data = {str(k).lower(): v for k, v in pdata.items() if v}
        pub = flat_data.get('published') or pdata.get('Published')
        pic = flat_data.get('picfilename') or flat_data.get('pic_file_name') or pdata.get('PicFileName')
        sub = flat_data.get('subject') or pdata.get('Subject')
        place_name = get_photo_place_name(pdata)
        
        if not pub or not pic or not sub or not place_name or len(str(pub).strip()) < 4:
            continue
            
        coords = get_lat_lon(pdata)
        if coords:
            if calculate_distance(TOKYO_LAT, TOKYO_LON, coords[0], coords[1]) <= 250.0:
                filtered_photos.append(pdata)
        else:
            pref = str(flat_data.get('prefecture') or pdata.get('Prefecture', ''))
            if any(x in pref for x in ["東京", "神奈川", "千葉", "埼玉", "茨城", "栃木", "群馬", "山梨", "長野", "静岡", "福島", "新潟"]):
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


# --- 🖼️ 入賞作品2点スライド仕様の紙芝居UI ---
def create_作品閲覧_ui(photo1, photo2, word_name):
    def make_slide(p):
        flat = {str(k).lower(): v for k, v in p.items() if v}
        title = flat.get('title') or flat.get('subject') or p.get('Title')
        author = flat.get('author') or flat.get('winner') or p.get('Author')
        loc = get_photo_place_name(p)
        return {
            "type": "bubble",
            # ─── 🌸 呼び出し関数名を正しく generate_fupc_url に完全結合 ───
            "hero": {"type": "image", "url": generate_fupc_url(p), "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
            "body": {
                "type": "box", "layout": "vertical", "spacing": "sm",
                "contents": [
                    {"type": "text", "text": f"📍 {loc}", "weight": "bold", "size": "md", "wrap": True},
                    {"type": "text", "text": f"「{title}」 (撮影: {author} 様)", "size": "sm", "color": "#555555", "wrap": True}
                ]
            }
        }
    return {
        "type": "carousel",
        "contents": [
            make_slide(photo1),
            make_slide(photo2),
            {
                "type": "bubble",
                "body": {
                    "type": "box", "layout": "vertical", "spacing": "md", "alignItems": "center", "justifyContent": "center",
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


# --- 🏛️ 【完全維持】元の添削指導UI ---
def create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment, map_url, route_url):
    global TARGET_IMAGE_URL
    return {
      "type": "bubble",
      "hero": {"type": "image", "url": TARGET_IMAGE_URL, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
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
    global TARGET_IMAGE_URL
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
                line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="コンシェルジュ提案メニュー", contents=create_大文字選択肢_ui(menu_text, choices)))
                return

        # ─── 📊 ①＆②: 【1往復目】 36分割マトリクス × 半径250kmリアルタイム集計 ───
        if not session_doc.exists or any(k in user_message for k in ["明日", "おすすめ", "お勧め", "撮影"]):
            base_photos = get_filtered_photos(default_month, default_period)

            if not base_photos:
                line_bot_api.reply_message(reply_token, TextSendMessage(text=f"申し訳ございません。現在の時期【{default_month}{default_period}】かつ【東京から半径250km圏内】に合致する風景写真データが本棚に見つかりませんでした。"))
                return

            subjects, point_names, trends = [], [], []
            for p in base_photos:
                flat = {str(k).lower(): v for k, v in p.items() if v}
                subjects.append(str(flat.get('subject') or p.get('Subject')).strip())
                point_names.append(get_photo_place_name(p))
                
                pub = flat.get('published') or p.get('Published')
                try:
                    pub_year = int(str(pub)[:4])
                    if (now.year - 3) <= pub_year <= now.year:
                        trends.append(str(flat.get('subject') or p.get('Subject')).strip())
                        trends.append(get_photo_place_name(p))
                except: pass

            sub_ranks = [w[0] for w in Counter(subjects).most_common(3)]
            point_ranks = [w[0] for w in Counter(point_names).most_common(3)]
            trend_ranks = [w[0] for w in Counter(trends).most_common(3)]

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

            line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="コンシェルジュからのご提案", contents=create_大文字選択肢_ui(reply_text, choices)))
            return

        # ─── 🗄️ 2往復目以降：固定された月・旬の記憶から完全に復元 ───
        state = session_doc.to_dict()
        target_month = state.get("month", default_month)
        target_period = state.get("period", default_period)
        base_photos = get_filtered_photos(target_month, target_period)

        # ─── 📸 被写体 or ポイントボタンが押された場合（2枚スライド表示） ───
        if "選ぶ被写体:" in user_message or "選ぶポイント:" in user_message:
            is_sub = "選ぶ被写体:" in user_message
            word_name = user_message.replace("選ぶ被写体:", "").replace("選ぶポイント:", "").strip()

            matched = []
            for p in base_photos:
                if is_sub:
                    flat = {str(k).lower(): v for k, v in p.items() if v}
                    sub = flat.get('subject') or p.get('Subject')
                    if sub and word_name in str(sub): matched.append(p)
                else:
                    if word_name in get_photo_place_name(p): matched.append(p)
                        
            if not matched: matched = [p for p in base_photos if word_name in str(p.values())]
            if not matched: matched = base_photos[:2]

            p1 = matched[0]
            p2 = matched[1] if len(matched) > 1 else matched[0]

            state["selected_type"] = "subject" if is_sub else "place"
            state["selected_word"] = word_name
            session_ref.set(state)

            line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="入賞作品プレビュー", contents=create_作品閲覧_ui(p1, p2, word_name)))
            return

        # ─── 🏁 「👉 ここに行く」が押された場合の最終クロージング ───
        if "ここに行く:" in user_message:
            word_name = user_message.replace("ここに行く:", "").strip()
            sel_type = state.get("selected_type", "place")

            matched = []
            for p in base_photos:
                if word_name in get_photo_place_name(p) or word_name in str(p.values()): matched.append(p)
            if not matched: matched = base_photos
            target_photo = random.choice(matched)

            location = get_photo_place_name(target_photo) or word_name

            if sel_type == "place" or "ポイント" in user_message:
                session_ref.delete()

                # 公式ユニバーサルリンクでGoogle Mapsを起動
                map_url = f"https://www.google.com/maps/search/?api=1&query={location}"
                route_url = f"https://www.google.com/maps/dir/?api=1&origin={TOKYO_LAT},{TOKYO_LON}&destination={location}&travelmode=driving"

                flat_data = {str(k).lower(): v for k, v in target_photo.items() if v}
                published = flat_data.get('published') or target_photo.get('Published')
                pic_file_name = flat_data.get('picfilename') or flat_data.get('pic_file_name') or target_photo.get('PicFileName')
                
                pub_str = str(published).strip()
                TARGET_IMAGE_URL = f"{IMAGE_BASE_VIEW.rstrip('/')}/{pub_str[:4]}/{pub_str}/{str(pic_file_name).strip()}"

                title = flat_data.get('title') or flat_data.get('subject') or target_photo.get('Title') or "無題"
                author = flat_data.get('author') or flat_data.get('winner') or target_photo.get('Author') or "不明"
                camera = flat_data.get('camera_body') or flat_data.get('camera') or target_photo.get('Camera_Body') or "情報なし"
                lens = flat_data.get('lens') or target_photo.get('Lens') or "情報なし"
                settings = flat_data.get('exposure') or f"F{flat_data.get('aperture', '-')} / ISO {flat_data.get('iso', '-')}"
                weather = flat_data.get('weather') or target_photo.get('Weather', '不明')
                guide = flat_data.get('guide_page') or flat_data.get('context_advice') or 'ルートナビ情報は本棚に保管されています。'
                judge_comment = flat_data.get('judge_comment_summary') or flat_data.get('logic_advice') or '素晴らしい構図の名作です。'

                reply_text = f"「{location}ですね。わかりました。では{location}へのルートをご案内致します。」"
                bubble_json = create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment, map_url, route_url)
                
                line_bot_api.reply_message(reply_token, [TextSendMessage(text=reply_text), FlexSendMessage(alt_text="最終ルート案内レポート", contents=bubble_json)])
                return
            else:
                reply_text = f"「{word_name}ですとこのあたりに撮りに行く方がおおいようです。」"
                
                extracted_places = []
                for p in matched:
                    p_name = get_photo_place_name(p)
                    if p_name and p_name not in extracted_places:
                        extracted_places.append(p_name)
                        if len(extracted_places) >= 3: break
                
                if not extracted_places: extracted_places = ["周辺主要スポット"]

                sub_choices = []
                for pl in extracted_places:
                    sub_choices.append({"label": f"📍 ポイント: {pl}", "text": f"選ぶポイント: {pl}"})
                sub_choices.append({"label": "❌ やめる", "text": "やめる"})

                line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="周辺の撮影ポイント提案", contents=create_大文字選択肢_ui(reply_text, sub_choices)))
                return

    except Exception as e:
        raw_error_trace = traceback.format_exc()
        try:
            line_bot_api.reply_message(reply_token, TextSendMessage(text=f"❌ システム内部クラッシュ詳細:\n{raw_error_trace}"))
        except: pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
