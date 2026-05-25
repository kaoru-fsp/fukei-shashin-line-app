import os
import json
import random
import traceback
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi
from linebot.models import (
    TextSendMessage, FlexSendMessage, QuickReply, QuickReplyButton, MessageAction
)
import firebase_admin
from firebase_admin import credentials, firestore
from openai import OpenAI

app = Flask(__name__)

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


# --- 5. 【完全維持】元の添削指導UI（Flex Message） ---
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


# --- 6. 真の対話エンジン：3ターン制約・テンポ最優先型 ---
def handle_line_message(event):
    user_id = event['source']['userId']
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    
    if db is None or not ai_client: return

    # 時期の自動判定
    now = datetime.now()
    default_month = f"{now.month}月"
    default_period = "初旬" if now.day <= 10 else "中旬" if now.day <= 20 else "下旬"

    try:
        # ─── 🗄️ 記憶のロード（何回目の会話かもカウント） ───
        session_ref = db.collection('User_Sessions').document(user_id)
        session_doc = session_ref.get()
        
        if session_doc.exists:
            current_state = session_doc.to_dict()
            current_state["turn_count"] = current_state.get("turn_count", 0) + 1
        else:
            current_state = {
                "month": default_month,
                "period": default_period,
                "prefecture": "無し",
                "subject": "無し",
                "turn_count": 1
            }

        # ─── 🤖 AIによる文脈解釈 ＆ 3ターン強制クロージングプロンプト ───
        system_prompt = f"""
        あなたは雑誌『風景写真』の格調高いAIコンシェルジュです。無駄な長文や、同じ質問の繰り返しは厳禁です。

        【現在の会話ステート】
        - 月: {current_state.get('month')}
        - 旬: {current_state.get('period')}
        - 都道府県: {current_state.get('prefecture')}
        - 被写体テーマ: {current_state.get('subject')}
        - 今回の会話ターン数: {current_state.get('turn_count')} 回目 (最大3回)

        本日の日付の前提は【 {default_month} {default_period} 】です。

        【厳格な対話ルール】
        1. 簡潔さの徹底: あなたの返信文（reply_text）は、必ず【100文字以内】で、スマートに要点だけを伝えてください。くどい挨拶や前置きはすべて廃止してください。
        2. 3ターン制限: 現在のターン数は【 {current_state.get('turn_count')} 回目 】です。
           - ターン数が 3 に達した場合、または主要な条件（都道府県と被写体）が概ね予測できた場合は、絶対に会話を引き延ばさず、必ず status を "COMPLETE" にして会話を締めくくってください。
           - 1回目、2回目の大雑把な段階では、status を "ASK" にし、次の一手（中央道ルートか、東名ルートか等）をスパッと2〜4択のクイックリプライ（各12文字以内）で提案してください。
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
        # ターン数を引き継ぐ
        updated_state["turn_count"] = current_state["turn_count"]
        
        reply_text = ai_res.get("reply_text", "どのような風景をお探しですか？")
        quick_replies = ai_res.get("quick_replies", [])

        # 3回目のやり取りに達したら、何が何でも強制的にCOMPLETEにするセーフティ
        if current_state["turn_count"] >= 3:
            status = "COMPLETE"

        # セッションを更新保存
        session_ref.set(updated_state)

        # ─── 🔁 1〜2回目：端的な逆質問ボタンでテンポよく返す ───
        if status == "ASK":
            items = []
            for label in quick_replies:
                items.append(QuickReplyButton(action=MessageAction(label=label[:15], text=label)))
            q_reply = QuickReply(items=items) if items else None
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text, quick_reply=q_reply))
            return

        # ─── 🎯 3回目（または収束時）：まとめとして極上のカードをドンと出す ───
        if status == "COMPLETE":
            session_ref.delete()  # 記憶をクリア

            target_month = updated_state.get("month", default_month)
            target_period = updated_state.get("period", default_period)
            target_pref = updated_state.get("prefecture", "無し")
            target_subject = updated_state.get("subject", "無し")

            # 36分割マトリクス × 地域インデックス検索
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

            # 💎 フィールド名ズレ自動吸収マッピング
            flat_data = {str(k).lower(): v for k, v in target_data.items() if v}
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
            
            # 締めの挨拶も短くスマートに
            closing_text = "ご要望を反映し、今回の撮影計画に最適な名作の書棚をまとめました。どうぞご高覧ください。"
            line_bot_api.reply_message(
                reply_token,
                [
                    TextSendMessage(text=closing_text),
                    FlexSendMessage(alt_text="撮影地コンシェルジュレポート", contents=bubble_json)
                ]
            )

    except Exception as e:
        error_str = str(e)
        if "https://console.firebase.google.com" in error_str:
            url_start = error_str.find("https://console.firebase.google.com")
            index_url = error_str[url_start:].split()[0]
            msg = f"⚙️ Firestoreの複合インデックスの作成が必要です。\n以下のリンクを一度だけクリックして有効化してください：\n\n{index_url}"
            try:
                line_bot_api.reply_message(reply_token, TextSendMessage(text=msg))
            except:
                pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
