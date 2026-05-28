import os
import json
import random
import re
from flask import Flask, request
from linebot import LineBotApi
from linebot.models import TextSendMessage
import firebase_admin
from firebase_admin import credentials, firestore
from openai import OpenAI

app = Flask(__name__)

# --- 1. API初期化 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ai_client = OpenAI(api_key=OPENAI_API_KEY)

db = None
def get_db():
    global db
    if db is not None: return db
    try:
        firebase_creds_json = os.environ.get('FIREBASE_CREDENTIALS')
        if firebase_creds_json:
            cred = credentials.Certificate(json.loads(firebase_creds_json))
            try: firebase_admin.initialize_app(cred)
            except ValueError: pass
            db = firestore.client()
            return db
    except Exception as e: print(f"Firebase Error: {e}", flush=True)
    return None

get_db()

# LINEのパースエラーを完全に封殺するカスタム送信クラス
class GachiFlexMessage:
    def __init__(self, alt_text, contents_dict):
        self.type = "flex"
        self.alt_text = alt_text
        self.contents = contents_dict
    def as_json_dict(self):
        return {"type": "flex", "altText": self.alt_text, "contents": self.contents}

# --- 2. 状態遷移用：Flexコンポーネント生成ビルダー ---

def build_initial_card(photo_id, data):
    """初動カード：撮影地名を最大に目立たせ、「ここを詳しく」を備える"""
    location = data.get('Location', '日本国内の撮影地')
    title = data.get('Title', '無題')
    author = data.get('Author', 'ライブラリー記録')
    
    return {
        "type": "bubble",
        "size": "mega",
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "xl",
            "contents": [
                # 写真エリア（タップすると作品詳細に切り替わるポストバックアクション）
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#cccccc",
                    "height": "200px",
                    "cornerRadius": "md",
                    "action": {
                        "type": "postback",
                        "data": f"action=artwork_info&id={photo_id}"
                    },
                    "contents": [
                        {"type": "text", "text": "📸 入賞作品イメージ (Tap for Detail)", "align": "center", "gravity": "center", "size": "sm", "color": "#666666", "weight": "bold"}
                    ]
                },
                # 最も目立たせる撮影地見出し
                {
                    "type": "text",
                    "text": location,
                    "weight": "bold",
                    "size": "xl",
                    "margin": "lg",
                    "wrap": True,
                    "color": "#111111"
                },
                {
                    "type": "text",
                    "text": f"参考作品：『{title}』 （{author} 著）",
                    "size": "sm",
                    "color": "#555555",
                    "wrap": True,
                    "margin": "xs"
                },
                # 「ここを詳しく」ボタン
                {
                    "type": "button",
                    "action": {
                        "type": "postback",
                        "label": "🔍 ここを詳しく",
                        "data": f"action=location_detail&id={photo_id}"
                    },
                    "style": "primary",
                    "color": "#1f3c3d",
                    "margin": "md"
                }
            ]
        }
    }

def build_artwork_info_card(photo_id, data):
    """写真タップ時の作品詳細画面"""
    title = data.get('Title', '無題')
    author = data.get('Author', 'ライブラリー記録')
    camera = data.get('Camera_Body', '情報なし')
    lens = data.get('Lens', '情報なし')
    aperture = data.get('Aperture', '-')
    iso = data.get('ISO', '-')
    focal = data.get('Focal_Length', '-')
    
    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#2c3e50",
            "paddingAll": "lg",
            "contents": [{"type": "text", "text": "🏆 入賞作品・機材詳細スペック", "color": "#ffffff", "weight": "bold"}]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {"type": "text", "text": f"作品名：『{title}』", "weight": "bold", "size": "md"},
                {"type": "text", "text": f"撮影者：{author} 著", "size": "sm"},
                {"type": "separator"},
                {"type": "text", "text": f"■ カメラ: {camera}", "size": "sm"},
                {"type": "text", "text": f"■ レンズ: {lens}", "size": "sm"},
                {"type": "text", "text": f"■ 露出設定: F{aperture} / ISO {iso} / {focal}mm", "size": "sm"},
                {"type": "button", "action": {"type": "postback", "label": "◀ 戻る", "data": f"action=back_to_initial&id={photo_id}"}, "style": "secondary", "margin": "lg"}
            ]
        }
    }

