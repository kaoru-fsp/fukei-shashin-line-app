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


# --- 6. 真の対話エンジン：記憶保持型コンシェルジュシステム ---
def handle_line_message(event):
    user_id = event['source']['userId']
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    
    if db is None or not ai_client: return

    # 本日の「月・旬」の自動判定（ベースライン）
    now = datetime.now()
    default_month = f"{now.month}月"
    default_period = "初旬" if now.day <= 10 else "中旬" if now.day <= 20 else "下旬"

    try:
        # ─── 🗄️ 記憶のロード: Firestoreからこのユーザーの現在の対話ステートを取得 ───
        session_ref = db.collection('User_Sessions').document(user_id)
        session_doc = session_ref.get()
        
        if session_doc.exists:
            current_state = session_doc.to_dict()
        else:
            current_state = {"month": default_month, "period": default_period, "prefecture": "無し", "subject": "無し"}

        # ─── 🤖 AIによる文脈解釈 ＆ ステート自動更新 ───
        system_prompt = f"""
        あなたは雑誌『風景写真』の読者（シニアの写真愛好家）をエスコートする、極めて品格のある対話型AIコンシェルジュです。
        ユーザーは東京在住で、主にお車での移動（高速道路ルート）を想定しています。

        【現在の検索ステート】
        - 月: {current_state.get('month')}
        - 旬: {current_state.get('period')}
        - 都道府県: {current_state.get('prefecture')}
        - 被写体テーマ: {current_state.get('subject')}

        本日の日付の前提は【 {default_month} {default_period} 】です。「明日」や「週末」という発言にはこの前提を適用してください。

        【あなたの思考ミッション】
        1. ユーザーの最新の発言（例：「新緑が良いな」「静岡側で」など）を読み解き、上記の検索ステートを更新してください。
        2. 更新した結果、「都道府県」と「被写体テーマ」の双方が、撮影地を特定できるレベルにまで【具体的に絞り込まれたか】を判定してください。
        3. 大雑把な段階（例：「長野に行きたい」「おすすめある？」など）では、絶対にすぐカードを出してはいけません。会話のラリーを続けるため、statusを"ASK"にし、次の絞り込みのための紳士的な「逆質問・提案」と、ユーザーが押しやすい具体的なボタンの選択肢（最大4択、15文字以内）を作成してください。
        4. 条件が完全に揃った、またはユーザーの要望がピンポイントに収束したと判断した場合は、statusを"COMPLETE"にしてください。

        必ず以下のJSONフォーマットのみで正確に出力してください。
        {{
          "status": "ASK" または "COMPLETE",
          "updated_state": {{
            "month": "○月",
            "period": "〇旬",
            "prefecture": "〇〇県 または 無し",
            "subject": "〇〇（例：滝、茶畑、新緑、新幹線など） または 無し"
          }},
          "reply_text": "ユーザーへの紳士的なセリフ（ASKの場合は魅力的で具体的な逆質問、COMPLETEの場合は『かしこまりました。それでは条件に合う名作の書棚を開きます。』などの締めの言葉）",
          "quick_replies": ["選択肢1", "選択肢2"] (ASKの場合のみ。COMPLETEの場合は空配列 [])
        }}
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
        reply_text = ai_res.get("reply_text", "どのような風景をお探しですか？")
        quick_replies = ai_res.get("quick_replies", [])

        # 最新のステートを記憶（Firestoreへ上書き保存）
        session_ref.set(updated_state)

        # ─── 🔁 対話継続（ASK）モード: まだ絞り込み途中のため、逆質問ボタンを出して終了（カードは出さない） ───
        if status == "ASK":
            items = []
            for label in quick_replies:
                items.append(QuickReplyButton(action=MessageAction(label=label[:15], text=label)))
            
            q_reply = QuickReply(items=items) if items else None
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text, quick_reply=q_reply))
            return

        # ─── 🎯 絞り込み完了（COMPLETE）モード: 最後のまとめとして極上のカードをドンと出す ───
        if status == "COMPLETE":
            # 対話が完結したため、ユーザーのセッション記憶は綺麗にリセット（削除）
            session_ref.delete()

            target_month = updated_state.get("month", default_month)
            target_period = updated_state.get("period", default_period)
            target_pref = updated_state.get("prefecture", "無し")
            target_subject = updated_state.get("subject", "無し")

            # あなたの設計通り、36分割マトリクス × 地域インデックスで一撃狙い撃ち
            photos_ref = db.collection('Master_Photos')
            query = photos_ref.where('Month', '==', target_month).where('Period', '==', target_period)
            if target_pref != "無し":
                query = query.where('Prefecture', '==', target_pref)
                
            docs = query.stream()
            matched_photos = [doc.to_dict() for doc in docs if doc.to_dict()]
            
            # メモリ上での被写体（Subject）マッチング
            if target_subject != "無し" and matched_photos:
                filtered = [p for p in matched_photos if (target_subject in str(p.values()))]
                if filtered: matched_photos = filtered
            
            if not matched_photos:
                fallback_docs = photos_ref.limit(5).stream()
                matched_photos = [doc.to_dict() for doc in fallback_docs if doc.to_dict()]

            target_data = random.choice(matched_photos)

            # ─── 💎 フィールド名のズレを100%吸収する自動マッピング ───
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
            guide = flat_data.get('guide_page') or flat_data.get('context_advice') or 'ルートナビ情報は本棚に大切に保管されています。'
            judge_comment = flat_data.get('judge_comment_summary') or flat_data.get('logic_advice') or '画面全体の構成が実に見事な名作です。'

            # 組み立てたまとめのカードUI
            bubble_json = create_添削_ui(location, title, author, camera, lens, settings, weather, guide, judge_comment)
            
            # 対話のまとめ文と、リッチなカードを同時に返信（最高のクロージング）
            line_bot_api.reply_message(
                reply_token,
                [
                    TextSendMessage(text=reply_text),
                    FlexSendMessage(alt_text="撮影地コンシェルジュレポート", contents=bubble_json)
                ]
            )

    except Exception as e:
        error_str = str(e)
        print(f"🔥 Engine Crash Error:\n{traceback.format_exc()}")
        # 複合インデックスが未作成の場合のみ、生成用のURLをLINEに流す親切デバッグ
        if "https://console.firebase.google.com" in error_str:
            url_start = error_str.find("https://console.firebase.google.com")
            index_url = error_str[url_start:].split()[0]
            msg = f"⚙️ Firestoreの複合インデックスの作成が必要です。\n以下のリンクを一度だけクリックして、インデックスを有効化してください：\n\n{index_url}"
            try:
                line_bot_api.reply_message(reply_token, TextSendMessage(text=msg))
            except:
                pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
