import os
import json
import traceback
from datetime import datetime, timedelta
from flask import Flask, request
from linebot import LineBotApi
from linebot.models import TextSendMessage, FlexSendMessage
from google.cloud import firestore
from google.oauth2 import service_account
from collections import Counter

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

PREFECTURES = [
    "北海道", "青森", "岩手", "宮城", "秋田", "山形", "福島", "茨城", "栃木", "群馬",
    "埼玉", "千葉", "東京", "神奈川", "新潟", "富山", "石川", "福井", "山梨", "長野",
    "岐阜", "静岡", "愛知", "三重", "滋賀", "京都", "大阪", "兵庫", "奈良", "和歌山",
    "鳥取", "島根", "岡山", "広島", "山口", "徳島", "香川", "愛媛", "高知", "福岡",
    "佐賀", "長崎", "熊本", "大分", "宮崎", "鹿児島", "沖縄"
]

db_default = None
try:
    firebase_creds_json = os.environ.get('FIREBASE_CREDENTIALS')
    if firebase_creds_json:
        creds_dict = json.loads(firebase_creds_json)
        project_id = creds_dict.get('project_id')
        cred = service_account.Credentials.from_service_account_info(creds_dict)
        db_default = firestore.Client(project=project_id, database='(default)', credentials=cred)
except Exception as e:
    print(f"Firebase Init Error: {e}")

def get_shun_index(month, day):
    if day <= 10: d = 1
    elif day <= 20: d = 2
    else: d = 3
    return (month - 1) * 3 + d

def create_ui_buttons(reply_text, choices_list):
    buttons_contents = []
    for item in choices_list:
        buttons_contents.append({
            "type": "button",
            "action": {"type": "message", "label": item["label"][:15], "text": item["text"]},
            "style": "secondary", "margin": "sm"
        })
    return {"type": "bubble", "body": {"type": "box", "layout": "vertical", "spacing": "md", "contents": [{"type": "text", "text": reply_text, "wrap": True, "size": "xl", "color": "#111111", "weight": "bold"}, {"type": "box", "layout": "vertical", "spacing": "xs", "contents": buttons_contents}]}}

@app.route("/callback", methods=['POST'])
def callback():
    try:
        request_json = request.get_json()
        for event in request_json.get('events', []):
            if event.get('type') == 'message' and event['message'].get('type') == 'text': 
                handle_line_message(event)
    except: 
        print(traceback.format_exc())
    return 'OK', 200

