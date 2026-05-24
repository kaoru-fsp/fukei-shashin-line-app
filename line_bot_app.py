import os
import json
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, FlexSendMessage
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

# --- 1. LINE API の初期化 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

# --- 2. Firebase / Firestore の初期化 ---
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


# --- 3. LINE Webhook 受信口 ---
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


# --- 4. 添削指導（レベルアップ相談室）UIを動的に組み立てる関数 ---
def create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment):
    """
    朝の仕様書に準拠し、審査員評（添削指導）を美しくカード型で見せるための
    LINE Flex Message (JSON構造) をPythonのディクショナリで定義。
    """
    flex_bubble = {
      "type": "bubble",
      "hero": {
        "type": "image",
        "url": "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=1000&q=80",
        "size": "full",
        "aspectRatio": "20:13",
        "aspectMode": "cover"
      },
      "body": {
        "type": "box",
        "layout": "vertical",
        "contents": [
          {
            "type": "text",
            "text": "🌸 AIコンシェルジュ厳選提案",
            "weight": "bold",
            "color": "#1DB954",
            "size": "sm"
          },
          {
            "type": "text",
            "text": location,
            "weight": "bold",
            "size": "xl",
            "margin": "md",
            "wrap": True
          },
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
              },
              {
                "type": "box",
                "layout": "baseline",
                "spacing": "sm",
                "contents": [
                  {"type": "text", "text": "当日天候", "color": "#aaaaaa", "size": "sm", "flex": 2},
                  {"type": "text", "text": weather, "wrap": True, "color": "#666666", "size": "sm", "flex": 5}
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
              {
                "type": "text",
                "text": "📖 【現地ナビ・アクセス】",
                "weight": "bold",
                "size": "md",
                "color": "#111111",
                "margin": "xs"
              },
              {
                "type": "text",
                "text": guide,
                "wrap": True,
                "size": "sm",
                "color": "#555555",
                "margin": "md"
              }
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
              {
                "type": "text",
                "text": "🎓 【レベルアップ相談室・添削指導】",
                "weight": "bold",
                "size": "md",
                "color": "#e67e22"
              },
              {
                "type": "text",
                "text": judge_comment,
                "wrap": True,
                "size": "sm",
                "color": "#333333",
                "margin": "sm"
              }
            ]
          }
        ]
      }
    }
    return flex_bubble


# --- 5. メインロジック（多次元クロス検索 ＆ UI流し込み） ---
def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    
    if db is None:
        return

    try:
        target_data = None
        match_reason = "条件にマッチするプロの撮影データを呼び出しました。"

        # コンテキスト抽出
        user_pref = None
        if any(k in user_message for k in ["東京", "関東", "在住"]):
            user_pref = ["東京都", "神奈川県", "千葉県", "埼玉県", "栃木県", "群馬県", "茨城県", "静岡県", "山梨県"]
        elif any(k in user_message for k in ["京都", "関西", "大阪"]):
            user_pref = ["京都府", "大阪府", "兵庫県", "奈良県", "滋賀県"]

        detect_weather = None
        for w in ["曇り", "くもり", "晴れ", "はれ", "雨", "あめ"]:
            if w in user_message:
                detect_weather = "曇り" if "くもり" in w else ("晴れ" if "はれ" in w else "雨")
                break

        current_season = "春"

        # 15,000件の安全スキャン
        docs = db.collection('Master_Photos').stream()
        for doc in docs:
            full_data = doc.to_dict()
            if not full_data: continue
            
            db_pref = full_data.get('Prefecture', '')
            db_weather = full_data.get('Weather', '')
            db_season = full_data.get('Season', '')
            db_loc = full_data.get('Location', '')
            db_title = full_data.get('Title', '')

            # 複合クロス検索の判定
            if user_pref and db_pref in user_pref and db_season == current_season:
                target_data = full_data
                break
            elif detect_weather and detect_weather in str(db_weather):
                target_data = full_data
                break
            elif user_message in str(db_loc) or user_message in str(db_title):
                target_data = full_data
                break

        # マッチした場合、Flex Messageを生成して返信
        if target_data:
            title = target_data.get('Title', '無題')
            location = target_data.get('Location', '不明な撮影地')
            author = target_data.get('Author', '不明')
            camera = target_data.get('Camera_Body', '情報なし')
            lens = target_data.get('Lens', '情報なし')
            
            aperture = target_data.get('Aperture', '-')
            iso = target_data.get('ISO', '-')
            focal = target_data.get('Focal_Length', '-')
            settings = f"F{aperture} / ISO {iso} / {focal}mm"
            
            weather = target_data.get('Weather', '不明')
            guide = target_data.get('Guide_Page', 'ナビ情報は現在準備中です。')
            judge_comment = target_data.get('Judge_Comment_Summary', '審査員アドバイスは現在準備中です。')
            
            # UIの組み立て
            bubble_json = create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment)
            
            # LINEへ送信（FlexSendMessage を使用）
            line_bot_api.reply_message(
                reply_token,
                FlexSendMessage(alt_text="撮影添削指導レポート", contents=bubble_json)
            )
        else:
            # 見つからなかった場合のフォールバック（ここは通常のテキストで安全に返す）
            from linebot.models import TextSendMessage
            line_bot_api.reply_message(
                reply_token, 
                TextSendMessage(text="ご提示いただいた条件に合うデータが現在見つかりませんでした。「富士山」や「京都」などのキーワードでお試しください。")
            )
            
    except Exception as e:
        print(f"Error in handle_line_message: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)