import os
import json
import random
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
import firebase_admin
from firebase_admin import credentials, firestore
from openai import OpenAI  # AI（司書）の知性を導入

app = Flask(__name__)

# --- 1. LINE API の初期化 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- 2. OpenAI API（司書脳）の初期化 ---
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ai_client = OpenAI(api_key=OPENAI_API_KEY)

# --- 3. Firebase / Firestore の初期化（既存のものを維持） ---
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


# --- 4. LINE Webhook 受信口（エラーを防止する安全設計に修正） ---
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except Exception as e:
        print(f"Webhook Error: {e}")
        abort(400)
    return 'OK', 200


# --- 5. 美しいFlex Message UI（既存のものをそのまま維持） ---
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


# --- 6. メイン処理：司書によるインテリジェント探索（タイムアウトを根絶） ---
@handler.add(MessageEvent, message=TextMessage)
def handle_line_message(event):
    reply_token = event.reply_token
    user_message = event.message.text.strip()
    
    if db is None:
        return

    try:
        # ─── 司書脳（LLM）ステップ1: ユーザーの曖昧な言葉から「検索キー」を優しく抽出 ───
        intent_response = ai_client.chat.completions.create(
            model="gpt-4o-mini",  # 高速かつ安価なモデルでキーワードを抽出
            messages=[
                {"role": "system", "content": "ユーザーの文章から、日本の『都道府県名』、または『被写体や季節のキーワード（例：桜、新緑、富士山など）』を2個以内の単語で抽出して、カンマ区切りで出力してください。該当がない場合は「無」とだけ出力してください。例：「長野で桜が見たい」➔「長野県,桜」"},
                {"role": "user", "content": user_message}
            ],
            temperature=0.0
        )
        
        search_keywords = [k.strip() for k in intent_response.choices[0].message.content.split(",") if k.strip() != "無"]
        
        # ─── 司書脳ステップ2: 15,000件を stream() せず、安全に限定検索 ───
        photos_ref = db.collection('Master_Photos')
        matched_photos = []
        
        # まずは、キーワードに関連しそうなデータを「最大100件」に厳格に制限してロード（タイムアウトを100%防止）
        # キーワードが都道府県なら、Prefectureカラムで高速インデックス検索
        if search_keywords:
            main_keyword = search_keywords[0]
            # 都道府県でのクエリ
            query = photos_ref.where('Prefecture', '==', main_keyword).limit(100)
            docs = query.stream()
            matched_photos = [doc.to_dict() for doc in docs]
            
            # 都道府県でヒットしなかった場合、LocationやSubjectにキーワードが含まれるものを探す（安全な上限数で回す）
            if not matched_photos:
                fallback_docs = photos_ref.limit(200).stream() # 15,000件ではなく、先頭200件に絞って安全に検索
                for doc in fallback_docs:
                    data = doc.to_dict()
                    if main_keyword in str(data.get('Location', '')) or main_keyword in str(data.get('Subject', '')):
                        matched_photos.append(data)
        
        # 万が一、何も引っかからなかった場合は全体の先頭からランダムに紹介
        if not matched_photos:
            random_docs = photos_ref.limit(10).stream()
            matched_photos = [doc.to_dict() for doc in random_docs]

        # マッチした中から1件をそっと選出
        target_data = random.choice(matched_photos)

        # ─── 司書脳ステップ3: 抽出したデータから、品格ある案内文を生成 ───
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

        # ─── 🤖 ステップ4: 「司書の言葉」＋「美しいFlex UI」の2連コンボで返信 ───
        title = target_data.get('Title', '無題')
        location = target_data.get('Location', '不明な撮影地')
        author = target_data.get('Author', '不明')
        camera = target_data.get('Camera_Body', '情報なし')
        lens = target_data.get('Lens', '情報なし')
        
        settings = f"F{target_data.get('Aperture', '-')} / ISO {target_data.get('ISO', '-')} / {target_data.get('Focal_Length', '-')}mm"
        weather = target_data.get('Weather', '不明')
        
        # 既存データにある「プロのロジック解説」をUIにマッピング
        guide = target_data.get('Judge_Comment_Summary', 'ナビ情報は現在準備中です。')
        judge_comment = target_data.get('Logic_Advice', 'アドバイスは現在準備中です。')
        
        bubble_json = create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment)
        
        # 司書のテキストメッセージと、美しいカードUIを同時にLINEへ返却
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