import os
import json
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, 
    FlexSendMessage, QuickReply, QuickReplyButton, MessageAction
)
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


# --- 4. 添削指導（レベルアップ相談室）UI（Flex Message）の組み立て ---
def create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment):
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


# --- 5. メインロジック（キーワード切り出し ＆ 能動的レコメンド） ---
def handle_line_message(event):
    reply_token = event['replyToken']
    raw_message = event['message']['text'].strip()
    
    if db is None:
        return

    try:
        current_season = "春"
        
        # 【あなたの指摘：自由な文章からキーワードを切り出す処理】
        # スペース区切りの単語リストを作成しつつ、文章全体から重要な地名や被写体を検知
        is_fuji_requested = "富士" in raw_message
        is_kyoto_requested = "京都" in raw_message
        
        # 文章の中からデータベース突合用のコアキーワードを配列に切り出し
        search_keywords = []
        if is_fuji_requested: search_keywords.append("富士山")
        if is_kyoto_requested: search_keywords.append("京都府")
        
        # 追加の被写体や地域の切り出し
        for word in ["静岡", "山梨", "新幹線", "滝", "茶畑", "湖", "桜", "曇り", "雨", "晴れ"]:
            if word in raw_message:
                search_keywords.append(word)

        # もし何のキーワードも切り出せなかった場合は、入力文字をそのまま使用
        if not search_keywords:
            search_keywords = raw_message.split()

        # 【切り出し結果：『富士山』の意図が含まれていた場合の能動的レコメンド】
        # 「明日、富士山撮りに行きたいんだけど」という文章から「富士」を切り出してこの分岐に入れます
        if is_fuji_requested and len(search_keywords) == 1:
            reply_text = (
                f"富士山ですね！5月下旬の今頃でしたら、新緑に美しく映える『滝と富士山』を狙ってみるのはいかがでしょう？\n\n"
                "本日の撮影プランに合わせて、以下の特選レコメンド、または地域から選択してください。"
            )
            
            quick_reply_options = QuickReply(items=[
                QuickReplyButton(action=MessageAction(label="🌊 今が旬！滝 × 富士山（富士宮エリア）", text="富士山 滝 春")),
                QuickReplyButton(action=MessageAction(label="🚄 定番！新幹線 × 富士山（三島方面）", text="富士山 新幹線 春")),
                QuickReplyButton(action=MessageAction(label="🌱 静岡側 × 茶畑新緑（大淵笹場）", text="富士山 茶畑 春")),
                QuickReplyButton(action=MessageAction(label="🏞️ 山梨側 × 湖水逆さ富士（富士五湖）", text="富士山 湖 春"))
            ])
            
            line_bot_api.reply_message(
                reply_token,
                TextSendMessage(text=reply_text, quick_reply=quick_reply_options)
            )
            return

        target_data = None

        # 15,000件の安全走査
        docs = db.collection('Master_Photos').stream()
        for doc in docs:
            full_data = doc.to_dict()
            if not full_data: continue
            
            db_loc = str(full_data.get('Location', ''))
            db_title = str(full_data.get('Title', ''))
            db_pref = full_data.get('Prefecture', '')
            db_season = full_data.get('Season', '')

            # 切り出したキーワード群でAND多層検索
            if search_keywords:
                if all((k in db_loc or k in db_title or k in db_season or k in db_pref) for k in search_keywords):
                    target_data = full_data
                    break

        # 【結果を「添削指導UI（Flex Message）」で確実に返却】
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
            
            bubble_json = create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment)
            
            line_bot_api.reply_message(
                reply_token,
                FlexSendMessage(alt_text="撮影地コンシェルジュレポート", contents=bubble_json)
            )
        else:
            line_bot_api.reply_message(
                reply_token, 
                TextSendMessage(text=f"「{raw_message}」から条件を解析しましたが、合致する撮影地を特定できませんでした。別のキーワード（例：京都、富士山など）でお試しください。")
            )
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)