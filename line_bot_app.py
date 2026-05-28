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
if not LINE_CHANNEL_ACCESS_TOKEN:
    print("WARNING: LINE_CHANNEL_ACCESS_TOKEN is empty!", flush=True)
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

# --- 2. OpenAI API の初期化 ---
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
if not OPENAI_API_KEY:
    print("WARNING: OPENAI_API_KEY is empty!", flush=True)
ai_client = OpenAI(api_key=OPENAI_API_KEY)

# --- 3. Firebase / Firestore の初期化関数 ---
db = None
def initialize_firebase():
    global db
    if db is not None:
        return db
    try:
        firebase_creds_json = os.environ.get('FIREBASE_CREDENTIALS')
        print(f"DEBUG: FIREBASE_CREDENTIALS length = {len(firebase_creds_json) if firebase_creds_json else 0}", flush=True)
        if firebase_creds_json:
            creds_dict = json.loads(firebase_creds_json)
            cred = credentials.Certificate(creds_dict)
            try:
                firebase_admin.initialize_app(cred)
            except ValueError:
                # すでに初期化済みの場合は既存のアプリを使用
                pass
            db = firestore.client()
            print("SUCCESS: Firestore initialized successfully.", flush=True)
            return db
    except Exception as e:
        print(f"CRITICAL ERROR: Firestore initialization failed: {e}", flush=True)
    return None

# 初回起動時に接続を試行
initialize_firebase()

