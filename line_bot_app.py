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

# --- 5. 美しいFlex Message UI ---
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

# --- 6. メイン処理：絶対沈黙しないコンシェルジュエンジン ---
def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    
    target_data = None

    # 1. 金庫（Firestore）からのデータ取得に挑戦
    if db is not None:
        try:
            intent_response = ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "ユーザーの文章から、日本の『都道府県名』、または『被写体や季節のキーワード（例：桜、新緑、富士山など）』を2個以内の単語で抽出して、カンマ区切りで出力してください。該当がない場合は「無」とだけ出力してください。"},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.0
            )
            search_keywords = [k.strip() for k in intent_response.choices[0].message.content.split(",") if k.strip() != "無"]
            
            # 複数の可能性のあるコレクション名を両方スキャンして救う
            matched_photos = []
            for col_name in ['photo_master', 'photo master', 'Master_Photos']:
                photos_ref = db.collection(col_name)
                if search_keywords:
                    main_keyword = search_keywords[0]
                    docs = photos_ref.where('Prefecture', '==', main_keyword).limit(50).stream()
                    matched_photos.extend([doc.to_dict() for doc in docs])
                    
                    if not matched_photos:
                        fallback_docs = photos_ref.limit(100).stream()
                        for doc in fallback_docs:
                            data = doc.to_dict()
                            if main_keyword in str(data.get('Location', '')) or main_keyword in str(data.get('Subject', '')):
                                matched_photos.append(data)
                if matched_photos:
                    break

            if not matched_photos:
                for col_name in ['photo_master', 'photo master', 'Master_Photos']:
                    random_docs = db.collection(col_name).limit(10).stream()
                    matched_photos = [doc.to_dict() for doc in random_docs]
                    if matched_photos:
                        break

            if matched_photos:
                target_data = random.choice(matched_photos)
        except Exception as firestore_err:
            print(f"Firestore fallback activated due to: {firestore_err}")

    # 2. 金庫が空、またはエラーだった場合はAI（gpt-4o）が「プロの風景写真家・司書」として最高品質のデータをその場で完全生成（フォールバック）
    if not target_data:
        try:
            print("Activating Ultimate AI Knowledge Fallback Mode...")
            ai_backup = ai_client.chat.completions.create(
                model="gpt-4o",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": """
                    あなたは雑誌『風景写真』35年の歴史を全て脳内に宿したマスターコンシェルジュであり、プロの風景写真家です。
                    ユーザーの問いかけ（季節、天候、撮影の悩み、要望など）に100%合致する、実在する最高峰の日本の撮影地情報と名作のデータを、以下のJSONフォーマットで完全にシミュレートして出力してください。
                    
                    {
                        "Title": "作品のタイトル（例: 黎明の霧）",
                        "Author": "写真家の氏名",
                        "Location": "具体的な撮影場所（例: 長野県 涸沢カール）",
                        "Subject": "被写体要素（例: 朝焼け, 紅葉, 残雪）",
                        "Camera_Body": "使用カメラボディ",
                        "Lens": "使用レンズ",
                        "Aperture": "絞り値（例: 11）",
                        "ISO": "ISO感度（例: 100）",
                        "Focal_Length": "焦点距離（例: 24）",
                        "Weather": "天候（例: 快晴（朝霧））",
                        "Judge_Comment_Summary": "この撮影地における光の読み方、構図の決定打、ベストな時間帯や季節のプロとしての詳細な解説（200文字程度）",
                        "Logic_Advice": "アマチュアがここで陥りがちな失敗（露出の過不足やブレ、構図の散漫さなど）と、それを一撃で解決するための具体的な添削指導・アドバイス（200文字程度）"
                    }
                    """},
                    {"role": "user", "content": f"ユーザーの問いかけ: 「{user_message}」"}
                ],
                temperature=0.5
            )
            target_data = json.loads(ai_backup.choices[0].message.content)
        except Exception as ai_err:
            print(f"AI backup error: {ai_err}")
            target_data = {
                "Title": "明日への光", "Author": "写真家ライブラリー", "Location": "日本国内の美しい風景",
                "Camera_Body": "プロ仕様機", "Lens": "標準ズームレンズ", "Aperture": "8", "ISO": "100", "Focal_Length": "50", "Weather": "晴れ",
                "Judge_Comment_Summary": "美しい瞬間を捉えるためのナビゲーションです。", "Logic_Advice": "構図をシンプルにまとめることが成功の鍵となります。"
            }

    # 3. 案内文（司書の言葉）の生成
    try:
        system_prompt = "あなたは雑誌『風景写真』35年の歴史を預かる「ライブラリーの司書」です。データに基づき、非常に丁寧で紳士的な敬語の口調で、ユーザーへの優しい案内メッセージを作成してください。"
        user_prompt = f"【データ】\n・作品: 「{target_data.get('Title', '無題')}」 ({target_data.get('Author', '名無し')} 著)\n・撮影地: {target_data.get('Location', '不明な撮影地')}\nユーザーの問いかけ: 「{user_message}」\n上記に基づき、150文字程度の短く紳士的な案内文を作ってください。最後に「こちらの名作の書棚を開きましたので、どうぞご高覧ください。」と結んでください。"
        
        response = ai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3
        )
        司書のメッセージ = response.choices[0].message.content
    except Exception:
        司書のメッセージ = f"お待たせいたしました。ご要望に最もふさわしい、風景写真ライブラリーの名作をご案内いたします。こちらの名作の書棚を開きましたので、どうぞご高覧ください。"

    # 4. 「司書の言葉」＋「美しいFlex UI」をLINEへ同時に返信
    try:
        title = target_data.get('Title', '無題')
        location = target_data.get('Location', '不明な撮影地')
        author = target_data.get('Author', '不明')
        camera = target_data.get('Camera_Body', '情報なし')
        lens = target_data.get('Lens', '情報なし')
        settings = f"F{target_data.get('Aperture', '-')} / ISO {target_data.get('ISO', '-')} / {target_data.get('Focal_Length', '-')}mm"
        weather = target_data.get('Weather', '不明')
        guide = target_data.get('Judge_Comment_Summary', 'ナビ情報は現在準備中です。')
        judge_comment = target_data.get('Logic_Advice', 'アドバイスは現在準備中です。')
        
        bubble_json = create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment)
        
        line_bot_api.reply_message(
            reply_token,
            [
                TextSendMessage(text=司書のメッセージ),
                FlexSendMessage(alt_text="風景写真ライブラリー案内レポート", contents=bubble_json)
            ]
        )
    except Exception as reply_err:
        print(f"LINE Reply Final Error: {reply_err}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
