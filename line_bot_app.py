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
from openai import OpenAI
from collections import Counter

app = Flask(__name__)

# ==========================================================
# 📸 定数定義（仕様書に完全準拠。将来のサーバー移転時もここを変えるだけ）
# ==========================================================
IMAGE_BASE_VIEW = "https://fupc.photo/PicsDB/PicsDB4Search/"
TOKYO_LAT = 35.6895  # 東京の基準点（現在地リファレンス：新宿・都庁付近）
TOKYO_LON = 139.6917

# --- LINE / OpenAI API の初期化 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

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


# --- 2点間の距離を算出するハヴェルサイン公式（半径250km判定用ツール） ---
def calculate_distance(lat1, lon1, lat2, lon2):
    rad_lat1, rad_lon1 = math.radians(lat1), math.radians(lon1)
    rad_lat2, rad_lon2 = math.radians(lat2), math.radians(lon2)
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


# --- 項目「Place」が空欄の場合「Area」を表示するルール対応抽出 ---
def get_photo_place_name(pdata):
    flat = {str(k).lower(): v for k, v in pdata.items() if v}
    place = flat.get('place') or pdata.get('Place')
    if place and str(place).lower() != 'nan' and str(place).strip():
        return str(place).strip()
    area = flat.get('area') or pdata.get('Area') or flat.get('location') or pdata.get('Location')
    if area and str(area).lower() != 'nan' and str(area).strip():
        return str(area).strip()
    return "未知の撮影地"


# --- 🔗 仕様書に完全準拠した閲覧用画像URL生成 ---
def generate_fupc_url(photo_data):
    flat = {str(k).lower(): v for k, v in photo_data.items() if v}
    published = str(flat.get('published') or photo_data.get('Published', '')).strip()
    pic_file_name = str(flat.get('picfilename') or flat.get('pic_file_name') or photo_data.get('PicFileName', '')).strip()
    if len(published) >= 4 and pic_file_name:
        return f"{IMAGE_BASE_VIEW.rstrip('/')}/{published[:4]}/{published}/{pic_file_name}"
    return "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=1000&q=80"


