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


# --- 5. メインロジック（インテリジェント提案エンジン） ---
def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    
    if db is None:
        return

    try:
        # 今朝のリアルタイムコンテキスト（5月 ➔ 春・初夏の新緑シーズン）
        current_season = "春"

        # 【あなたの発明：『富士山』に対する、時期連動型の能動的レコメンド（提案）】
        if user_message == "富士山":
            reply_text = (
                f"富士山ですね！5月下旬の今頃でしたら、新緑に美しく映える『滝と富士山』を狙ってみるのはいかがでしょう？\n\n"
                "本日の撮影プランに合わせて、以下の特選レコメンド、または地域から選択してください。"
            )
            
            # ただの質問ではなく、1番目に「滝と富士山」のプロアクティブな提案ボタンを配置！
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
        match_reason = "コンシェルジュの提案条件に合致する撮影データを特定しました。"

        # タップされた複数キーワード（例：['富士山', '滝', '春']）に分解
        keywords = user_message.split()

        # 抽象コンテキスト（東京在住、明日など）のフォールバック
        user_pref = None
        if any(k in user_message for k in ["東京", "関東", "在住"]):
            user_pref = ["東京都", "神奈川県", "千葉県", "埼玉県", "栃木県", "群馬県", "茨城県", "静岡県", "山梨県"]

        # 15,000件の安全走査
        docs = db.collection('Master_Photos').stream()
        for doc in docs:
            full_data = doc.to_dict()
            if not full_data: continue
            
            db_loc = str(full_data.get('Location', ''))
            db_title = str(full_data.get('Title', ''))
            db_pref = full_data.get('Prefecture', '')
            db_season = full_data.get('Season', '')

            # 1. 提案UIタップ時（3軸ANDクロス検索）
            if len(keywords) > 1:
                if all((k in db_loc or k in db_title or k in db_season or k in db_pref) for k in keywords):
                    target_data = full_data
                    match_reason = f"【時期: {current_season}】×【テーマ: {keywords[1]}】に完全合致。今朝一番おすすめしたいプロフェッショナル写真データです。"
                    break
            
            # 2. メイン仕様フォールバック（現在地 ＋ 時期のおすすめ）
            elif user_pref:
                if db_pref in user_pref and db_season == current_season:
                    target_data = full_data
                    match_reason = f"東京から好アクセスで、今まさにベストシーズン（{current_season}）を迎えている撮影地です。"
                    break
            
            # 3. 通常の単発キーワード中間一致
            else:
                if user_message in db_loc or user_message in db_title:
                    target_data = full_data
                    break

        # 【結果を極上の「添削指導UI」に流し込んで返却】
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
                TextSendMessage(text=f"「{user_message}」に関する具体的なデータが特定できませんでした。条件を少し変えてお試しください。")
            )
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)