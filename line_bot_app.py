import os
import json
import traceback
from datetime import datetime, timedelta
from flask import Flask, request
from linebot import LineBotApi
from linebot.models import TextSendMessage

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

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

@app.route("/callback", methods=['POST'])
def callback():
    try:
        request_json = request.get_json()
        for event in request_json.get('events', []):
            if event.get('type') == 'message' and event['message'].get('type') == 'text': 
                handle_line_message(event)
    except: 
        pass
    return 'OK', 200

def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    if db_default is None: return

    # 5月29日の前後15日窓（数値型と文字列型の両方のブレを100%吸収）
    target_slots = [15, 16, "15", "16"]

    # 📊 すべての情報を1つの「テキスト」にまとめる
    report = []
    report.append("📊 【金庫データ リアルタイム開通レポート】")
    report.append("----------------------------------")

    try:
        # ① 15,281件の写真データ部屋の生存確認
        photo_col1 = db_default.collection("photo master").stream()
        photo_count1 = sum(1 for _ in photo_col1)
        report.append(f"📸 写真データ [photo master]: {photo_count1} 件")
        
        # ② 案内データ18件の生存確認
        guide_docs = db_default.collection("Location master").stream()
        all_guides = [d.to_dict() for d in guide_docs]
        report.append(f"📂 案内データ [Location master]: {len(all_guides)} 件")
        report.append("----------------------------------")

        # ③ 18件の中身のPeriodIdxを、化けてようが何だろうが文字で全出力
        if all_guides:
            report.append("💡 【案内データにある実際のPeriodIdxの値】")
            for i, g in enumerate(all_guides):
                p_idx = g.get('PeriodIdx', '❌空欄')
                area = g.get('Area', '❌空欄')
                place = g.get('Place', '❌空欄')
                report.append(f"  ・{i+1}件目: 地域={area} | 撮影地={place} | PeriodIdx={p_idx}")
        else:
            report.append("🚨 案内データ部屋の中身が完全に空っぽです。")

        report.append("----------------------------------")
        report.append("\n🧭 次のステップへの案内:")
        report.append("この文字がLINEに届けば、大元のCSVファイルのどこに表記の揺らぎ（.0など）があるのかが、Kaoruさんの画面で一瞬で白黒つきます！")

        # 🎯 複雑なFlexメッセージ（ボタン）を一旦完全にやめ、純粋なテキスト1本だけで送信
        full_text = "\n".join(report)
        if len(full_text) > 4000:
            full_text = full_text[:4000] + "\n...（省略）"

        line_bot_api.reply_message(reply_token, TextSendMessage(text=full_text))

    except Exception as e:
        # 万が一ここがバグっても、チケット（ReplyToken）が生きてる最初の1回目なので、絶対にLINEにエラー文字が届く
        line_bot_api.reply_message(reply_token, TextSendMessage(text=f"❌ 内部処理エラー:\n{str(e)}"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
import json
import traceback
from datetime import datetime, timedelta
from flask import Flask, request
from linebot import LineBotApi
from linebot.models import TextSendMessage

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

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

@app.route("/callback", methods=['POST'])
def callback():
    try:
        request_json = request.get_json()
        for event in request_json.get('events', []):
            if event.get('type') == 'message' and event['message'].get('type') == 'text': 
                handle_line_message(event)
    except: 
        pass
    return 'OK', 200

def handle_line_message(event):
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    if db_default is None: return

    # 5月29日の前後15日窓（数値型と文字列型の両方のブレを100%吸収）
    target_slots = [15, 16, "15", "16"]

    # 📊 すべての情報を1つの「テキスト」にまとめる
    report = []
    report.append("📊 【金庫データ リアルタイム開通レポート】")
    report.append("----------------------------------")

    try:
        # ① 15,281件の写真データ部屋の生存確認
        photo_col1 = db_default.collection("photo master").stream()
        photo_count1 = sum(1 for _ in photo_col1)
        report.append(f"📸 写真データ [photo master]: {photo_count1} 件")
        
        # ② 案内データ18件の生存確認
        guide_docs = db_default.collection("Location master").stream()
        all_guides = [d.to_dict() for d in guide_docs]
        report.append(f"📂 案内データ [Location master]: {len(all_guides)} 件")
        report.append("----------------------------------")

        # ③ 18件の中身のPeriodIdxを、化けてようが何だろうが文字で全出力
        if all_guides:
            report.append("💡 【案内データにある実際のPeriodIdxの値】")
            for i, g in enumerate(all_guides):
                p_idx = g.get('PeriodIdx', '❌空欄')
                area = g.get('Area', '❌空欄')
                place = g.get('Place', '❌空欄')
                report.append(f"  ・{i+1}件目: 地域={area} | 撮影地={place} | PeriodIdx={p_idx}")
        else:
            report.append("🚨 案内データ部屋の中身が完全に空っぽです。")

        report.append("----------------------------------")
        report.append("\n🧭 次のステップへの案内:")
        report.append("この文字がLINEに届けば、大元のCSVファイルのどこに表記の揺らぎ（.0など）があるのかが、Kaoruさんの画面で一瞬で白黒つきます！")

        # 🎯 複雑なFlexメッセージ（ボタン）を一旦完全にやめ、純粋なテキスト1本だけで送信
        full_text = "\n".join(report)
        if len(full_text) > 4000:
            full_text = full_text[:4000] + "\n...（省略）"

        line_bot_api.reply_message(reply_token, TextSendMessage(text=full_text))

    except Exception as e:
        # 万が一ここがバグっても、チケット（ReplyToken）が生きてる最初の1回目なので、絶対にLINEにエラー文字が届く
        line_bot_api.reply_message(reply_token, TextSendMessage(text=f"❌ 内部処理エラー:\n{str(e)}"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