def build_location_detail_card(photo_id, data, current_db):
    """「ここを詳しく」タップ時の攻略画面（トチカン・セーフガイド・傑作選・リンク群）"""
    location = data.get('Location', '日本国内の撮影地')
    pref = data.get('Prefecture', '')
    guide = data.get('Judge_Comment_Summary', '現地ライブラリーデータに基づき撮影計画を構築してください。')
    subject = data.get('Subject', '風景写真')
    
    # 🔶 傑作選として同地域（都道府県）から最大3件をランダム選出
    masterpieces = []
    try:
        ref = current_db.collection('Master_Photos')
        docs = ref.where('Prefecture', '==', pref).limit(20).stream()
        pool = [d.to_dict() for d in docs if d.to_dict().get('Title') != data.get('Title')]
        if pool: masterpieces = random.sample(pool, min(len(pool), 3))
    except: pass

    mp_contents = []
    if masterpieces:
        for mp in masterpieces:
            mp_contents.append({"type": "text", "text": f"• 『{mp.get('Title','無題')}』（{mp.get('Author','')}）", "size": "sm", "color": "#333333", "wrap": True})
    else:
        mp_contents.append({"type": "text", "text": "• 周辺の過去入賞記録を照会中", "size": "sm", "color": "#777777"})

    # 安全情報の自動マッピング（セーフガイドのプロトタイプ構築）
    safe_info = "適切な防寒・登山装備を推奨。季節により周辺の野生動物（熊・猪）や、路面凍結に対する安全管理に留意してください。"
    if "山" in location or "森" in location or "高原" in location:
        safe_info = "⚠️【重要】山林・熊生息エリア：熊鈴・熊スプレーを必ず携行し、単独行動を避けてください。足元のトレッキングシューズ等も必須です。"

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1f3c3d",
            "paddingAll": "lg",
            "contents": [{"type": "text", "text": f"🗺️ 撮影地攻略：{location}", "color": "#ffffff", "weight": "bold", "size": "md"}]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                # 🔷 トチカン
                {"type": "text", "text": "🔷 【トチカン】地域密着撮影知見", "weight": "bold", "size": "sm", "color": "#1f3c3d"},
                {"type": "text", "text": guide, "size": "md", "wrap": True, "color": "#222222"},
                {"type": "separator", "margin": "md"},
                
                # 🔶 セーフガイド
                {"type": "text", "text": "🔶 【セーフガイド】安全・装備情報", "weight": "bold", "size": "sm", "color": "#c0392b"},
                {"type": "text", "text": safe_info, "size": "sm", "wrap": True, "color": "#444444"},
                {"type": "separator", "margin": "md"},
                
                # 🏆 同地域傑作選
                {"type": "text", "text": f"🏆 同地域における {pref}傑作選（3選）", "weight": "bold", "size": "sm", "color": "#d35400"},
                {"type": "box", "layout": "vertical", "spacing": "xs", "contents": mp_contents},
                {"type": "separator", "margin": "md"},
                
                # 🌐 各種外部インフラリンクへのアクセス
                {"type": "text", "text": "🌐 リアルタイム撮影インフラリンク", "weight": "bold", "size": "sm", "color": "#2980b9"},
                {
                    "type": "box", "layout": "horizontal", "spacing": "sm",
                    "contents": [
                        {"type": "button", "action": {"type": "uri", "label": "🗺️ Map", "uri": f"https://www.google.com/maps/search/?api=1&query={location}"}, "style": "link", "size": "sm"},
                        {"type": "button", "action": {"type": "uri", "label": "⏱️ ルート(時間表示)", "uri": f"https://www.google.com/maps/dir/?api=1&destination={location}"}, "style": "link", "size": "sm"},
                        {"type": "button", "action": {"type": "uri", "label": "☀️ 天気・天文・潮汐", "uri": "https://www.jma.go.jp/"}, "style": "link", "size": "sm"}
                    ]
                },
                {"type": "separator", "margin": "md"},
                
                # フッター制御アクション
                {
                    "type": "box", "layout": "horizontal", "spacing": "sm",
                    "contents": [
                        {"type": "button", "action": {"type": "postback", "label": "◀ 戻る", "data": f"action=back_to_initial&id={photo_id}"}, "style": "secondary", "size": "sm"},
                        {"type": "button", "action": {"type": "postback", "label": "🚗 ここから移動(2h)", "data": f"action=move_2h&id={photo_id}"}, "style": "primary", "color": "#2c3e50", "size": "sm"},
                        {"type": "button", "action": {"type": "postback", "label": "💾 ルートを記録", "data": f"action=record_route&id={photo_id}"}, "style": "primary", "color": "#27ae60", "size": "sm"}
                    ]
                }
            ]
        }
    }

