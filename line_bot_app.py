import os
import json
import traceback
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
    reply_token = event['replyToken']
    if db_default is None: return

    # 📊 18件の生中身を限界まで暴露するレポート
    report = []
    report.append("📊 【金庫内データ 18件全件・生中身暴露】")
    report.append("※検索フィルターはすべて解除しました。")
    report.append("----------------------------------")

    try:
        # 金庫から18件のデータを無条件で全件回収
        guide_docs = db_default.collection("Location master").stream()
        all_guides = [d.to_dict() for d in guide_docs]
        
        report.append(f"📂 案内データの実際の総数: {len(all_guides)} 件\n")

        if all_guides:
            for i, g in enumerate(all_guides):
                # 1件ごとに、中身の主要な列の値をそのまま書き出す
                loc_id = g.get('Loc_ID', 'なし')
                area = g.get('Area', 'なし')
                place = g.get('Place', 'なし')
                period_idx = g.get('PeriodIdx', 'なし')
                title = g.get('Title', 'なし')
                
                # 🎯 列名そのものが化けていないか確認するため、データの「鍵」も全表示
                all_keys = list(g.keys())
                
                report.append(f"【{i+1}件目】")
                report.append(f"  ・Loc_ID : {loc_id}")
                report.append(f"  ・都道府県(Area) : {area}")
                report.append(f"  ・撮影地(Place) : {place}")
                report.append(f"  ・期間番号(PeriodIdx) : {period_idx} (型: {type(g.get('PeriodIdx')).__name__})")
                report.append(f"  ・タイトル(Title) : {title}")
                report.append(f"  ・格納されている実際の列名一覧:\n    {', '.join(all_keys)}")
                report.append("-" * 20)
        else:
            report.append("🚨 警告：金庫の部屋『Location master』の中身が完全に空っぽです。")

        # 18件分の生テキストをドカンとLINEに返信する
        # ※文字数がLINEの上限（5000文字）を超えないよう、安全に分割して送信
        full_text = "\n".join(report)
        if len(full_text) > 4000:
            full_text = full_text[:4000] + "\n\n...（文字数制限のため省略）"

        line_bot_api.reply_message(reply_token, TextSendMessage(text=full_text))

    except Exception as e:
        line_bot_api.reply_message(reply_token, TextSendMessage(text=f"❌ 全件暴露エラー:\n{traceback.format_exc()}"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
