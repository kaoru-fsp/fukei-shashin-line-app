import os
import json
import random
import sys
from flask import Flask, request, abort
from linebot import LineBotApi
from linebot.models import TextSendMessage, FlexSendMessage
import firebase_admin
from firebase_admin import credentials, firestore
from openai import OpenAI

app = Flask(__name__)

print("STARTUP: Initializing line_bot_app...", flush=True)

# --- 1. LINE API の初期化 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

# --- 2. OpenAI API の初期化 ---
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ai_client = OpenAI(api_key=OPENAI_API_KEY)

# --- 安全な文字列変換（LINEのエラー400を絶対に防ぐ防壁） ---
def safe_str(val, default="情報なし"):
    if val is None:
        return default
    s = str(val).strip()
    if s == "" or s.lower() == "nan" or s.lower() == "none":
        return default
    return s

# --- 3. Firebase / Firestore の初期化 ---
db = None
def initialize_firebase():
    global db
    if db is not None:
        return db
    try:
        firebase_creds_json = os.environ.get('FIREBASE_CREDENTIALS')
        if firebase_creds_json:
            creds_dict = json.loads(firebase_creds_json)
            cred = credentials.Certificate(creds_dict)
            try:
                firebase_admin.initialize_app(cred)
            except ValueError:
                pass
            db = firestore.client()
            print("SUCCESS: Firestore initialized.", flush=True)
            return db
    except Exception as e:
        print(f"CRITICAL ERROR: Firebase init failed: {e}", flush=True)
    return None

initialize_firebase()

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
        print(f"ERROR: Callback exception: {e}", flush=True)
    return 'OK', 200

# --- 5. 美しいFlex Message UI ---
def create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment):
    flex_bubble = {
      "type": "bubble",
      "hero": {
        "type": "image",
        "url": "https://upload.wikimedia.org/wikipedia/commons/d/d4/One_White_Square.png",
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

# --- 6. メイン処理：インテリジェント探索ハイブリッドエンジン ---
def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    print(f"ENGINE: Processing message = '{user_message}'", flush=True)
    
    current_db = initialize_firebase()
    target_data = None

    # ─── ステップ1: 司書脳（LLM）によるキーワード抽出 ───
    search_keywords = []
    try:
        intent_response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "ユーザーの文章から、日本の『都道府県名』、または『被写体や季節のキーワード（例：桜、新緑、富士山など）』を2個以内の単語で抽出して、カンマ区切りで出力してください。該当がない場合は「無」とだけ出力してください。"},
                {"role": "user", "content": user_message}
            ],
            temperature=0.0
        )
        keyword_output = intent_response.choices[0].message.content
        search_keywords = [k.strip() for k in keyword_output.split(",") if k.strip() != "無"]
    except Exception as e:
        print(f"ENGINE ERROR: OpenAI keyword extraction failed: {e}", flush=True)

    # ─── ステップ2: 14,737件のデータベース探索 ───
    if current_db is not None:
        try:
            matched_photos = []
            possible_collections = ['Master_Photos', 'photo_master', 'photo master', 'photos']
            
            for col_name in possible_collections:
                photos_ref = current_db.collection(col_name)
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
                for col_name in possible_collections:
                    random_docs = current_db.collection(col_name).limit(10).stream()
                    matched_photos = [doc.to_dict() for doc in random_docs]
                    if matched_photos:
                        break

            if matched_photos:
                target_data = random.choice(matched_photos)
        except Exception as firestore_err:
            print(f"DATABASE ERROR: Firestore logic failed: {firestore_err}", flush=True)

    # ─── ステップ3: セーフティネット（本番データ構造の完全エミュレート） ───
    if not target_data:
        try:
            ai_backup = ai_client.chat.completions.create(
                model="gpt-4o",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": """
                    ユーザーの問いかけに合致する、実在する最高峰の日本の撮影地情報と名作データを、指定のJSONフォーマットで出力してください。空欄は厳禁です。
                    {
                        "Title": "作品のタイトル", "Author": "写真家の氏名", "Location": "具体的な撮影場所", "Subject": "被写体要素",
                        "Camera_Body": "使用カメラ", "Lens": "使用レンズ", "Aperture": "絞り値", "ISO": "ISO", "Focal_Length": "焦点距離", "Weather": "天候",
                        "Judge_Comment_Summary": "この撮影地における光の読み方やプロの解説（200文字程度）",
                        "Logic_Advice": "アマチュアへの具体的な添削指導・アドバイス（200文字程度）"
                    }
                    """},
                    {"role": "user", "content": f"ユーザーの問いかけ: 「{user_message}」"}
                ],
                temperature=0.4
            )
            target_data = json.loads(ai_backup.choices[0].message.content)
        except Exception as ai_err:
            target_data = {}

    # ─── ステップ4: データの安全洗浄（safe_strによるLINE拒否ガード） ───
    title = safe_str(target_data.get('Title'), "無題")
    location = safe_str(target_data.get('Location'), "不明な撮影地")
    author = safe_str(target_data.get('Author'), "写真家")
    camera = safe_str(target_data.get('Camera_Body'), "情報なし")
    lens = safe_str(target_data.get('Lens'), "情報なし")
    
    aperture = safe_str(target_data.get('Aperture'), "-")
    iso = safe_str(target_data.get('ISO'), "-")
    focal = safe_str(target_data.get('Focal_Length'), "-")
    settings = f"F{aperture} / ISO {iso} / {focal}mm"
    weather = safe_str(target_data.get('Weather'), "不明")
    
    guide = safe_str(target_data.get('Judge_Comment_Summary', target_data.get('guide')), "ナビ情報は現在準備中です。")
    judge_comment = safe_str(target_data.get('Logic_Advice', target_data.get('judge_comment')), "アドバイスは現在準備中です。")

    # ─── ステップ5: 案内文の生成 ───
    try:
        response = ai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "あなたは雑誌『風景写真』35年の歴史を預かるライブラリーの司書です。丁寧な紳士の敬語で、ユーザーへの優しい案内メッセージを作成してください。"},
                {"role": "user", "content": f"【データ】\n作品:「{title}」（{author}著）\n撮影地:{location}\nユーザーの問いかけ:「{user_message}」\n150文字程度で案内文を作ってください。最後に「こちらの名作の書棚を開きましたので、どうぞご高覧ください。」と結んでください。"}
            ],
            temperature=0.3
        )
        司書のメッセージ = safe_str(response.choices[0].message.content, "ご要望にふさわしい、風景写真ライブラリーの名作をご案内いたします。どうぞご高覧ください。")
    except Exception:
        司書のメッセージ = f"お待たせいたしました。ご要望に最もふさわしい名作をご案内いたします。こちらの名作の書棚を開きましたので、どうぞご高覧ください。"

    # ─── ステップ6: 返信の執行 ───
    try:
        bubble_json = create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment)
        line_bot_api.reply_message(
            reply_token,
            [
                TextSendMessage(text=司書のメッセージ),
                FlexSendMessage(alt_text="風景写真ライブラリー案内レポート", contents=bubble_json)
            ]
        )
        print("SUCCESS: LINE reply completed perfectly.", flush=True)
    except Exception as reply_err:
        print(f"LINE_API CRITICAL ERROR: reply_message crashed: {reply_err}", flush=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
