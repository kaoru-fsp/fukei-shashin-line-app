import os
import json
import random
import traceback
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi
from linebot.models import TextSendMessage, FlexSendMessage
import firebase_admin
from firebase_admin import credentials, firestore
from openai import OpenAI

app = Flask(__name__)

# ==========================================================
# 📸 【FUPC管理サーバー】画像閲覧用ベースURL（将来の移転時はここを変更）
# ==========================================================
IMAGE_BASE_VIEW = "https://fupc.photo/PicsDB/PicsDB4Search/"

# --- 1. LINE API の初期化 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

# --- 2. OpenAI API の初期化 ---
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

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


# --- 5. 【完全維持 ＋ 本物の入賞作品画像対応】元の添削指導UI ---
def create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment):
    # ※裏側で生成された、この名作固有の「fupcサーバーの画像URL」がグローバルまたは動的にheroへセットされます
    global TARGET_IMAGE_URL
    image_url = TARGET_IMAGE_URL if 'TARGET_IMAGE_URL' in globals() else "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=1000&q=80"

    flex_bubble = {
      "type": "bubble",
      "hero": {
        "type": "image",
        "url": image_url, # ➔ FUPCサーバーの文字入り閲覧用画像がここに美しく咲きます
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


# --- 6. 【大文字・大ボタン仕様】視認性抜群のカスタム選択肢メニュー ---
def create_大文字選択肢_ui(reply_text, quick_replies):
    buttons_contents = []
    for label in quick_replies:
        buttons_contents.append({
            "type": "button",
            "action": {
                "type": "message",
                "label": label[:15],
                "text": label
            },
            "style": "secondary",
            "color": "#f0f0f0",
            "margin": "sm"
        })
        
    flex_bubble = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": reply_text,
                    "wrap": True,
                    "size": "md",
                    "color": "#111111",
                    "weight": "bold"
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "xs",
                    "contents": buttons_contents
                }
            ]
        }
    }
    return flex_bubble


