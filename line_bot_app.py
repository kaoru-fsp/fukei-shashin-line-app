import os
import json
import random
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


# --- 5. 本物のデータを美しく見せる Flex Message UI ---
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
          {"type": "text", "text": "🏛️ 風景写真ライブラリー 厳選案内", "weight": "bold", "color": "#111111", "size": "sm"},
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
                  {"type": "text", "text": "名作", "color": "#aaaaaa", "size": "sm", "flex": 2},
                  {"type": "text", "text": f"「{title}」 ({author} 様 著)", "wrap": True, "color": "#666666", "size": "sm", "flex": 5}
                ]
              },
              {
                "type": "box",
                "layout": "baseline",
                "spacing": "sm",
                "contents": [
                  {"type": "text", "text": "機材", "color": "#aaaaaa", "size": "sm", "flex": 2},
                  {"type": "text", "text": f"{camera}\n{lens}", "wrap": True, "color": "#666666", "size": "sm", "flex": 5}
                ]
              },
              {
                "type": "box",
                "layout": "baseline",
                "spacing": "sm",
                "contents": [
                  {"type": "text", "text": "設定", "color": "#aaaaaa", "size": "sm", "flex": 2},
                  {"type": "text", "text": f"{settings} / 天候: {weather}", "wrap": True, "color": "#666666", "size": "sm", "flex": 5}
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
              {"type": "text", "text": "📖 【この名作のコンテキスト（背景）】", "weight": "bold", "size": "md", "color": "#111111"},
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
              {"type": "text", "text": "💬 【プロのロジック・指導アドバイス】", "weight": "bold", "size": "md", "color": "#e67e22"},
              {"type": "text", "text": judge_comment, "wrap": True, "size": "sm", "color": "#333333", "margin": "sm"}
            ]
          }
        ]
      }
    }
    return flex_bubble


# --- 6. メイン処理：本物のマスター項目名にマッピング ---
def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    
    if db is None:
        return

    try:
        # ─── 司書脳（LLM）ステップ1: 検索用の「正式な都道府県名」を抽出 ───
        intent_response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "ユーザーの文章から、関係する日本の『都道府県名』を正式名称（例：長野県、山梨県、千葉県）で1つだけ抽出してください。都道府県名が含まれない、または特定できない場合は「無し」とだけ出力してください。"},
                {"role": "user", "content": user_message}
            ],
            temperature=0.0
        )
        pref_keyword = intent_response.choices[0].message.content.strip()
        
        photos_ref = db.collection('Master_Photos')
        matched_photos = []
        
        # ─── ステップ2: 実際のフィールド名「Area」から前方一致で確実に引き抜く ───
        if pref_keyword != "無し":
            # Firestoreの仕様に合わせた、高速かつ安全な前方一致クエリ（長野県から始まるデータをハント）
            query = photos_ref.where('Area', '>=', pref_keyword).where('Area', '<=', pref_keyword + '\uf8ff').limit(100)
            docs = query.stream()
            matched_photos = [doc.to_dict() for doc in docs]
        
        # 都道府県名がない、またはヒットしない場合は、「桜」や「富士山」などのキーワードで先頭1000件から部分一致検索
        if not matched_photos:
            fallback_docs = photos_ref.limit(1000).stream()
            for doc in fallback_docs:
                data = doc.to_dict()
                db_area = str(data.get('Area', ''))
                db_subject = str(data.get('Subject', ''))
                if user_message in db_area or user_message in db_subject:
                    matched_photos.append(data)
                    if len(matched_photos) >= 50:
                        break
        
        # 完全に見つからない場合のセーフティ
        if not matched_photos:
            random_docs = photos_ref.limit(10).stream()
            matched_photos = [doc.to_dict() for doc in random_docs]

        # 確定した1件（本物のマスターデータ構造）
        target_data = random.choice(matched_photos)

        # ─── ステップ3: 100%本物のデータだけを使って、誠実な案内文を作る ───
        title = target_data.get('Title', '無題')
        area = target_data.get('Area', '不明な撮影地')
        place = target_data.get('Place', '')
        full_location = f"{area} {place}".strip() if (place and str(place) != 'nan') else area
        winner = target_data.get('Winner', '不明')
        
        system_prompt = """
        あなたは雑誌『風景写真』のライブラリー司書です。
        与えられた【ライブラリーのデータ】の事実のみを基にして、丁寧な口調で案内を作ってください。
        データが「不明」となっているものは、嘘をついて捏造せず、正直に情報がない旨を伝えてください。
        """
        
        user_prompt = f"""
        【ライブラリーのデータ】
        ・作品名: 「{title}」
        ・撮影地: {full_location}
        ・作者: {winner} 様
        ・被写体要素: {target_data.get('Subject', '')}
        
        ユーザーの問いかけ: 「{user_message}」
        
        上記の「作品名」「撮影地」「作者名」を必ず文章の中に明記して、150文字程度で案内文を作成してください。最後は「こちらの名作の書棚を開きましたので、どうぞご高覧ください。」と結んでください。
        """
        
        response = ai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2
        )
        司書のメッセージ = response.choices[0].message.content

        # ─── ステップ4: カードUIへ本物の項目（Camera, Lens, Exposureなど）をマッピング ───
        camera = target_data.get('Camera', '情報なし')
        lens = target_data.get('Lens', '情報なし')
        settings = target_data.get('Exposure', '情報なし')  # CSVの「f16 1/250秒」などの文字列がそのまま入ります
        weather = target_data.get('Weather', '不明')
        
        # アドバイス項目のマッピング
        guide = target_data.get('Context_Advice', 'バックエンド・アクセスナビ情報は現在準備中です。')
        if not guide or str(guide) == 'nan': guide = 'バックエンド・アクセスナビ情報は現在準備中です。'
        
        judge_comment = target_data.get('Logic_Advice', 'プロによる作画ロジック・添削指導データは現在準備中です。')
        if not judge_comment or str(judge_comment) == 'nan': judge_comment = 'プロによる作画ロジック・添削指導データは現在準備中です。'
        
        bubble_json = create_添削_ui(full_location, title, winner, camera, lens, settings, weather, guide, judge_comment)
        
        line_bot_api.reply_message(
            reply_token,
            [
                TextSendMessage(text=司書のメッセージ),
                FlexSendMessage(alt_text="風景写真ライブラリー案内レポート", contents=bubble_json)
            ]
        )
            
    except Exception as e:
        print(f"Concierge System Error: {e}")
        line_bot_api.reply_message(reply_token, TextSendMessage(text="申し訳ございません。書棚の検索中に不手際がございました。"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
