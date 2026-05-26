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
# 📸 定数定義（仕様書に準拠。将来のサーバー移転時もここを変えるだけ）
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


# --- ドキュメントから安全に緯度経度を抽出するロジック ---
def get_lat_lon(data):
    flat = {str(k).lower(): v for k, v in data.items() if v}
    lat = flat.get('latitude') or flat.get('lat')
    lon = flat.get('longitude') or flat.get('lon')
    try:
        if lat is not None and lon is not None:
            return float(lat), float(lon)
    except:
        pass
    return None


# --- 🔗 仕様書に完全準拠したFUPCサーバー閲覧用画像URL生成パーツ ---
def generate_fupc_url(photo_data):
    flat = {str(k).lower(): v for k, v in photo_data.items() if v}
    published = str(flat.get('published') or photo_data.get('Published', '')).strip()
    pic_file_name = str(flat.get('picfilename') or flat.get('pic_file_name') or photo_data.get('PicFileName', '')).strip()
    if len(published) >= 4 and pic_file_name:
        return f"{IMAGE_BASE_VIEW.rstrip('/')}/{published[:4]}/{published}/{pic_file_name}"
    return "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=1000&q=80"


# --- 🎴 【大きな文字・大きなボタン】視認性抜群のカスタム選択肢メニューの組み立て ---
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


# --- 🖼️ 【本物画像2点スライド仕様】過去の入賞作品を大画面で見せる紙芝居UI ---
def create_作品閲覧_ui(photo1, photo2, word_name):
    def make_slide(p):
        flat = {str(k).lower(): v for k, v in p.items() if v}
        title = flat.get('title') or flat.get('subject') or p.get('Title', '無題')
        author = flat.get('author') or flat.get('winner') or p.get('Author', '写真家')
        loc = flat.get('location') or flat.get('area') or p.get('Location', '撮影地')
        if flat.get('place') and str(flat.get('place')) != 'nan': loc = f"{loc} {flat.get('place')}"
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
                        {"type": "text", "text": f"🏁 【{word_name}】のアプローチ", "weight": "bold", "size": "md", "margin": "md"},
                        {"type": "button", "action": {"type": "message", "label": "👉 ここに行く", "text": f"ここに行く: {word_name}"}, "style": "primary", "color": "#1DB954", "margin": "sm"},
                        {"type": "button", "action": {"type": "message", "label": "⬅️ 戻る", "text": "戻る"}, "style": "secondary", "margin": "sm"},
                        {"type": "button", "action": {"type": "message", "label": "❌ やめる", "text": "やめる"}, "style": "link", "color": "#ff0000", "margin": "sm"}
                    ]
                }
            }
        ]
    }


# --- 🏛️ 【完全維持 ＋ 地図ナビ対応】元の添削指導UI ---
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
            "type": "box", "layout": "vertical", "margin": "md", "spacing": "sm",
            "contents": [
                {"type": "button", "action": {"type": "uri", "label": "🗺️ Googleマップで場所を確認", "uri": map_url}, "style": "secondary"},
                {"type": "button", "action": {"type": "uri", "label": "🚗 東京からの高速ルートナビ", "uri": route_url}, "style": "primary", "color": "#1DB954"}
            ]
          }
        ]
      }
    }


# --- LINE Webhook 受信口 ---
@app.route("/callback", methods=['POST'])
def callback():
    request_json = request.get_json()
    events = request_json.get('events', [])
    for event in events:
        if event.get('type') == 'message' and event['message'].get('type') == 'text':
            handle_line_message(event)
    return 'OK', 200


# --- 8. データベース連動型・対話アナリティクスエンジン ---
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

        # ─── ❌ 「やめる」ボタンの即時クローズ処置 ───
        if user_message == "やめる":
            session_ref.delete()
            line_bot_api.reply_message(reply_token, TextSendMessage(text="ご用がありましたら、いつでもお声がけください。"))
            return

        # ─── 🔙 「戻る」ボタンによる元の集計選択メニューへの復元 ───
        if user_message == "戻る" and session_doc.exists:
            state = session_doc.to_dict()
            menu_text = state.get("menu_text", "")
            choices = json.loads(state.get("menu_choices_json", "[]"))
            if menu_text and choices:
                state["status"] = "SELECTING"
                session_ref.set(state)
                menu_json = create_大文字選択肢_ui(menu_text, choices)
                line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="コンシェルジュ提案メニュー", contents=menu_json))
                return

        # ─── 📊 ①＆②: 【1往復目 / 記憶がない状態】 36分割マトリクス × 半径250kmリアルタイム集計 ───
        if not session_doc.exists or any(k in user_message for k in ["明日", "おすすめ", "お勧め", "撮影"]):
            print("初期集計を開始します...")
            photos_ref = db.collection('Master_Photos')
            docs = photos_ref.where('Month', '==', target_month).where('Period', '==', target_period).stream()
            
            base_photos = []
            for doc in docs:
                pdata = doc.to_dictimport os