# --- 🛡️ インデックスエラーを100%回避する超軽量データフィルター（背骨） ---
def get_filtered_photos(target_month, target_period):
    photos_ref = db.collection('Master_Photos')
    # インデックスが標準保証されているMonth（月）だけでロードし、Period（旬）はメモリで安全に弾く
    docs = photos_ref.where('Month', '==', target_month).stream()
    
    filtered_photos = []
    for doc in docs:
        pdata = doc.to_dict()
        if not pdata: continue
        
        db_period = str(pdata.get('Period', '')).strip()
        if db_period != target_period: continue
            
        coords = get_lat_lon(pdata)
        if coords:
            # 半径250km以内かを厳密に判定
            if calculate_distance(TOKYO_LAT, TOKYO_LON, coords[0], coords[1]) <= 250.0:
                filtered_photos.append(pdata)
        else:
            flat_data = {str(k).lower(): v for k, v in pdata.items() if v}
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
        title = flat.get('title') or flat.get('subject') or p.get('Title', '無題')
        author = flat.get('author') or flat.get('winner') or p.get('Author', '写真家')
        loc = get_photo_place_name(p)
        return {
            "type": "bubble",
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


# --- 🏛️ 【完全維持 ＋ 地図ナビ公式リンク対応】元の添削指導UI ---
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


# --- ⚔️ 【防壁完全復活】LINE Webhook 受信口 ---
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
    target_month = f"{now.month}月"
    target_period = "初旬" if now.day <= 10 else "中旬" if now.day <= 20 else "下旬"

    try:
        session_ref = db.collection('User_Sessions').document(user_id)
        session_doc = session_ref.get()

        # ─── ❌ 「やめる」
        if user_message == "やめる":
            session_ref.delete()
            line_bot_api.reply_message(reply_token, TextSendMessage(text="ご用がありましたら、いつでもお声がけください。"))
            return

        # ─── 🔙 「戻る」
        if user_message == "戻る" and session_doc.exists:
            state = session_doc.to_dict()
            menu_text = state.get("menu_text", "")
            choices = json.loads(state.get("menu_choices_json", "[]"))
            if menu_text and choices:
                line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="コンシェルジュ提案メニュー", contents=create_大文字選択肢_ui(menu_text, choices)))
                return

        # ─── 📊 ①＆②: 1往復目のリアルタイム集計（安全な超軽量フィルターを適用） ───
        if not session_doc.exists or any(k in user_message for k in ["明日", "おすすめ", "お勧め", "撮影"]):
            print("🚀 初期集計：超軽量フィルターでロードします...")
            base_photos = get_filtered_photos(target_month, target_period)

            # キーワード集計
            subjects, point_names, trends = [], [], []
            for p in base_photos:
                flat = {str(k).lower(): v for k, v in p.items() if v}
                sub = flat.get('subject') or p.get('Subject')
                if sub and str(sub).lower() != 'nan' and str(sub).strip(): subjects.append(str(sub).strip())
                pt = get_photo_place_name(p)
                if pt and pt != "未知の撮影地": point_names.append(pt)
                
                pub = flat.get('published') or flat.get('year') or p.get('Published')
                if pub:
                    try:
                        pub_year = int(str(pub)[:4])
                        if (now.year - 3) <= pub_year <= now.year:
                            if sub and str(sub).lower() != 'nan' and str(sub).strip(): trends.append(str(sub).strip())
                            area_val = flat.get('area') or p.get('Area')
                            if area_val and str(area_val).lower() != 'nan' and str(area_val).strip(): trends.append(str(area_val).strip())
                    except: pass

            sub_ranks = [w[0] for w in Counter(subjects).most_common(3)]
            point_ranks = [w[0] for w in Counter(point_names).most_common(3)]
            trend_ranks = [w[0] for w in Counter(trends).most_common(3)]

            sub_top_str = "や".join(sub_ranks[:2]) if sub_ranks else "新緑"
            point_top_str = "や".join(point_ranks[:2]) if point_ranks else "人気撮影地"
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
                "month": target_month, "period": target_period,
                "menu_text": reply_text, "menu_choices_json": json.dumps(choices)
            })

            line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="コンシェルジュからのご提案", contents=create_大文字選択肢_ui(reply_text, choices)))
            return

        # ─── 🗄️ 【バグ完全清掃】2往復目以降も「生クエリ」を完全廃止し、安全な関数に統一 ───
        state = session_doc.to_dict()
        base_photos = get_filtered_photos(target_month, target_period)

        # ─── 📸 被写体 or ポイントが選ばれた場合 ───
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

            location = get_photo_place_name(target_photo)

            if sel_type == "place" or "ポイント" in user_message:
                session_ref.delete()

                # 公式URLスキームでGoogle Mapsを1秒起動
                map_url = f"https://www.google.com/maps/search/?api=1&query={location}"
                route_url = f"https://www.google.com/maps/dir/?api=1&origin={TOKYO_LAT},{TOKYO_LON}&destination={location}&travelmode=driving"

                flat_data = {str(k).lower(): v for k, v in target_photo.items() if v}
                published = flat_data.get('published') or target_photo.get('Published')
                pic_file_name = flat_data.get('picfilename') or flat_data.get('pic_file_name') or target_photo.get('PicFileName')
                
                if published and pic_file_name:
                    pub_str = str(published).strip()
                    TARGET_IMAGE_URL = f"{IMAGE_BASE_VIEW.rstrip('/')}/{pub_str[:4]}/{pub_str}/{str(pic_file_name).strip()}"
                else:
                    TARGET_IMAGE_URL = "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=1000&q=80"

                title = flat_data.get('title') or flat_data.get('subject') or target_photo.get('Title', '無題')
                author = flat_data.get('author') or flat_data.get('winner') or target_photo.get('Author', '不明')
                camera = flat_data.get('camera_body') or flat_data.get('camera') or target_photo.get('Camera_Body', '情報なし')
                lens = flat_data.get('lens') or target_photo.get('Lens', '情報なし')
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
                    if p_name and p_name != "未知の撮影地" and p_name not in extracted_places:
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
        # 万が一の際もサイレントクラッシュせず、必ずメッセージで受け流す強固なセーフティ
        print(f"🔥 Internal Session Error:\n{traceback.format_exc()}")
        try:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="本棚の通信が一時的に瞬断しました。もう一度「明日のおすすめ」とお声がけください。"))
        except: pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