# --- 4. LINE Webhook 受信口 ---
@app.route("/callback", methods=['POST'])
def callback():
    print("WEBHOOK: Received request from LINE.", flush=True)
    try:
        request_json = request.get_json()
        events = request_json.get('events', [])
        print(f"WEBHOOK: Event count = {len(events)}", flush=True)
        for event in events:
            print(f"WEBHOOK: Event detail = {json.dumps(event)}", flush=True)
            if event.get('type') == 'message' and event['message'].get('type') == 'text':
                handle_line_message(event)
    except Exception as e:
        print(f"ERROR: Exception in callback execution: {e}", flush=True)
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
    
    # グローバルDBが外れていたら再初期化
    current_db = initialize_firebase()
    target_data = None

    # ─── ステップ1: 司書脳（LLM）によるキーワード抽出 ───
    search_keywords = []
    try:
        print("ENGINE: Requesting gpt-4o-mini for keywords...", flush=True)
        intent_response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "ユーザーの文章から、日本の『都道府県名』、または『被写体や季節のキーワード（例：桜、新緑、富士山など）』を2個以内の単語で抽出して、カンマ区切りで出力してください。該当がない場合は「無」とだけ出力してください。"},
                {"role": "user", "content": user_message}
            ],
            temperature=0.0
        )
        keyword_output = intent_response.choices[0].message.content
        print(f"ENGINE: Extracted raw keywords = '{keyword_output}'", flush=True)
        search_keywords = [k.strip() for k in keyword_output.split(",") if k.strip() != "無"]
    except Exception as e:
        print(f"ENGINE ERROR: OpenAI keyword extraction failed: {e}", flush=True)

    # ─── ステップ2: 14,737件のクレンジング済みデータベース探索 ───
    if current_db is not None:
        try:
            matched_photos = []
            # 揺らぎのある複数のコレクション名を全スキャンして救う
            possible_collections = ['Master_Photos', 'photo_master', 'photo master', 'photos']
            
            for col_name in possible_collections:
                print(f"DATABASE: Querying collection '{col_name}'...", flush=True)
                photos_ref = current_db.collection(col_name)
                
                if search_keywords:
                    main_keyword = search_keywords[0]
                    print(f"DATABASE: Searching for Prefecture == '{main_keyword}'", flush=True)
                    docs = photos_ref.where('Prefecture', '==', main_keyword).limit(50).stream()
                    matched_photos.extend([doc.to_dict() for doc in docs])
                    
                    if not matched_photos:
                        print(f"DATABASE: Fallback scanning Location/Subject for '{main_keyword}'", flush=True)
                        fallback_docs = photos_ref.limit(150).stream()
                        for doc in fallback_docs:
                            data = doc.to_dict()
                            if main_keyword in str(data.get('Location', '')) or main_keyword in str(data.get('Subject', '')):
                                matched_photos.append(data)
                
                if matched_photos:
                    print(f"DATABASE: Hit found in '{col_name}'. Count = {len(matched_photos)}", flush=True)
                    break

            # 完全に空振った場合は、どこでもいいから先頭からランダムに取得
            if not matched_photos:
                print("DATABASE: No match. Fetching random documents for fallback...", flush=True)
                for col_name in possible_collections:
                    random_docs = current_db.collection(col_name).limit(10).stream()
                    matched_photos = [doc.to_dict() for doc in random_docs]
                    if matched_photos:
                        break

            if matched_photos:
                target_data = random.choice(matched_photos)
                print(f"DATABASE SUCCESS: Selected document Title = '{target_data.get('Title')}'", flush=True)
        except Exception as firestore_err:
            print(f"DATABASE ERROR: Firestore logic broke down: {firestore_err}", flush=True)

    # ─── ステップ3: 100%沈黙を回避する、知性バックアップのセーフティネット ───
    if not target_data:
        print("SAFETY WARNING: Database is unreachable or empty. Generating high-fidelity expert data dynamically...", flush=True)
        try:
            ai_backup = ai_client.chat.completions.create(
                model="gpt-4o",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": """
                    あなたは雑誌『風景写真』35年の歴史を全て脳内に宿したマスターコンシェルジュであり、プロの風景写真家です。
                    ユーザーの問いかけ（季節、天候、撮影の悩み、要望など）に100%合致する、実在する最高峰の日本の撮影地情報と名作のデータを、以下のJSONフォーマットで完全に出力してください。
                    
                    {
                        "Title": "作品のタイトル",
                        "Author": "写真家の氏名",
                        "Location": "具体的な撮影場所（例: 長野県 涸沢カール）",
                        "Subject": "被写体要素（例: 朝焼け, 紅葉）",
                        "Camera_Body": "使用カメラボディ",
                        "Lens": "使用レンズ",
                        "Aperture": "絞り値",
                        "ISO": "ISO感度",
                        "Focal_Length": "焦点距離",
                        "Weather": "天候",
                        "Judge_Comment_Summary": "この撮影地における光の読み方、構図の決定打、ベストな時間帯や季節のプロとしての詳細な解説（200文字程度）",
                        "Logic_Advice": "アマチュアがここで陥りがちな失敗と、それを一撃で解決するための具体的な添削指導・アドバイス（200文字程度）"
                    }
                    """},
                    {"role": "user", "content": f"ユーザーの問いかけ: 「{user_message}」"}
                ],
                temperature=0.4
            )
            target_data = json.loads(ai_backup.choices[0].message.content)
        except Exception as ai_err:
            print(f"CRITICAL AI ERROR: Backup generation failed: {ai_err}", flush=True)
            # 最終防衛用の固定値
            target_data = {
                "Title": "黎明の山嶺", "Author": "風景写真家ライブラリー", "Location": "長野県 穂高連峰",
                "Camera_Body": "プロ仕様フルサイズ機", "Lens": "標準大口径ズームレンズ", "Aperture": "11", "ISO": "100", "Focal_Length": "35", "Weather": "快晴（朝霧）",
                "Judge_Comment_Summary": "モルゲンロートに染まる岩肌を捉えるには、日の出30分前からの精密な露出固定が必須です。", 
                "Logic_Advice": "【添削指導】空の比率を抑え、手前のディテールを引き締めることで、画面全体の密度と山岳の圧倒的な立体感がより強調されます。"
            }

    # ─── ステップ4: 案内文（司書の言葉）の生成 ───
    try:
        print("ENGINE: Generating concierge message with gpt-4o...", flush=True)
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

    # ─── ステップ5: LINEへの同時返信の執行 ───
    try:
        print("LINE_API: Formulating message package...", flush=True)
        title = target_data.get('Title', '無題')
        location = target_data.get('Location', '不明な撮影地')
        author = target_data.get('Author', '不明')
        camera = target_data.get('Camera_Body', '情報なし')
        lens = target_data.get('Lens', '情報なし')
        
        # 絞り値やISOの数値に、前回のインポートで直したクレンジングデータがそのまま綺麗に乗る設計
        settings = f"F{target_data.get('Aperture', '-')} / ISO {target_data.get('ISO', '-')} / {target_data.get('Focal_Length', '-')}mm"
        weather = target_data.get('Weather', '不明')
        
        # あなたのマスターデータに完全に準拠したマッピング
        guide = target_data.get('Judge_Comment_Summary', target_data.get('guide', 'ナビ情報は現在準備中です。'))
        judge_comment = target_data.get('Logic_Advice', target_data.get('judge_comment', 'アドバイスは現在準備中です。'))
        
        bubble_json = create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment)
        
        print("LINE_API: Sending payload via reply_message...", flush=True)
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