import json
import random
import traceback
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi
from linebot.models import TextSendMessage, FlexSendMessage
import firebase_admin
from firebase_admin import credentials, firestore
from openai import OpenAI

app = Flask(__name__)

# ==========================================================
# 📸 【FUPC管理サーバー】画像閲覧用ベースURL（将来の移転時はここを変更）
# ==========================================================
IMAGE_BASE_VIEW = "https://fupc.photo/PicsDB/PicsDB4Search/"

# --- 1. LINE API の初期化 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

# --- 2. OpenAI API の初期化 ---
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# --- 3. Firebase / Firestore の初期化 ---
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


# --- 4. LINE Webhook 受信口 ---
@app.route("/callback", methods=['POST'])
def callback():
    try:
        request_json = request.get_json()
        events = request_json.get('events', [])
        for event in events:
            if event.get('type') == 'message' and event['message'].get('type') == 'text':
                handle_line_message(event)
    except Exception as e:
        print(f"Error processing webhook event: {e}")
    return 'OK', 200


# --- 5. 【完全維持 ＋ 本物の入賞作品画像対応】元の添削指導UI ---
def create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment):
    global TARGET_IMAGE_URL
    image_url = TARGET_IMAGE_URL if 'TARGET_IMAGE_URL' in globals() else "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=1000&q=80"

    flex_bubble = {
      "type": "bubble",
      "hero": {
        "type": "image",
        "url": image_url,
        "size": "full",
        "aspectRatio": "20:13",
        "aspectMode": "cover"
      },
      "body": {
        "type": "box",
        "layout": "vertical",
        "contents": [
          {"type": "text", "text": "🌸 AIコンシェル浅厳選提案", "weight": "bold", "color": "#1DB954", "size": "sm"},
          {"type": "text", "text": location, "weight": "bold", "size": "xl", "margin": "md", "wrap": True},
          {
            "type": "box",
            "layout": "vertical",
            "margin": "lg",
            "spacing": "sm",
            "contents": [
              {
                "type": "box",
                "layout": "baseline",
                "spacing": "sm",
                "contents": [
                  {"type": "text", "text": "作品名", "color": "#aaaaaa", "size": "sm", "flex": 2},
                  {"type": "text", "text": f"{title} (撮影: {author} 様)", "wrap": True, "color": "#666666", "size": "sm", "flex": 5}
                ]
              },
              {
                "type": "box",
                "layout": "baseline",
                "spacing": "sm",
                "contents": [
                  {"type": "text", "text": "推奨機材", "color": "#aaaaaa", "size": "sm", "flex": 2},
                  {"type": "text", "text": f"{camera}\n{lens}", "wrap": True, "color": "#666666", "size": "sm", "flex": 5}
                ]
              },
              {
                "type": "box",
                "layout": "baseline",
                "spacing": "sm",
                "contents": [
                  {"type": "text", "text": "撮影設定", "color": "#aaaaaa", "size": "sm", "flex": 2},
                  {"type": "text", "text": settings, "wrap": True, "color": "#666666", "size": "sm", "flex": 5}
                ]
              }
            ]
          },
          {"type": "separator", "margin": "xxl"},
          {
            "type": "box",
            "layout": "vertical",
            "margin": "xxl",
            "contents": [
              {"type": "text", "text": "📖 【現地ナビ・アクセス】", "weight": "bold", "size": "md", "color": "#111111"},
              {"type": "text", "text": guide, "wrap": True, "size": "sm", "color": "#555555", "margin": "md"}
            ]
          },
          {"type": "separator", "margin": "xxl"},
          {
            "type": "box",
            "layout": "vertical",
            "margin": "xxl",
            "backgroundColor": "#f7f8fa",
            "cornerRadius": "md",
            "paddingAll": "md",
            "contents": [
              {"type": "text", "text": "🎓 【レベルアップ相談室・添削指導】", "weight": "bold", "size": "md", "color": "#e67e22"},
              {"type": "text", "text": judge_comment, "wrap": True, "size": "sm", "color": "#333333", "margin": "sm"}
            ]
          }
        ]
      }
    }
    return flex_bubble


# --- 6. 【大文字・大ボタン仕様】視認性抜群のカスタム選択肢メニュー ---
def create_大文字選択肢_ui(reply_text, quick_replies):
    buttons_contents = []
    for label in quick_replies:
        buttons_contents.append({
            "type": "button",
            "action": {
                "type": "message",
                "label": label[:15],
                "text": label
            },
            "style": "secondary",
            "color": "#f0f0f0",
            "margin": "sm"
        })
        
    flex_bubble = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": reply_text,
                    "wrap": True,
                    "size": "md",
                    "color": "#111111",
                    "weight": "bold"
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "xs",
                    "contents": buttons_contents
                }
            ]
        }
    }
    return flex_bubble


