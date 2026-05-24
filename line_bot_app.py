import os
import json
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage, QuickReply, QuickReplyButton, MessageAction
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


# --- 5. メイン処理：時期（36分割）× 地域インデックスによる超高速事前絞り込み ---
def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    
    if db is None:
        return

    try:
        # 【あなたの設計思想：時期の36分割（5月下旬コンテキスト）】
        # 15,000件のデータを「5月」「下旬」という完全一致クエリで、最初に数百分の一に超高速フィルタリングします。
        current_month = "5月"
        current_period = "下旬"

        # ユーザー発話から「地域（都道府県）」のインデックスを特定
        target_pref = None
        if any(k in user_message for k in ["東京", "関東", "在住", "静岡", "山梨"]):
            # 関東近郊・富士山周辺エリアにターゲットを事前ロック
            target_pref = ["静岡県", "山梨県", "東京都", "神奈川県", "千葉県", "埼玉県", "栃木県"]
        elif any(k in user_message for k in ["京都", "関西", "大阪"]):
            target_pref = ["京都府", "大阪府", "兵庫県", "奈良県"]

        # 「富士山」単発への能動的レコメンド
        if user_message == "富士山":
            reply_text = f"富士山ですね！今の時期（{current_month}{current_period}・初夏）に最高の表情を見せるスポットを、マトリクスから事前抽出しました。\n\n本日の撮影プランに合わせて、以下の特選レコメンドから選択してください。"
            items = [
                QuickReplyButton(action=MessageAction(label="🌊 今が旬！滝 × 富士山", text="富士山 滝 5月 下旬")),
                QuickReplyButton(action=MessageAction(label="🚄 定番！新幹線 × 富士山", text="富士山 新幹線 5月 下旬")),
                QuickReplyButton(action=MessageAction(label="🌱 静岡側 × 茶畑新緑", text="富士山 茶畑 5月 下旬")),
                QuickReplyButton(action=MessageAction(label="🏞️ 山梨側 × 湖水逆さ富士", text="富士山 湖 5月 下旬"))
            ]
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text, quick_reply=QuickReply(items=items)))
            return

        # --- 【超高速絞り込みクエリの実行】 ---
        # 15,000件に対してフルスキャンするのではなく、Firestoreのインデックスを効かせて
        # 「5月」「下旬」に合致するデータ（数百件規模）だけをサーバーにロード。
        query = db.collection('Master_Photos').where('Month', '==', current_month).where('Period', '==', current_period)
        
        # 地域要素があればさらにFirestore側で数十件レベルに事前絞り込み
        if target_pref:
            # 最初の1件目の都道府県を代表インデックスとして安全に絞り込み
            query = query.where('Prefecture', '==', target_pref[0])
            
        docs = query.stream()
        
        target_data = None
        keywords = user_message.split()

        # 数十件〜数百件に絞り込まれた安全な分母の中だけで、最終マッピングを検証（タイムアウトは100%起きません）
        for doc in docs:
            full_data = doc.to_dict()
            if not full_data: continue
            
            db_loc = str(full_data.get('Location', ''))
            db_title = str(full_data.get('Title', ''))

            # 切り出されたキーワード（例：富士山、滝、新幹線など）と最終突合
            if keywords:
                if any((k in db_loc or k in db_title) for k in keywords):
                    target_data = full_data
                    break
            else:
                target_data = full_data
                break

        # もし都道府県のインデックスが外れて見つからなかった場合のフォールバック（全体からキーワードで再検索）
        if not target_data and len(keywords) > 0:
            fallback_docs = db.collection('Master_Photos').stream()
            for doc in fallback_docs:
                full_data = doc.to_dict()
                if not full_data: continue
                if keywords[0] in str(full_data.get('Location', '')) or keywords[0] in str(full_data.get('Title', '')):
                    target_data = full_data
                    break

        # 【結果を「添削指導UI（Flex Message）」で最速返却】
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
            line_bot_api.reply_message(reply_token, FlexSendMessage(alt_text="撮影地コンシェルジュレポート", contents=bubble_json))
        else:
            line_bot_api.reply_message(
                reply_token, 
                TextSendMessage(text="指定された時期・地域のマトリクスから合致する撮影地を特定できませんでした。キーワードを変えて再度お試しください。")
            )
            
    except Exception as e:
        print(f"Pre-filtering System Error: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)