def handle_line_message(event):
    user_id = event['source']['userId']
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    if db_default is None: return
    
    # 5月29日の前後15日窓（数値型と文字列型の両方のブレを100%吸収）
    target_slots = [15, 16, "15", "16"]
    base_date = datetime(2026, 5, 28)
    target_date = base_date + timedelta(days=1)

    try:
        session_ref = db_default.collection('User_Sessions').document(user_id)
        session_doc = session_ref.get()

        if user_message == "やめる":
            session_ref.delete()
            line_bot_api.reply_message(reply_token, TextSendMessage(text="社史編纂室にてお待ちしております。"))
            return

        # 🎯 ボタンをタップしたときの処理（日本の正しい漢字「選ぶ地域」で完全一致）
        if "選ぶ地域:" in user_message or "選ぶポイント:" in user_message:
            word_name = user_message.replace("選ぶ地域:", "").replace("選ぶポイント:", "").strip()
            
            # 該当データを15日間窓から再度スキャンしてログ確認
            matched_guides = []
            docs = db_default.collection("Location master").where('PeriodIdx', 'in', target_slots).stream()
            for doc in docs:
                gdata = doc.to_dict()
                pool = str(gdata.get('Area', '')) + str(gdata.get('Place', '')) + str(gdata.get('Title', ''))
                if word_name in pool:
                    matched_guides.append(gdata)

            if not matched_guides:
                line_bot_api.reply_message(reply_token, TextSendMessage(text=f"📊 検証：『{word_name}』に合致するデータは金庫内で0件でした。"))
            else:
                # 暫定的にヒットした撮影地の生テキスト情報をLINEにそのままテキストで返す（デバッグ用）
                res_text = f"📊 【ボタン反応成功レポート】\n選択された単語: {word_name}\nヒット件数: {len(matched_guides)}件\n\n【該当箇所サンプル】\n"
                for i, g in enumerate(matched_guides[:3]):
                    res_text += f"・{g.get('Area')} - {g.get('Place')} ({g.get('Title')})\n"
                line_bot_api.reply_message(reply_token, TextSendMessage(text=res_text))
            return

        # 最初の提案フェーズ（「明日」などのメッセージ受信時）
        if not session_doc.exists or any(k in user_message for k in ["明日", "おすすめ", "お勧め", "撮影"]):
            
            # 📊 数値結果レポートのテキストを組み立て
            report = []
            report.append("📊 【LINE検索 数値結果レポート】")
            
            all_docs = db_default.collection("Location master").stream()
            all_guides = [d.to_dict() for d in all_docs]
            report.append(f"📂 金庫（Location master）の総登録数: {len(all_guides)} 件")

            matched_guides = []
            docs = db_default.collection("Location master").where('PeriodIdx', 'in', target_slots).stream()
            for doc in docs:
                matched_guides.append(doc.to_dict())
                
            report.append(f"🎯 5月下旬〜6月上旬の期間ヒット数: {len(matched_guides)} 件")
            report.append("----------------------------------")

            area_names, point_names = [], []
            for g in matched_guides:
                a_val = str(g.get('Area', '')).strip()
                p_val = str(g.get('Place', '')).strip()
                if a_val and a_val.lower() not in ["null", "nan", "none", ""]: area_names.append(a_val)
                if p_val and p_val.lower() not in ["null", "nan", "none", ""]: point_names.append(p_val)

            area_ranks = [w[0] for w in Counter(area_names).most_common(2) if w[0]]
            point_ranks = [w[0] for w in Counter(point_names).most_common(2) if w[0]]

            if matched_guides:
                report.append("🗺️ 【地域（Area列）の内訳】")
                for k, v in Counter(area_names).items(): report.append(f"  ・{k}: {v} 件")
                report.append("\n📍 【撮影地（Place列）の内訳】")
                for k, v in Counter(point_names).items(): report.append(f"  ・{k}: {v} 件")
            else:
                report.append("🚨 【警告】期間内ヒットが0件です。PeriodIdxの型（文字/数字）か、コレクション名を確認してください。")

            # 🗺️ 選択肢UIのテキスト（被写体を完全に排除したシンプルな案内文）
            ui_text = "社史編纂室の情報から、この時期に特におすすめの地域や名所を割り出しました。どちらの方面のデータを開きますか？"
            
            # 🎯 【完全修正】日本の正しい漢字「選ぶ地域:」「選ぶポイント:」に統合
            choices = []
            for a in area_ranks: choices.append({"label": f"🗺️ 地域: {a}", "text": f"選ぶ地域: {a}"})
            for p in point_ranks: choices.append({"label": f"📍 名所: {p}", "text": f"選ぶポイント: {p}"})
            choices.append({"label": "❌ やめる", "text": "やめる"})

            session_ref.set({"target_timestamp": target_date.timestamp()})
            
            # 🎯 数値レポートのテキストと、綺麗に直したUIボタンの「2個のメッセージ」を同時に送信する
            line_bot_api.reply_message(reply_token, [
                TextSendMessage(text="\n".join(report)),
                FlexSendMessage.new_from_json_dict({"type": "flex", "altText": "ご提案メニュー", "contents": create_ui_buttons(ui_text, choices)})
            ])
            return

    except: 
        line_bot_api.reply_message(reply_token, TextSendMessage(text=f"❌ 処理エラー発生:\n{traceback.format_exc()}"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
