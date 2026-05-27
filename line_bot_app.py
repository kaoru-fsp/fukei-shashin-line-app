import os
import json
import random
import re
import traceback
from datetime import datetime, timedelta
from flask import Flask, request, abort
from linebot import LineBotApi
from linebot.models import TextSendMessage, FlexSendMessage
from google.cloud import firestore
from google.oauth2 import service_account
from collections import Counter

app = Flask(__name__)
IMAGE_BASE_VIEW = "https://fupc.photo/PicsDB/PicsDB4Search"
TOKYO_LAT, TOKYO_LON = 35.6895, 139.6917

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
db_us = None

try:
    firebase_creds_json = os.environ.get('FIREBASE_CREDENTIALS')
    if firebase_creds_json:
        creds_dict = json.loads(firebase_creds_json)
        project_id = creds_dict.get('project_id')
        cred = service_account.Credentials.from_service_account_info(creds_dict)
        db_default = firestore.Client(project=project_id, database='(default)', credentials=cred)
        secondary_db_name = os.environ.get('FIRESTORE_SECONDARY_DB_NAME')
        if secondary_db_name:
            db_us = firestore.Client(project=project_id, database=secondary_db_name, credentials=cred)
except Exception as e:
    print(f"Firebase Init Error: {e}")

def get_shun_index(month, day):
    if day <= 10: d = 1
    elif day <= 20: d = 2
    else: d = 3
    return (month - 1) * 3 + d

def generate_fupc_url(photo_data):
    published = str(photo_data.get('Published', '')).strip()
    pic_file_name = str(photo_data.get('PicFileName', '')).strip()
    if published.endswith('.0'): published = published[:-2]
    if pic_file_name.endswith('.0'): pic_file_name = pic_file_name[:-2]
    
    if published and pic_file_name and len(published) >= 4:
        raw_url = f"{IMAGE_BASE_VIEW}/{published[:4]}/{published}/{pic_file_name}"
        return re.sub(r'(?<!:)/+', '/', raw_url)
    return f"{IMAGE_BASE_VIEW}/default.jpg"

def fetch_photo_by_dnumb(dnumb_value):
    """📸 型のブレ（数値・文字列・.0）を完璧に吸収して写真を一本釣り"""
    if not dnumb_value: return None
    dnumb_str = str(dnumb_value).strip()
    if dnumb_str.endswith('.0'): dnumb_str = dnumb_str[:-2]
    
    search_ids = [dnumb_str]
    try:
        val_int = int(float(dnumb_str))
        search_ids.append(val_int)
        search_ids.append(str(val_int))
    except: pass
    search_ids = list(set(search_ids))
        
    for db_client in [db_default, db_us]:
        if not db_client: continue
        for col in ["photo master", "photo_master"]:
            try:
                query = db_client.collection(col).where('dNumb', 'in', search_ids)
                for doc in query.stream():
                    pdata = doc.to_dict()
                    if pdata: return pdata
            except: continue
    return None

def fetch_guide_by_related_dnumb(dnumb_value):
    """🗺️ 写真の dNumb から、対応する詳細案内を逆引きで一本釣り"""
    if not dnumb_value: return None
    dnumb_str = str(dnumb_value).strip()
    if dnumb_str.endswith('.0'): dnumb_str = dnumb_str[:-2]
    
    search_ids = [dnumb_str]
    try:
        val_int = int(float(dnumb_str))
        search_ids.append(val_int)
        search_ids.append(str(val_int))
    except: pass
    search_ids = list(set(search_ids))

    for db_client in [db_default, db_us]:
        if not db_client: continue
        for col in ["Location master", "Location_master"]:
            try:
                query = db_client.collection(col).where('Related_dNumb', 'in', search_ids)
                for doc in query.stream():
                    gdata = doc.to_dict()
                    if gdata: return gdata
            except: continue
    return None