# --- 7. 改良型対話エンジン：セーフティ超強化型 ---
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
        # 🗄️ 過去の記憶のロード ＆ 話題の急な方向転換の自動判定
        session_ref = db.collection('User_Sessions').document(user_id)
        session_doc = session_ref.get()
        
        is_new_topic = False
        if session_doc.exists:
            current_state = session_doc.to_dict()
            past_pref = current_state.get("prefecture", "無し")
            if past_pref != "無し" and past_pref != "特定不能":
                past_pref_short = past_pref.replace("県", "").replace("府", "").replace("都", "").replace("道", "")
                if past_pref_short not in user_message and any(p in user_message for p in ["長野", "山梨", "静岡", "山形", "福島", "富士山"]):
                    is_new_topic = True
        else:
            is_new_topic = True

        if is_new_topic:
            current_state = {"month": default_month, "period": default_period, "prefecture": "無し", "subject": "無し", "turn_count": 1}
        else:
            current_state["turn_count"] = current_state.get("turn_count", 0) + 1

        status = "ASK"
        updated_state = current_state
        reply_text = ""
        quick_replies = []

        # ─── 🤖 【防御復活】AIによるスマート文脈解釈 ───
        ai_success = False
        if ai_client:
            try:
                system_prompt = f"""
                あなたは雑誌『風景写真』の格調高いAIコンシェルジュです。
                【現在の会話ステート】
                - 月: {current_state.get('month')}
                - 旬: {current_state.get('period')}
                - 都道府県: {current_state.get('prefecture')}
                - 被写体テーマ: {current_state.get('subject')}
                - 今回の会話ターン数: {current_state.get('turn_count')} 回目 (最大3回)

                【ルール】
                1. 返信文は必ず【100文字以内】でスマートに逆質問すること。
                2. 3回目のやり取り、または条件が揃った場合は必ず status を "COMPLETE" にすること。
                3. 1〜2回目は status を "ASK" にし、見やすい大きな選択肢ボタンのテキスト（最大4択）を quick_replies に入れること。
                """

                intent_response = ai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                    timeout=4.0
                )
                
                ai_res = json.loads(intent_response.choices[0].message.content.strip())
                status = ai_res.get("status", "ASK")
                updated_state = ai_res.get("updated_state", current_state)
                updated_state["turn_count"] = current_state["turn_count"]
                reply_text = ai_res.get("reply_text", "")
                quick_replies = ai_res.get("quick_replies", [])
                ai_success = True
            except Exception as ai_err:
                print(f"⚠️ OpenAI一時エラーガード（自力パースでセッションを継続します）: {ai_err}")

        # ─── 🛡️ 自力救済ルート: AIがエラーでコケても100%自力で地名を拾ってボタンを返す ───
        if not ai_success:
            for p in ["長野", "山梨", "静岡", "山形", "福島"]:
                if p in user_message: updated_state["prefecture"] = p + "県"
            for s in ["滝", "新緑", "茶畑", "新幹線", "花", "富士山"]:
                if s in user_message: updated_state["subject"] = s

            pref = updated_state.get("prefecture", "無し")
            subj = updated_state.get("subject", "無し")

            if pref == "長野県" and subj == "無し":
                status = "ASK"
                reply_text = "明日（5月下旬）の長野県ですね。広いエリアですので、アクセスとテーマから絞り込みましょう。"
                quick_replies = ["🌱 北信 × ブナ新緑", "🌊 東信 × 清流と滝", "🌸 南信 × 残雪と花"]
            elif (pref in ["山梨県", "静岡県"] or "富士山" in user_message) and subj == "無し":
                status = "ASK"
                reply_text = "明日の富士山周辺ですね。ルートによって狙える表情が異なります。ご希望のテーマはどちらですか？"
                quick_replies = ["🌊 中央道：山梨 × 滝", "🌱 東名：静岡 × 茶畑", "🚄 東名 × 新幹線"]
            elif pref != "無し" or subj != "無し" or "確定" in user_message or current_state["turn_count"] >= 2:
                status = "COMPLETE"
                reply_text = "かしこまりました。それでは条件に合う名作の書棚を開きます。"
            else:
                status = "ASK"
                reply_text = "明日（5月下旬）のおすすめ撮影地ですね。車での移動を想定し、今もっとも輝く被写体を選出しました。"
                quick_replies = ["🌊 清流・滝と新緑", "🗻 富士山周辺スポット", "🌱 茶畑と新緑の丘"]

        if current_state["turn_count"] >= 3:
            status = "COMPLETE"

        session_ref.set(updated_state)

        # ─── 🔁 1〜2回目：大文字カスタムボタンメニューを最速送信 ───
        if status == "ASK":
            if not reply_text: reply_text = "今の時期に最適な撮影テーマをご案内します。気になる項目を選択してください。"
            if not quick_replies: quick_replies = ["次の候補を見る"]
            menu_json = create_大文字選択肢_ui(reply_text, quick_replies)
            line_bot_api.reply_message(event['replyToken'], FlexSendMessage(alt_text="コンシェルジュからのご提案", contents=menu_json))
            return

        # ─── 🎯 3回目（確定時）：まとめとして本物の入賞作品画像つき極上カードを出す ───
        if status == "COMPLETE":
            session_ref.delete()

            target_month = updated_state.get("month", default_month)
            target_period = updated_state.get("period", default_period)
            target_pref = updated_state.get("prefecture", "無し")
            target_subject = updated_state.get("subject", "無し")

            # 曖昧なクイックテキスト選択を検索用に標準化
            if "北信" in user_message or "新緑" in user_message: target_subject = "新緑"
            if "東信" in user_message or "滝" in user_message: target_subject = "滝"
            if "静岡" in user_message or "茶畑" in user_message: target_pref = "静岡県"
            if "山梨" in user_message: target_pref = "山梨県"

            photos_ref = db.collection('Master_Photos')
            query = photos_ref.where('Month', '==', target_month).where('Period', '==', target_period)
            if target_pref != "無し" and target_pref != "特定不能":
                query = query.where('Prefecture', '==', target_pref)
                
            docs = query.stream()
            matched_photos = [doc.to_dict() for doc in docs if doc.to_dict()]
            
            if target_subject != "無し" and matched_photos:
                filtered = [p for p in matched_photos if (target_subject in str(p.values()))]
                if filtered: matched_photos = filtered
            
            if not matched_photos:
                fallback_docs = photos_ref.limit(10).stream()
                matched_photos = [doc.to_dict() for doc in fallback_docs if doc.to_dict()]

            target_data = random.choice(matched_photos)

            # フィールド名ズレ自動吸収マッピング
            flat_data = {str(k).lower(): v for k, v in target_data.items() if v}
            
            # ─── 🔗 閲覧用画像URLの動的生成 ───
            published = flat_data.get('published') or target_data.get('Published')
            pic_file_name = flat_data.get('picfilename') or flat_data.get('pic_file_name') or target_data.get('PicFileName')
            
            if published and pic_file_name:
                pub_str = str(published).strip()
                parent_dir = pub_str[:4]
                child_dir = pub_str
                file_name = str(pic_file_name).strip()
                TARGET_IMAGE_URL = f"{IMAGE_BASE_VIEW.rstrip('/')}/{parent_dir}/{child_dir}/{file_name}"
            else:
                TARGET_IMAGE_URL = "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=1000&q=80"

            title = flat_data.get('title') or flat_data.get('subject') or target_data.get('Title', '名作風景')
            location = flat_data.get('location') or flat_data.get('area') or flat_data.get('place') or target_data.get('Location', '厳選撮影地')
            author = flat_data.get('author') or flat_data.get('winner') or target_data.get('Author', '写真家')
            camera = flat_data.get('camera_body') or flat_data.get('camera') or target_data.get('Camera_Body', '一眼レフ')
            lens = flat_data.get('lens') or target_data.get('Lens', '標準レンズ')
            
            if flat_data.get('exposure'):
                settings = flat_data.get('exposure')
            else:
                settings = f"F{flat_data.get('aperture', '-')} / ISO {flat_data.get('iso', '-')} / {flat_data.get('focal_length', '-')}mm"
                
            weather = flat_data.get('weather') or target_data.get('Weather', '晴れ')
            guide = flat_data.get('guide_page') or flat_data.get('context_advice') or 'ルートナビ情報は本棚に保管されています。'
            judge_comment = flat_data.get('judge_comment_summary') or flat_data.get('logic_advice') or '構図バランスが実に見事な名作です。'

            bubble_json = create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment)
            
            closing_text = "ご要望を反映し、今回の撮影計画に最適な名作の書棚をまとめました。どうぞご高覧ください。"
            line_bot_api.reply_message(
                event['replyToken'],
                [
                    TextSendMessage(text=closing_text),
                    FlexSendMessage(alt_text="撮影地コンシェルジュレポート", contents=bubble_json)
                ]
            )

    except Exception as e:
        # 万が一のエラー時も絶対に隠蔽せず、生ログをLINE画面に完全に暴露するデバッグ仕様
        raw_error_trace = traceback.format_exc()
        print(f"🔥 実行時エラー詳細:\n{raw_error_trace}")
        try:
            line_bot_api.reply_message(event['replyToken'], TextSendMessage(text=f"❌ システム内部エラー検知:\n{raw_error_trace}"))
        except:
            pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