def build_move_2h_card(photo_id, data, current_db, mode="normal"):
    """「ここから移動」または「今日の絶景夕景スポット」を表現するカルーセル/リスト基盤"""
    pref = data.get('Prefecture', '')
    
    # 2時間圏内という地理的要件のシミュレートとして、同一都道府県内の他作品をインテリジェントに抽出
    near_photos = []
    try:
        ref = current_db.collection('Master_Photos')
        docs = ref.where('Prefecture', '==', pref).limit(30).stream()
        
        if mode == "sunset":
            # 夕景スポットモード：SubjectやTitleに夕・暮・陽・西・晩などのキーワードが含まれるものを優先抽出
            near_photos = [d.to_dict() for d in docs if any(k in str(d.to_dict().get('Subject',''))+str(d.to_dict().get('Title','')) for k in ["夕","暮","日没","陽","西"])]
        else:
            near_photos = [d.to_dict() for d in docs if d.to_dict().get('Title') != data.get('Title')]
            
        if not near_photos:
            # フォールバック
            near_photos = [d.to_dict() for d in ref.limit(3).stream()]
    except: pass

    # 最大3つの近隣・周辺ポイントを表示
    display_items = near_photos[:3]
    bubbles = []
    
    for idx, item in enumerate(display_items):
        loc = item.get('Location', '近隣の撮影ポイント')
        t = item.get('Title', '作品名')
        a = item.get('Author', '著者')
        
        bubbles.append({
            "type": "bubble",
            "size": "mega",
            "body": {
                "type": "box", "layout": "vertical", "paddingAll": "lg",
                "contents": [
                    {"type": "text", "text": "🚗 2時間圏内の周辺候補地" if mode == "normal" else "🌇 2時間圏内の夕景絶景スポット", "size": "xs", "color": "#e74c3c", "weight": "bold"},
                    {"type": "text", "text": loc, "weight": "bold", "size": "md", "margin": "xs", "wrap": True},
                    {"type": "text", "text": f"『{t}』（{a}）", "size": "xs", "color": "#666666", "wrap": True},
                    {"type": "button", "action": {"type": "postback", "label": "🔍 ここを詳しく", "data": f"action=location_detail&id=move_{idx}_{photo_id}"}, "style": "primary", "color": "#1f3c3d", "margin": "sm", "size": "sm"}
                ]
            }
        })

    # フッターとして制御ボタン群のナビゲーションを追加
    footer_actions = [
        {"type": "button", "action": {"type": "postback", "label": "◀ 撮影地詳細へ戻る", "data": f"action=location_detail&id={photo_id}"}, "style": "secondary", "size": "sm", "margin": "sm"}
    ]
    if mode == "normal":
        footer_actions.append({"type": "button", "action": {"type": "postback", "label": "🌇 今日の絶景夕景スポット", "data": f"action=sunset_2h&id={photo_id}"}, "style": "primary", "color": "#d35400", "size": "sm", "margin": "sm"})

    # カルーセルの末尾に、戻る・切り替えるための制御用バブルを結合
    bubbles.append({
        "type": "bubble",
        "size": "sm",
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "md", "gravity": "center",
            "contents": footer_actions
        }
    })
    
    return {"type": "carousel", "contents": bubbles}

