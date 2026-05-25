import os
import json
import random
import traceback  # エラーの発生行を特定するためのパーツ
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi
from linebot.models import TextSendMessage, FlexSendMessage
import firebase_admin
from firebase_admin import credentials, firestore
from openai import OpenAI

app = Flask(__name__)

# --- 1. LINE API の初期化 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

# --- 2. OpenAI API の初期化 ---
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ai_client = OpenAI(api_key=OPENAI_API_KEY)

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


# --- 5. 【完全復元】元の添削指導UI（Flex Message） ---
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
          {"type": "text", "text": "🌸 AIコンシェルジュ厳選提案", "weight": "bold", "color": "#1DB954", "size": "sm"},
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


# --- 6. メイン処理：エラー発生時にすべてをLINEへ暴露するデバッグ版クエリ ---
def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    
    if db is None:
        return

    try:
        # 時期の基準を生成
        now = datetime.now()
        default_month = f"{now.month}月"
        if now.day <= 10:
            default_period = "初旬"
        elif now.day <= 20:
            default_period = "中旬"
        else:
            default_period = "下旬"

        # AIによる「揺らぎ切り出し」
        system_prompt = f"""
        ユーザーの文章から、データベース検索に必要な4つのキーワードを正確に切り出してください。
        本日の日付は大前提として【 {default_month} {default_period} 】です。
        必ず以下の4つの要素を、指定された形式の「カンマ区切り」のみで出力してください。
        月,旬,都道府県名,被写体
        """

        intent_response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.0
        )
        
        ai_output = intent_response.choices[0].message.content.strip()
        extracted_parts = [p.strip() for p in ai_output.split(",")]
        
        target_month = extracted_parts[0] if len(extracted_parts) > 0 else default_month
        target_period = extracted_parts[1] if len(extracted_parts) > 1 else default_period
        target_pref = extracted_parts[2] if len(extracted_parts) > 2 else "無し"
        target_subject = extracted_parts[3] if len(extracted_parts) > 3 else "無し"

        # 36分割マトリクス検索
        photos_ref = db.collection('Master_Photos')
        query = photos_ref.where('Month', '==', target_month).where('Period', '==', target_period)
        
        if target_pref != "無し":
            query = query.where('Prefecture', '==', target_pref)
            
        docs = query.stream()
        matched_photos = [doc.to_dict() for doc in docs if doc.to_dict()]
        
        if target_subject != "無し" and matched_photos:
            filtered = [p for p in matched_photos if (target_subject in str(p.get('Location', '')) or target_subject in str(p.get('Title', '')))]
            if filtered:
                matched_photos = filtered
        
        if not matched_photos:
            fallback_docs = photos_ref.limit(5).stream()
            matched_photos = [doc.to_dict() for doc in fallback_docs]

        target_data = random.choice(matched_photos)

        # 項目マッピング
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
        line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="撮影地コンシェルジュレポート", contents=bubble_json))
            
    except Exception as e:
        # ─── 🚨 【ブラックボックス解体】生のエラーログと行番号をLINEに直接叩きつける ───
        raw_error_trace = traceback.format_exc()
        print(f"🔥 サーバー側検出エラー:\n{raw_error_trace}")
        
        debug_message = (
            "⚠️ 【稼働エラーを検知しました】\n"
            "言い訳を排除し、現在の生のシステムエラー内容を出力します。この画面をそのまま教えてください：\n\n"
            f"{raw_error_trace}"
        )
        line_bot_api.reply_message(reply_token, TextSendMessage(text=debug_message))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