def get_smart_filtered_pairs(target_date):
    """🎯 15日間窓に合致する「案内＋写真」の有効なペアを最高打順ソートで全回収"""
    if db_default is None: return []
    
    start_date = target_date - timedelta(days=5)
    end_date = target_date + timedelta(days=10)
    
    target_slots = []
    tmp_date = start_date
    while tmp_date <= end_date:
        idx = get_shun_index(tmp_date.month, tmp_date.day)
        if idx not in target_slots: target_slots.append(idx)
        tmp_date += timedelta(days=1)

    raw_guides = []
    for db_client in [db_default, db_us]:
        if not db_client: continue
        for col in ["Location master", "Location_master"]:
            try:
                query = db_client.collection(col).where('PeriodIdx', 'in', target_slots)
                for doc in query.stream():
                    gdata = doc.to_dict()
                    if gdata: raw_guides.append(gdata)
            except: continue

    valid_pairs = []
    for g in raw_guides:
        pdata = fetch_photo_by_dnumb(g.get('Related_dNumb'))
        if not pdata: continue  # 写真が無い案内データは事前に除外
        
        # 🎯 【ハイブリッド・テキストプール】案内と写真のテキストを合算して判定
        loc_pool = (str(g.get('Area', '')) + str(g.get('Place', '')) + str(g.get('Title', '')) + str(g.get('Notes', '')) +
                    str(pdata.get('Title', '')) + str(pdata.get('Place', '')))
        
        if any(x in loc_pool for x in ["台湾", "海外", "中国", "韓国", "アメリカ"]): continue
        if not any(pref in loc_pool for pref in PREFECTURES): continue

        # 優先度スコアリング
        score = 3
        p_month = pdata.get('Month')
        p_day = pdata.get('Day')
        if p_month and p_day:
            try:
                p_date = datetime(target_date.year, int(float(p_month)), int(float(p_day)))
                if start_date <= p_date <= end_date:
                    score = 1
            except: pass
        
        if score == 3:
            g_idx = g.get('PeriodIdx')
            if g_idx and int(float(g_idx)) == get_shun_index(target_date.month, target_date.day):
                score = 2

        g['_priority_score'] = score
        g['_photo_cache'] = pdata
        g['_combined_pool'] = loc_pool
        valid_pairs.append(g)

    valid_pairs.sort(key=lambda x: (x['_priority_score'], random.random()))
    return valid_pairs

def create_ui_buttons(reply_text, choices_list):
    buttons_contents = []
    for item in choices_list:
        buttons_contents.append({
            "type": "button",
            "action": {"type": "message", "label": item["label"][:15], "text": item["text"]},
            "style": "secondary", "margin": "sm"
        })
    return {"type": "bubble", "body": {"type": "box", "layout": "vertical", "spacing": "md", "contents": [{"type": "text", "text": reply_text, "wrap": True, "size": "xl", "color": "#111111", "weight": "bold"}, {"type": "box", "layout": "vertical", "spacing": "xs", "contents": buttons_contents}]}}

def create_preview_carousel(photo1, photo2):
    t1, a1, l1, u1 = photo1.get('Title') or "無題", photo1.get('Winner') or "写真家", photo1.get('Place') or "厳選撮影地", generate_fupc_url(photo1)
    t2, a2, l2, u2 = photo2.get('Title') or "無題", photo2.get('Winner') or "写真家", photo2.get('Place') or "厳選撮影地", generate_fupc_url(photo2)
    
    # 🎯 ボタンの裏の text に、一意の dNumb 識別子を直接仕込む（言葉での再検索を永久撤廃）
    id1 = str(photo1.get('dNumb', '')).split('.')[0]
    id2 = str(photo2.get('dNumb', '')).split('.')[0]
    
    return {
        "type": "carousel",
        "contents": [
            {"type": "bubble", "backgroundColor": "#ffffff", "hero": {"type": "image", "url": u1, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"}, "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [{"type": "text", "text": f"📍 {l1}", "weight": "bold", "size": "xl", "wrap": True, "color": "#111111"}, {"type": "text", "text": f"「{t1}」 (撮影: {a1} 様)", "size": "md", "color": "#444444", "wrap": True}, {"type": "button", "action": {"type": "message", "label": "👉 ここに行く", "text": f"確定移動: dnumb_{id1}"}, "style": "primary", "color": "#1DB954", "margin": "md"}]}},
            {"type": "bubble", "backgroundColor": "#ffffff", "hero": {"type": "image", "url": u2, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"}, "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [{"type": "text", "text": f"📍 {l2}", "weight": "bold", "size": "xl", "wrap": True, "color": "#111111"}, {"type": "text", "text": f"「{t2}」 (撮影: {a2} 様)", "size": "md", "color": "#444444", "wrap": True}, {"type": "button", "action": {"type": "message", "label": "👉 ここに行く", "text": f"確定移動: dnumb_{id2}"}, "style": "primary", "color": "#1DB954", "margin": "md"}]}}
        ]
    }