# --- 7. 対話 ＆ 画像自動生成エンジン ---
def handle_line_message(event):
    global TARGET_IMAGE_URL
    user_id = event['source']['userId']
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    
    if db is None or not ai_client: return

    now = datetime.now()
    default_month = f"{now.month}月"
    default_period = "初旬" if now.day <= 10 else "中旬" if now.day <= 20 else "下旬"

    try:
        session_ref = db.collection('User_Sessions').document(user_id)
        session_doc = session_ref.get()
        
        is_new_topic = False
        if session_doc.exists:
            current_state = session_doc.to_dict()
            past_pref = current_state.get("prefecture", "無し")
            if past_pref != "無し" and past_pref != "特定不能":
                past_pref_short = past_pref.replace("県", "").replace("府", "").replace("都", "").replace("道", "")
                if past_pref_short not in user_message and any(p in user_message for p in ["長野", "山梨", "静岡", "山形", "福島", "富士山"]):
                    is_new_topic = True
        else:
            is_new_topic = True

        if is_new_topic:
            current_state = {"month": default_month, "period": default_period, "prefecture": "無し", "subject": "無し", "turn_count": 1}
        else:
            current_state["turn_count"] = current_state.get("turn_count", 0) + 1

        # AIによるスマート文脈解釈
        system_prompt = f"""
        あなたは雑誌『風景写真』の格調高いAIコンシェルジュです。
        【現在の会話ステート】
        - 月: {current_state.get('month')}
        - 旬: {current_state.get('period')}
        - 都道府県: {current_state.get('prefecture')}
        - 被写体テーマ: {current_state.get('subject')}
        - 今回の会話ターン数: {current_state.get('turn_count')} 回目 (最大3回)

        【ルール】
        1. 返信文は必ず【100文字以内】でスマートに逆質問すること。
        2. 3回目のやり取り、または条件が揃った場合は必ず status を "COMPLETE" にすること。
        3. 1〜2回目は status を "ASK" にし、見やすい大きな選択肢ボタンのテキスト（最大4択）を quick_replies に入れること。
        """

        intent_response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        
        ai_res = json.loads(intent_response.choices[0].message.content.strip())
        status = ai_res.get("status", "ASK")
        updated_state = ai_res.get("updated_state", current_state)
        updated_state["turn_count"] = current_state["turn_count"]
        
        reply_text = ai_res.get("reply_text", "どのような風景をお探しですか？")
        quick_replies = ai_res.get("quick_replies", [])

        if current_state["turn_count"] >= 3:
            status = "COMPLETE"

        session_ref.set(updated_state)

        # ─── 🔁 1〜2回目：大文字カスタムボタンメニューを最速送信（画像はまだ出さない） ───
        if status == "ASK":
            if not quick_replies: quick_replies = ["次の候補を見る"]
            menu_json = create_大文字選択肢_ui(reply_text, quick_replies)
            line_bot_api.reply_message(event['replyToken'], FlexSendMessage(alt_text="コンシェルジュからのご提案", contents=menu_json))
            return

        # ─── 🎯 3回目（確定時）：まとめとして本物の入賞作品画像つき極上カードを出す ───
        if status == "COMPLETE":
            session_ref.delete()

            target_month = updated_state.get("month", default_month)
            target_period = updated_state.get("period", default_period)
            target_pref = updated_state.get("prefecture", "無し")
            target_subject = updated_state.get("subject", "無し")

            photos_ref = db.collection('Master_Photos')
            query = photos_ref.where('Month', '==', target_month).where('Period', '==', target_period)
            if target_pref != "無し" and target_pref != "特定不能":
                query = query.where('Prefecture', '==', target_pref)
                
            docs = query.stream()
            matched_photos = [doc.to_dict() for doc in docs if doc.to_dict()]
            
            if target_subject != "無し" and matched_photos:
                filtered = [p for p in matched_photos if (target_subject in str(p.values()))]
                if filtered: matched_photos = filtered
            
            if not matched_photos:
                fallback_docs = photos_ref.limit(10).stream()
                matched_photos = [doc.to_dict() for doc in fallback_docs if doc.to_dict()]

            target_data = random.choice(matched_photos)

            # フィールド名ズレ自動吸収マッピング
            flat_data = {str(k).lower(): v for k, v in target_data.items() if v}
            
            # ─── 🔗 【最重要】仕様書に準拠した「閲覧用画像URL」の動的生成 ───
            published = flat_data.get('published') or target_data.get('Published')
            pic_file_name = flat_data.get('picfilename') or flat_data.get('pic_file_name') or target_data.get('PicFileName')
            
            if published and pic_file_name:
                pub_str = str(published).strip()
                parent_dir = pub_str[:4] # 先頭4文字（年）
                child_dir = pub_str      # 全体（子ディレクトリ）
                file_name = str(pic_file_name).strip()
                
                # 末尾のスラッシュ重複を防ぎ、綺麗に結合
                TARGET_IMAGE_URL = f"{IMAGE_BASE_VIEW.rstrip('/')}/{parent_dir}/{child_dir}/{file_name}"
            else:
                # 万が一データに画像名がない場合のセーフティ
                TARGET_IMAGE_URL = "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=1000&q=80"

            title = flat_data.get('title') or flat_data.get('subject') or target_data.get('Title', '名作風景')
            location = flat_data.get('location') or flat_data.get('area') or flat_data.get('place') or target_data.get('Location', '厳選撮影地')
            author = flat_data.get('author') or flat_data.get('winner') or target_data.get('Author', '写真家')
            camera = flat_data.get('camera_body') or flat_data.get('camera') or target_data.get('Camera_Body', '一眼レフ')
            lens = flat_data.get('lens') or target_data.get('Lens', '標準レンズ')
            
            if flat_data.get('exposure'):
                settings = flat_data.get('exposure')
            else:
                settings = f"F{flat_data.get('aperture', '-')} / ISO {flat_data.get('iso', '-')} / {flat_data.get('focal_length', '-')}mm"
                
            weather = flat_data.get('weather') or target_data.get('Weather', '晴れ')
            guide = flat_data.get('guide_page') or flat_data.get('context_advice') or 'ルートナビ情報は本棚に保管されています。'
            judge_comment = flat_data.get('judge_comment_summary') or flat_data.get('logic_advice') or '構図バランスが実に見事な名作です。'

            bubble_json = create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment)
            
            closing_text = "ご要望を反映し、今回の撮影計画に最適な名作の書棚をまとめました。どうぞご高覧ください。"
            line_bot_api.reply_message(
                event['replyToken'],
                [
                    TextSendMessage(text=closing_text),
                    FlexSendMessage(alt_text="撮影地コンシェルジュレポート", contents=bubble_json)
                ]
            )

    except Exception as e:
        try:
            line_bot_api.reply_message(event['replyToken'], TextSendMessage(text=f"🔍 システム調整中:\n再度の入力をお試しいただくか、しばらくお待ちください。"))
        except:
            pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