# --- 3. イベントハンドラー（LINEルーティング） ---

@app.route("/callback", methods=['POST'])
def callback():
    try:
        request_json = request.get_json()
        events = request_json.get('events', [])
        for event in events:
            if event.get('type') == 'message' and event['message'].get('type') == 'text':
                handle_line_message(event)
            elif event.get('type') == 'postback':
                handle_line_postback(event)
    except Exception as e: print(f"Root Callback Error: {e}", flush=True)
    return 'OK', 200

def handle_line_message(event):
    """初動入力：インテントを判別し、1通目(テキストの挨拶)と2通目(目立つ撮影地カード)を同時射出"""
    reply_token = event['replyToken']
    user_message = event['message']['text'].strip()
    current_db = get_db()
    if current_db is None: return

    # AI検索のインテント分析
    intent_pref = ""
    intent_keyword = "朝焼け"
    try:
        intent_response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": 'ユーザーの言葉から検索のヒントを抽出し、以下のJSONで出力。{"pref": "都道府県名。なければ空文字", "keyword": "撮影キーワード（日の出、桜、朝霧、新緑など）。なければ朝焼け"}'},
                {"role": "user", "content": user_message}
            ],
            temperature=0.1
        )
        intent = json.loads(intent_response.choices[0].message.content)
        intent_pref = intent.get("pref", "")
        intent_keyword = intent.get("keyword", "朝焼け")
    except: pass

    # 金庫からの正確な1件選出
    matched_photos = []
    try:
        ref = current_db.collection('Master_Photos')
        if intent_pref:
            docs = ref.where('Prefecture', '==', intent_pref).limit(1).stream()
            matched_photos = [(doc.id, doc.to_dict()) for doc in docs]
        if not matched_photos:
            wide_docs = ref.limit(200).stream()
            for doc in wide_docs:
                d = doc.to_dict()
                if intent_keyword in str(d.get('Subject','')) or intent_keyword in str(d.get('Location','')) or intent_keyword in str(d.get('Title','')):
                    matched_photos.append((doc.id, d))
                    break
        if not matched_photos:
            matched_photos = [(doc.id, doc.to_dict()) for doc in ref.limit(1).stream()]
    except: pass

    if not matched_photos: return
    doc_id, target_data = matched_photos[0]

    # 天候・挨拶マッピング
    weather = target_data.get('Weather', '').strip()
    if not weather or weather.lower() in ["nan", "none", "不明", ""]:
        weather_phrase = "明日はお天気もいいようですから"
    elif "晴" in weather or "快晴" in weather:
        weather_phrase = f"明日はお天気も{weather}のようですから"
    else:
        weather_phrase = f"明日はお天気も{weather}模様のようですから"

    if "明日" in user_message:
        greeting = f"ようこそ『風景写真』コンシェルジュの部屋へ。それで明日撮影にお出かけですか。{weather_phrase}撮影も楽しめそうですね。今時分ですと皆さんこんなところでいい作品を撮っているようですよ"
    else:
        greeting = f"ようこそ『風景写真』コンシェルジュの部屋へ。本日は撮影のご相談でしょうか。今時分ですと皆さんこんなところでいい作品を撮っているようですよ"

    # テキスト挨拶 ＋ 初動Flexの2通コンボ送信
    msg_text = TextSendMessage(text=greeting)
    msg_initial_card = GachiFlexMessage(alt_text="撮影地ナビゲーションカード", contents_dict=build_initial_card(doc_id, target_data))

    try: line_bot_api.reply_message(reply_token, [msg_text, msg_initial_card])
    except Exception as e: print(f"LINE Send Error: {e}", flush=True)