def create_detail_ui(location, title, author, camera, lens, settings, guide_info, image_url):
    access = guide_info.get('Access') or "現地案内を参照してください。"
    best_time = guide_info.get('BestTime') or "終日"
    light = guide_info.get('Light') or "現場の光線に準ずる"
    filters = guide_info.get('Filter') or "なし"
    notes = guide_info.get('Notes') or ""
    map_url = f"https://www.google.com/maps/search/?api=1&query={location}"
    route_url = f"https://www.google.com/maps/dir/?api=1&origin={TOKYO_LAT},{TOKYO_LON}&destination={location}&travelmode=driving"
    return {
        "type": "bubble", "backgroundColor": "#ffffff", "hero": {"type": "image", "url": image_url, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
        "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "🌸 AIコンシェルジュ撮影ナビ", "weight": "bold", "color": "#1DB954", "size": "md"}, {"type": "text", "text": location, "weight": "bold", "size": "xxl", "margin": "md", "wrap": True}, {"type": "box", "layout": "vertical", "margin": "md", "spacing": "xs", "contents": [{"type": "text", "text": f"作品名: {title} (撮影: {author} 様)", "wrap": True, "color": "#111111", "size": "sm"}, {"type": "text", "text": f"推奨機材: {camera} / {lens}", "wrap": True, "color": "#555555", "size": "sm"}, {"type": "text", "text": f"撮影設定: {settings} / フィルター: {filters}", "wrap": True, "color": "#555555", "size": "sm"}]}, {"type": "separator", "margin": "md"}, {"type": "box", "layout": "vertical", "margin": "md", "spacing": "xs", "contents": [{"type": "text", "text": "🧭 【アクセス・攻略情報】", "weight": "bold", "size": "md", "color": "#111111"}, {"type": "text", "text": f"■ 行き方:\n{access}", "wrap": True, "size": "sm", "color": "#222222", "margin": "xs"}, {"type": "text", "text": f"■ ベスト時間帯: {best_time} / 光線: {light}", "wrap": True, "size": "sm", "color": "#222222"}, {"type": "text", "text": f"■ 注意事項: {notes}" if notes else "", "wrap": True, "size": "sm", "color": "#cc0000"}]}, {"type": "separator", "margin": "md"}, {"type": "box", "layout": "vertical", "margin": "md", "spacing": "sm", "contents": [{"type": "button", "action": {"type": "uri", "label": "🗺️ Googleマップで場所を確認", "uri": map_url}, "style": "secondary"}, {"type": "button", "action": {"type": "uri", "label": "🚗 東京からの高速ルートナビ", "uri": route_url}, "style": "primary", "color": "#1DB954", "margin": "sm"}]}]}
    }

@app.route("/callback", methods=['POST'])
def callback():
    try:
        request_json = request.get_json()
        for event in request_json.get('events', []):
            if event.get('type') == 'message' and event['message'].get('type') == 'text': handle_line_message(event)
    except: print(traceback.format_exc())
    return 'OK', 200

def handle_line_message(event):
    user_id, reply_token, user_message = event['source']['userId'], event['replyToken'], event['message']['text'].strip()
    if db_default is None: return
    
    base_date = datetime(2026, 5, 28)
    target_date = base_date + timedelta(days=1)  # 明日（5月29日）が基本ターゲット窓

    try:
        session_ref = db_default.collection('User_Sessions').document(user_id)
        session_doc = session_ref.get()

        if user_message == "やめる":
            session_ref.delete()
            line_bot_api.reply_message(reply_token, TextSendMessage(text="ご用がありましたらお声がけください。"))
            return
        if user_message == "戻る" and session_doc.exists:
            state = session_doc.to_dict()
            menu_payload = {"type": "flex", "altText": "メニュー", "contents": create_ui_buttons(state.get("menu_text", ""), json.loads(state.get("menu_choices_json", "[]")))}
            line_bot_api.reply_message(reply_token, FlexSendMessage.new_from_json_dict(menu_payload))
            return

        # 🎯 【新・ID一本釣りルート】「ここに行く」が押されたら、再検索せずにIDで100%確実に出す
        if "確定移動: dnumb_" in user_message:
            target_dnumb = user_message.replace("確定移動: dnumb_", "").strip()
            
            target_photo = fetch_photo_by_dnumb(target_dnumb)
            target_guide = fetch_guide_by_related_dnumb(target_dnumb)
            
            if not target_photo or not target_guide:
                 line_bot_api.reply_message(reply_token, TextSendMessage(text="詳細情報の読み込みに失敗しました。データを確認してください。"))
                 return

            location = target_guide.get('Place') or target_photo.get('Place') or "厳選撮影地"
            session_ref.delete()

            title = target_photo.get('Title') or "無題"
            author = target_photo.get('Winner') or "不明"
            camera = target_photo.get('Camera') or "情報なし"
            lens = target_photo.get('Lens') or "情報なし"
            settings = target_photo.get('Exposure') or "情報なし"

            reply_wait_text = f"かしこまりました。では{location}への詳しい行程と撮影ナビをご用意いたします。少々お待ちください。"
            reply_final_text = "こちらでございます。素晴らしい光逢に出会えますように。道中お気をつけてお出かけください！"
            
            detail_payload = {"type": "flex", "altText": "ルート案内", "contents": create_detail_ui(location, title, author, camera, lens, settings, target_guide, generate_fupc_url(target_photo))}
            line_bot_api.reply_message(reply_token, [TextSendMessage(text=reply_wait_text), TextSendMessage(text=reply_final_text), FlexSendMessage.new_from_json_dict(detail_payload)])
            return

        # 〇月指定のパース
        m_match = re.search(r'(\d+)月', user_message)
        if m_match:
            target_date = datetime(2026, int(m_match.group(1)), 15)

        # 最初の提案フェーズ
        if not session_doc.exists or any(k in user_message for k in ["明日", "おすすめ", "お勧め", "撮影"]) or m_match:
            extracted_loc = None
            for k in PREFECTURES:
                if k in user_message: extracted_loc = k; break
            
            pairs = get_smart_filtered_pairs(target_date)
            if extracted_loc:
                pairs = [p for p in pairs if extracted_loc in p['_combined_pool']]
            if not pairs:
                pairs = get_smart_filtered_pairs(target_date)

            photo_keywords = ["新緑", "滝", "富士山", "残雪", "桜", "茶畑", "新幹線", "清流", "海岸", "雲海", "ツツジ", "雪景色", "山焼き", "ナノハナ", "紅葉", "落葉", "冬桜"]
            subjects, point_names = [], []
            for p in pairs:
                pool = p['_combined_pool']
                for kw in photo_keywords:
                    if kw in pool: subjects.append(kw)
                pt = str(p.get('Place', '')).strip()
                if pt and "県" not in pt and pt.lower() not in ["null", "nan", "none"]: point_names.append(pt)

            sub_ranks = [w[0] for w in Counter(subjects).most_common(3) if w[0]]
            point_ranks = [w[0] for w in Counter(point_names).most_common(3) if w[0]]
            if not sub_ranks: sub_ranks = ["風景"]
            if not point_ranks: point_ranks = ["厳選撮影地"]

            sub_top_str = "や".join(sub_ranks[:2]) if len(sub_ranks) >= 2 else sub_ranks[0]
            point_top_str = "や".join(point_ranks[:2]) if len(point_ranks) >= 2 else point_ranks[0]
            
            reply_text = f"お探しの時期におすすめの撮影プランをご案内いたします。\n\nこの季節は{sub_top_str}などの風情ある被写体が絶好のシャッターチャンスを迎えます。名所としては{point_top_str}などが特に美しい表情を見せてくれますが、どちらに興味を惹かれますか？"
            
            choices = []
            for s in sub_ranks[:2]: choices.append({"label": f"📸 被写体: {s}", "text": f"選ぶ被写体: {s}"})
            for p in point_ranks[:2]: choices.append({"label": f"📍 ポイント: {p}", "text": f"選ぶポイント: {p}"})
            choices.append({"label": "❌ やめる", "text": "やめる"})

            session_ref.set({"target_timestamp": target_date.timestamp(), "menu_text": reply_text, "menu_choices_json": json.dumps(choices)})
            line_bot_api.reply_message(reply_token, FlexSendMessage.new_from_json_dict({"type": "flex", "altText": "ご提案", "contents": create_ui_buttons(reply_text, choices)}))
            return

        state = session_doc.to_dict() or {}
        target_date = datetime.fromtimestamp(state.get("target_timestamp", base_date.timestamp()))
        
        # 被写体・ポイントの選択フェーズ
        if "選ぶ被写体:" in user_message or "選ぶポイント:" in user_message:
            word_name = user_message.replace("選ぶ被写体:", "").replace("選ぶポイント:", "").strip()
            
            # 🎯 案内＋写真の合算テキストプールから、選択されたキーワードに合致するペアを抽出
            all_pairs = get_smart_filtered_pairs(target_date)
            matched_pairs = [p for p in all_pairs if word_name in p['_combined_pool']]
            
            if not matched_pairs:
                line_bot_api.reply_message(reply_token, TextSendMessage(text="あいにく条件に合う作品情報が見つかりませんでした。"))
                return
                
            p1 = matched_pairs[0]['_photo_cache']
            p2 = matched_pairs[1]['_photo_cache'] if len(matched_pairs) > 1 else matched_pairs[0]['_photo_cache']
            
            line_bot_api.reply_message(reply_token, FlexSendMessage.new_from_json_dict({"type": "flex", "altText": "作品プレビュー", "contents": create_preview_carousel(p1, p2)}))
            return

    except: print(traceback.format_exc())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
