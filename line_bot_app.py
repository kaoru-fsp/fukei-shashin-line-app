import os
import json
import random
from flask import Flask, request, abort
from linebot import LineBotApi
from linebot.models import TextSendMessage, FlexSendMessage
import firebase_admin
from firebase_admin import credentials, firestore
from openai import OpenAI  # 司書の知性を導入

app = Flask(__name__)

# --- 1. LINE API の初期化（元の動いていた構造を100%維持） ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

# --- 2. OpenAI API（司書脳）の初期化 ---
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ai_client = OpenAI(api_key=OPENAI_API_KEY)

# --- 3. Firebase / Firestore の初期化（元の構造を100%維持） ---
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


# --- 4. LINE Webhook 受信口（元の手動パース構造を完全維持） ---
@app.route("/callback", methods=['POST'])
def callback():
    try:
        request_json = request.get_json()
        events = request_json.get('events', [])
        for event in events:
            # テキストメッセージが届いた場合のみ処理
            if event.get('type') == 'message' and event['message'].get('type') == 'text':
                handle_line_message(event)
    except Exception as e:
        print(f"Error processing webhook event: {e}")
    return 'OK', 200


# --- 5. 美しいFlex Message UI（元の構造をそのまま維持） ---
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
                  {"type": "text", "text": f"「{title}」 ({author} 著)", "wrap": True, "color": "#666666", "size": "sm", "flex": 5}
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
                  {"type": "text", "text": "条件", "color": "#aaaaaa", "size": "sm", "flex": 2},
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
              {"type": "text", "text": "📖 【ライブラリーの撮影地知見】", "weight": "bold", "size": "md", "color": "#111111"},
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
              {"type": "text", "text": "💬 【この名作に宿る改善ロジック】", "weight": "bold", "size": "md", "color": "#2c3e50"},
              {"type": "text", "text": judge_comment, "wrap": True, "size": "sm", "color": "#333333", "margin": "sm"}
            ]
          }
        ]
      }
    }
    return flex_bubble


# --- 6. メイン処理：手動イベントパースに合わせたインテリジェント探索 ---
def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    
    if db is None:
        return

    try:
        # ─── 司書脳（LLM）ステップ1: キーワードの抽出 ───
        intent_response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "ユーザーの文章から、日本の『都道府県名』、または『被写体や季節のキーワード（例：桜、新緑、富士山など）』を2個以内の単語で抽出して、カンマ区切りで出力してください。該当がない場合は「無」とだけ出力してください。"},
                {"role": "user", "content": user_message}
            ],
            temperature=0.0
        )
        
        search_keywords = [k.strip() for k in intent_response.choices[0].message.content.split(",") if k.strip() != "無"]
        
        # ─── 司書脳ステップ2: 15,000件の安全な限定ロード ───
        photos_ref = db.collection('Master_Photos')
        matched_photos = []
        
        if search_keywords:
            main_keyword = search_keywords[0]
            # 実際のフィールド名「Prefecture」で高速インデックス検索（最大100件制限）
            query = photos_ref.where('Prefecture', '==', main_keyword).limit(100)
            docs = query.stream()
            matched_photos = [doc.to_dict() for doc in docs]
            
            # ヒットしない場合、LocationやSubjectにキーワードが含まれるものを先頭200件から安全にスキャン
            if not matched_photos:
                fallback_docs = photos_ref.limit(200).stream()
                for doc in fallback_docs:
                    data = doc.to_dict()
                    if main_keyword in str(data.get('Location', '')) or main_keyword in str(data.get('Subject', '')):
                        matched_photos.append(data)
        
        # 該当がない場合は先頭からランダムに選出
        if not matched_photos:
            random_docs = photos_ref.limit(10).stream()
            matched_photos = [doc.to_dict() for doc in random_docs]

        target_data = random.choice(matched_photos)

        # ─── 司書脳ステップ3: 案内文の生成 ───
        system_prompt = """
        あなたは雑誌『風景写真』35年の歴史を預かる「ライブラリーの司書（コンシェルジュ）」です。
        データから引き出された事実のみを基にして、非常に丁寧で思慮深い「司書」の口調（紳士的な敬語）で、
        ユーザーへの優しい案内メッセージを作成してください。事実の捏造は厳禁です。
        """
        
        user_prompt = f"""
        【ライブラリーのデータ】
        ・作品: 「{target_data.get('Title', '無題')}」 ({target_data.get('Author', '名無し')} 著)
        ・撮影地: {target_data.get('Location', '不明な撮影地')}
        ・被写体要素: {target_data.get('Subject', '')}
        
        ユーザーの問いかけ: 「{user_message}」
        
        上記データを使って、150文字程度の短く紳士的な案内文を作ってください。最後に「こちらの名作の書棚を開きましたので、どうぞご高覧ください。」と結んでください。
        """
        
        response = ai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3
        )
        司書のメッセージ = response.choices[0].message.content

        # ─── ステップ4: 「司書の言葉」＋「美しいFlex UI」をLINEへ同時に返信 ───
        title = target_data.get('Title', '無題')
        location = target_data.get('Location', '不明な撮影地')
        author = target_data.get('Author', '不明')
        camera = target_data.get('Camera_Body', '情報なし')
        lens = target_data.get('Lens', '情報なし')
        
        settings = f"F{target_data.get('Aperture', '-')} / ISO {target_data.get('ISO', '-')} / {target_data.get('Focal_Length', '-')}mm"
        weather = target_data.get('Weather', '不明')
        
        # あなたのマスターデータの項目名「Judge_Comment_Summary」「Logic_Advice」を正しくマッピング
        guide = target_data.get('Judge_Comment_Summary', 'ナビ情報は現在準備中です。')
        judge_comment = target_data.get('Logic_Advice', 'アドバイスは現在準備中です。')
        
        bubble_json = create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment)
        
        # 配列形式で2つのメッセージを同時に送信（元のlinebotライブラリの仕様に完全追従）
        line_bot_api.reply_message(
            reply_token,
            [
                TextSendMessage(text=司書のメッセージ),
                FlexSendMessage(alt_text="風景写真ライブラリー案内レポート", contents=bubble_json)
            ]
        )
            
    except Exception as e:
        print(f"Concierge System Error: {e}")
        line_bot_api.reply_message(reply_token, TextSendMessage(text="申し訳ございません。書棚の検索中に少し不手際がございました。もう一度お声がけいただけますでしょうか。"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