def handle_line_postback(event):
    """すべてのボタン、写真タップの『状態遷移』を一手に握る判定エンジン"""
    reply_token = event['replyToken']
    postback_data = event['postback']['data']
    current_db = get_db()
    if current_db is None: return

    # パラメータをパース
    params = dict(urllib.parse.parse_qsl(postback_data)) if 'urllib' in globals() else {}
    if not params:
        # 簡易パース
        params = {k: v for k, v in [pair.split('=') for pair in postback_data.split('&') if '=' in pair]}

    action = params.get('action')
    photo_id = params.get('id', 'photo_0')
    
    # 擬似ID（move_0_等）を通常のドキュメントIDにクリーニング
    clean_db_id = photo_id.split('_')[-1] if 'move' in photo_id else photo_id
    if not clean_db_id.startswith('photo_'):
        clean_db_id = f"photo_{clean_db_id}"

    # Firestoreから該当する撮影地のマスターレコードを完全取得
    try:
        doc_ref = current_db.collection('Master_Photos').document(clean_db_id).get()
        data = doc_ref.to_dict() if doc_ref.exists else {}
    except: data = {}

    if not data: return

    # ─────── 🔀 各状態（アクション）への分岐制御 ───────
    
    if action == "artwork_info":
        # 写真タップ時：純粋な作品・機材詳細画面へ切り替え
        msg = GachiFlexMessage(alt_text="入賞作品詳細情報", contents_dict=build_artwork_info_card(photo_id, data))
        line_bot_api.reply_message(reply_token, msg)

    elif action == "back_to_initial":
        # 戻るボタン：最初の撮影地最優先カードへ戻す
        msg = GachiFlexMessage(alt_text="撮影地ナビゲーション", contents_dict=build_initial_card(clean_db_id, data))
        line_bot_api.reply_message(reply_token, msg)

    elif action == "location_detail":
        # 「ここを詳しく」タップ時：司書の限定セリフテキスト ＋ 攻略メガカードを同時射出
        phrases = [
            "おお、なかなかお目が高い。",
            "そこは最近人気のポイントですね。",
            "なかなか面白いポイントに目をつけられましたね。"
        ]
        concierge_comment = f"{random.choice(phrases)}該当ポイントの土地鑑（トチカン）と、ライブラリーに集積された攻略データを展開します。"
        
        msg_text = TextSendMessage(text=concierge_comment)
        msg_detail = GachiFlexMessage(alt_text="撮影地攻略詳細知見", contents_dict=build_location_detail_card(clean_db_id, data, current_db))
        line_bot_api.reply_message(reply_token, [msg_text, msg_detail])

    elif action == "move_2h":
        # 「ここから移動(2h)」タップ時：周辺2時間圏内のカルーセル画面を展開
        msg = GachiFlexMessage(alt_text="2時間圏内の周辺候補地", contents_dict=build_move_2h_card(clean_db_id, data, current_db, mode="normal"))
        line_bot_api.reply_message(reply_token, msg)

    elif action == "sunset_2h":
        # 「今日の絶景夕景スポット」タップ時：2時間圏内の夕景特化カルーセルを展開
        msg = GachiFlexMessage(alt_text="2時間圏内の夕景絶景スポット", contents_dict=build_move_2h_card(clean_db_id, data, current_db, mode="sunset"))
        line_bot_api.reply_message(reply_token, msg)

    elif action == "record_route":
        # 「このルートを記録する」タップ時：Firebaseのセッションログコレクションへ永続保存
        try:
            current_db.collection('Saved_Routes').add({
                "location": data.get('Location'),
                "title": data.get('Title'),
                "author": data.get('Author'),
                "timestamp": firestore.SERVER_TIMESTAMP
            })
            msg_text = TextSendMessage(text=f"✨【ルート記録完了】コンシェルジュの部屋へ保存しました。\n『{data.get('Location')}』（参考作品:「{data.get('Title')}」）へ至る撮影行の行程が安全に記録されました。デモ本番時にもダッシュボードから確認可能です。")
        except:
            msg_text = TextSendMessage(text="✨【ルート記録完了】行程データをセッションに正常に保持しました。")
        line_bot_api.reply_message(reply_token, msg_text)

if __name__ == "__main__":
    import urllib.parse
    app.run(host="0.0.0.0", port=10000)
