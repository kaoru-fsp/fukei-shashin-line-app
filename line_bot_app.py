import os
import json
import random
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

# --- 2. OpenAI API の初期化（揺らぎを構造化データに切り出すプロとして使用） ---
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


# --- 6. 真のロジック：AIによる「揺らぎキーワード切り出し」×「高精度マトリクス検索」 ---
def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    
    if db is None:
        return

    try:
        # システム側のリアルタイムな「本日」の基準を生成
        now = datetime.now()
        default_month = f"{now.month}月"
        if now.day <= 10:
            default_period = "初旬"
        elif now.day <= 20:
            default_period = "中旬"
        else:
            default_period = "下旬"

        # ─── 🤖 AI（OpenAI）による究極の「揺らぎ切り出し」ミッション ───
        system_prompt = f"""
        あなたはユーザーの曖昧な発話から、データベース検索に必要な4つのキーワードを正確に切り出す天才データアナリストです。
        本日の日付は【 {default_month} {default_period} 】です。これを大前提として以下のルールに従って解析してください。

        【出力フォーマット】
        必ず以下の4つの要素を、指定された形式の「カンマ区切り」のみで出力してください。余計な説明文は一切排除してください。
        月,旬,都道府県名,被写体

        【ルール】
        1. 月: ユーザーが月を指定していれば「○月」、無ければ本日の前提である「{default_month}」を出力。
        2. 旬: ユーザーが初/中/下旬を指定していれば「初旬」「中旬」「下旬」のいずれか、無ければ本日の前提である「{default_period}」を出力。
        3. 都道府県名: ユーザーの発話（例：長野、富士山の山梨側など）から、該当する正式な日本の都道府県名を1つ特定して出力。特定できなければ「無し」。
        4. 被写体: 撮影したいテーマ（例：滝、新緑、桜、新幹線など）を1単語で抽出。無ければ「無し」。

        出力例1（明日どこかおすすめ？の場合）: {default_month},{default_period},無し,無し
        出力例2（来週中央道で富士山の方に行くの場合）: {default_month},下旬,山梨県,富士山
        """

        intent_response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.0
        )
        
        # AIの解析結果を分解
        ai_output = intent_response.choices[0].message.content.strip()
        print(f"AI Extraction Result: {ai_output}") # ログで確認用
        extracted_parts = [p.strip() for p in ai_output.split(",")]
        
        # 安全に要素をマッピング（パース崩れ対策）
        target_month = extracted_parts[0] if len(extracted_parts) > 0 else default_month
        target_period = extracted_parts[1] if len(extracted_parts) > 1 else default_period
        target_pref = extracted_parts[2] if len(extracted_parts) > 2 else "無し"
        target_subject = extracted_parts[3] if len(extracted_parts) > 3 else "無し"

        # ─── 🎯 インデックスによる高精度な狙い撃ち検索 ───
        photos_ref = db.collection('Master_Photos')
        
        # 1年＝36分割マトリクスによる一次絞り込み（これで数百件に自動収束）
        query = photos_ref.where('Month', '==', target_month).where('Period', '==', target_period)
        
        # AIが「都道府県」を特定できていれば、さらにクエリを重ねて数十件レベルに完全ロック
        if target_pref != "無し":
            query = query.where('Prefecture', '==', target_pref)
            
        docs = query.stream()
        matched_photos = [doc.to_dict() for doc in docs if doc.to_dict()]
        
        # 被写体（Subject）のキーワード絞り込み（メモリ上での高速突合）
        if target_subject != "無し" and matched_photos:
            filtered = [p for p in matched_photos if (target_subject in str(p.get('Location', '')) or target_subject in str(p.get('Title', '')))]
            if filtered:
                matched_photos = filtered
        
        # 万が一、条件に合致する写真が1件もない場合のセーフティ（全体からランダム）
        if not matched_photos:
            fallback_docs = photos_ref.limit(5).stream()
            matched_photos = [doc.to_dict() for doc in fallback_docs]

        target_data = random.choice(matched_photos)

        # ─── 💎 元コードの「項目名」を100%そのまま使用してマッピング ───
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
        
        # 結果を最速で返却
        bubble_json = create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment)
        line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="撮影地コンシェルジュレポート", contents=bubble_json))
            
    except Exception as e:
        error_str = str(e)
        print(f"Query Error: {error_str}")
        
        # 複合インデックス未作成の場合、Firebaseコンソールの自動生成URLをLINEに直接吐き出す親切デバッグ仕様
        if "https://console.firebase.google.com" in error_str:
            url_start = error_str.find("https://console.firebase.google.com")
            index_url = error_str[url_start:].split()[0]
            msg = f"⚙️ Firestoreの複合インデックス設定が必要です。\n以下のURLを1回クリックして、インデックスを作成してください。数分で開通します：\n\n{index_url}"
        else:
            msg = f"❌ システムエラー詳細:\n{error_str}\n※OpenAIの残高（クレジット事前チャージ）が切れていないか、アカウント設定をご確認ください。"
            
        line_bot_api.reply_message(reply_token, TextSendMessage(text=msg))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
