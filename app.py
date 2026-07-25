# -*- coding: utf-8 -*-
"""
風景写真コンシェルジュ
LINE Bot（Flask / Firestore）。『風景写真』入賞作品データから、
地域・被写体・時期に応じて撮影地を提案する。
被写体検索は KEYWORD_NORMALIZE 辞書＋最長一致。継続開発中。
"""
import os
import json
import sys
import re
import math
import random
import secrets
import urllib.parse
from datetime import date, timedelta
from collections import defaultdict, Counter
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, LocationMessage, PostbackEvent, TextSendMessage, FlexSendMessage, QuickReply, QuickReplyButton, PostbackAction, MessageAction
from linebot.exceptions import InvalidSignatureError
import unicodedata
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

# ──────────────── LINE API 初期化 ────────────────
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ──────────────── Firestore 初期化 ────────────────
db = None
try:
    firebase_creds_json = os.environ.get('FIREBASE_CREDENTIALS')
    if firebase_creds_json:
        creds_dict = json.loads(firebase_creds_json)
        cred = credentials.Certificate(creds_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("[INFO] Firestore initialized.")
except Exception as e:
    print(f"[ERROR] Firestore initialization failed: {e}")

# ──────────────── 心臓部ユーティリティ ────────────────
PREF_LATLNG = {
    "北海道":(43.06,141.35),"青森県":(40.82,140.74),"岩手県":(39.70,141.15),"宮城県":(38.27,140.87),
    "秋田県":(39.72,140.10),"山形県":(38.24,140.36),"福島県":(37.75,140.47),"茨城県":(36.34,140.45),
    "栃木県":(36.57,139.88),"群馬県":(36.39,139.06),"埼玉県":(35.86,139.65),"千葉県":(35.60,140.12),
    "東京都":(35.69,139.69),"神奈川県":(35.45,139.64),"新潟県":(37.90,139.02),"富山県":(36.70,137.21),
    "石川県":(36.59,136.63),"福井県":(36.07,136.22),"山梨県":(35.66,138.57),"長野県":(36.65,138.18),
    "岐阜県":(35.39,136.72),"静岡県":(34.98,138.38),"愛知県":(35.18,136.91),"三重県":(34.73,136.51),
    "滋賀県":(35.00,135.87),"京都府":(35.02,135.76),"大阪府":(34.69,135.52),"兵庫県":(34.69,135.18),
    "奈良県":(34.69,135.83),"和歌山県":(34.23,135.17),"鳥取県":(35.50,134.24),"島根県":(35.47,133.05),
    "岡山県":(34.66,133.93),"広島県":(34.40,132.46),"山口県":(34.19,131.47),"徳島県":(34.07,134.56),
    "香川県":(34.34,134.04),"愛媛県":(33.84,132.77),"高知県":(33.56,133.53),"福岡県":(33.61,130.42),
    "佐賀県":(33.25,130.30),"長崎県":(32.74,129.87),"熊本県":(32.79,130.74),"大分県":(33.24,131.61),
    "宮崎県":(31.91,131.42),"鹿児島県":(31.56,130.56),"沖縄県":(26.21,127.68),
}
GHOST_PREF = {"山内県":"山口県","京都県":"京都府","青山県":"青森県","三重御県":"三重県","金沢県":"神奈川県"}
CITY_PREF = {"京都市":"京都府","南丹市":"京都府","鹿児島":"鹿児島県"}
PREF_RE = re.compile(r'^(北海道|東京都|京都府|大阪府|.{2,3}県)')

AWARD_SCORE = {'最優秀作品賞':100, '優秀作品賞':80, '入選':40, '佳作':30}
SERVER_BASE = "https://fupc.photo/PicsDB"
VIEW_DIR = "PicsDB4Search"

def extract_pref(area):
    if not area:
        return None
    a = str(area).strip()
    for ghost in sorted(GHOST_PREF, key=len, reverse=True):
        if a.startswith(ghost):
            return GHOST_PREF[ghost]
    m = PREF_RE.match(a)
    if m and m.group(1) in PREF_LATLNG:
        return m.group(1)
    for city, pref in CITY_PREF.items():
        if a.startswith(city):
            return pref
    return None

# ──────────────── 市区町村の座標表（オフライン辞書引き）────────────────
# 全国の市区町村→緯度経度。実行時のジオコーディング(API)を避け、距離計算を即時化する。
CITY_LATLNG = {}
CITY_NAMES_BY_PREF = {}
try:
    _cpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'city_latlng.json')
    with open(_cpath, encoding='utf-8') as _f:
        CITY_LATLNG = {k: tuple(v) for k, v in json.load(_f).items()}
    for _key in CITY_LATLNG:
        for _p in PREF_LATLNG:
            if _key.startswith(_p):
                CITY_NAMES_BY_PREF.setdefault(_p, []).append(_key[len(_p):])
                break
    for _p in CITY_NAMES_BY_PREF:
        CITY_NAMES_BY_PREF[_p].sort(key=len, reverse=True)  # 長い名前優先(さいたま市桜区>さいたま市)
    print(f"[INFO] city_latlng loaded: {len(CITY_LATLNG)} municipalities", flush=True)
except Exception as _e:
    print(f"[WARN] city_latlng.json load failed: {_e}", flush=True)

# 全国に複数ある同名の区（中央区・北区など）→ [(正式名, (lat,lng)), ...]。曖昧解決の候補に使う。
WARD_INDEX = {}
try:
    _tmp_w = {}
    for _k, _v in CITY_LATLNG.items():
        if not _k.endswith('区'):
            continue
        _mw = re.search(r'(?:市|郡)([^市郡]*区)$', _k) or re.search(r'(?:都|道|府|県)(.*区)$', _k)
        _w = _mw.group(1) if _mw else _k
        _tmp_w.setdefault(_w, []).append((_k, _v))
    WARD_INDEX = {w: fs for w, fs in _tmp_w.items() if len(fs) >= 2}
    print(f"[INFO] ward index: {len(WARD_INDEX)} ambiguous ward names", flush=True)
except Exception as _e:
    print(f"[WARN] ward index build failed: {_e}", flush=True)

# 現在地が無いときの候補並び順（主要都市の都道府県を上位に）
MAJOR_PREF_ORDER = ['東京都', '大阪府', '愛知県', '北海道', '福岡県', '神奈川県', '京都府', '兵庫県',
                    '埼玉県', '千葉県', '広島県', '宮城県', '新潟県', '静岡県', '岡山県', '熊本県']

SHINJUKU = (35.70044, 139.71827)      # デフォルト起点: 東京都新宿区
DEFAULT_ORIGIN_NAME = "東京都新宿区"

def work_latlng(area, pref=None):
    """作品のArea文字列から市区町村の座標を返す。見つからなければNone（呼び出し側で県重心にフォールバック）。"""
    a = str(area or '').strip()
    if not a:
        return None
    if pref is None:
        pref = extract_pref(a)
    if not pref:
        return None
    rest = (a[len(pref):] if a.startswith(pref) else a).strip()
    for city in CITY_NAMES_BY_PREF.get(pref, ()):
        if city and rest.startswith(city):
            return CITY_LATLNG.get(pref + city)
    # 救済: 市区町村種別が抜けている表記（例: 草津→草津町／みなかみ→みなかみ町）
    head = re.split(r'[\s　0-9０-９]', rest)[0] if rest else ''
    if head:
        for suf in ('市', '町', '村', '区'):
            hit = CITY_LATLNG.get(pref + head + suf)
            if hit:
                return hit
    return None

def format_loc_city(address):
    """LINEの位置情報addressから『県+市区町村』を抽出。失敗時は空文字。"""
    m = re.search(r'([^\s　0-9〒]+?[都道府県])\s*([^\s　0-9]+?[市区町村])', str(address or ''))
    return (m.group(1) + m.group(2)) if m else ''

def junkun(day):
    try:
        d = int(day)
    except:
        return None
    if d <= 10:
        return "上旬"
    if d <= 20:
        return "中旬"
    return "下旬"

def format_period(month, day):
    """撮影時期を ［◯月x旬］ 形式で返す。日があれば上/中/下旬に変換、月のみなら旬を省略。"""
    try:
        m = int(month)
    except:
        return ''
    jun = junkun(day)  # 上旬/中旬/下旬 or None
    return f"［{m}月{jun}］" if jun else f"［{m}月］"

JUN_LABELS = ['上旬', '中旬', '下旬']
# 「見頃」という表現が自然な季節被写体（花・季節現象）
SEASONAL_SUBJECTS = {'桜', '紅葉', '雪', 'ひまわり', 'コスモス', 'ススキ', '紫陽花', '菜の花', '芝桜', '藤', 'ラベンダー'}
# 撮影意図を表すだけで、被写体でも地名でもない語（検索ワードから除く。長い語を先に並べる）
FILLER_WORDS = ['撮り頃', '撮りごろ', '撮影地', '撮影', '見頃', 'みごろ', '写真', 'スポット', '撮れる', '撮りたい', '撮る', '行きたい', '行ける',
                '探して', '探す', '教えて', 'おすすめ', 'オススメ', '名所', '風景', '景色', 'ください',
                'どこ', '場所']

# 参考撮影地の辞書（『風景写真』入賞作品としては少ない／無いが、撮影地として広く知られる場所）。
# ※運用側で認めた場所のみを掲載する方針。流行に応じて随時点検・追加する。
# subject は KEYWORD_NORMALIZE の正規名に合わせる。query は Googleマップ検索に使う文字列。
# season は表示用の見頃（無ければ空文字）。lat/lng は近い順の判定に使う（任意）。
FAMOUS_SPOTS = [
    {"name": "河津桜（静岡県河津町）", "query": "河津桜 静岡県河津町", "subject": "桜",
     "pref": "静岡県", "names": ["河津", "河津桜"], "season": "2月中旬〜3月上旬", "months": {2, 3}, "lat": 34.7449, "lng": 138.9534},
    {"name": "三春滝桜（福島県三春町）", "query": "三春滝桜 福島県三春町", "subject": "桜",
     "pref": "福島県", "names": ["三春", "滝桜", "三春滝桜"], "season": "4月中旬", "months": {4}, "lat": 37.4439, "lng": 140.4906},
    {"name": "高遠城址公園（長野県伊那市）", "query": "高遠城址公園 桜", "subject": "桜",
     "pref": "長野県", "names": ["高遠"], "season": "4月上旬〜中旬", "months": {4}, "lat": 35.8339, "lng": 138.0617},
    {"name": "あしかがフラワーパークの大藤（栃木県足利市）", "query": "あしかがフラワーパーク 藤", "subject": "藤",
     "pref": "栃木県", "names": ["あしかが", "足利", "フラワーパーク"], "season": "4月下旬〜5月上旬", "months": {4, 5}, "lat": 36.3146, "lng": 139.5206},
    {"name": "上高地（長野県松本市）", "query": "上高地 長野県松本市", "subject": None,
     "pref": "長野県", "names": ["上高地"], "season": "新緑6月・紅葉10月中旬", "months": {4, 5, 6, 7, 8, 9, 10, 11}, "lat": 36.2506, "lng": 137.6319,
     "closed_note": "上高地は冬期は閉山中です。入山には冬山装備と相応の経験が必要なため、最新の入山・アクセス情報を必ずご確認ください。"},
    {"name": "国営ひたち海浜公園 ネモフィラ（茨城県ひたちなか市）", "query": "国営ひたち海浜公園 ネモフィラ", "subject": "ネモフィラ",
     "pref": "茨城県", "names": ["ひたち海浜", "ネモフィラ"], "season": "4月中旬〜5月上旬", "months": {4, 5}, "lat": 36.4017, "lng": 140.5928},
    {"name": "富士芝桜まつり（山梨県富士河口湖町）", "query": "富士本栖湖リゾート 芝桜", "subject": "芝桜",
     "pref": "山梨県", "names": ["本栖", "富士芝桜"], "season": "4月中旬〜5月下旬", "months": {4, 5}, "lat": 35.4530, "lng": 138.5870},
]


def gmaps_link(query):
    """Googleマップの検索リンクを作る（アプリが無くてもブラウザで開ける）。"""
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(query)


def pick_famous_spots(subject=None, region_text=None, origin_latlng=None, base_date=None, limit=3):
    """被写体や地域に合う参考撮影地を選ぶ。被写体一致 or 地域/名称一致のものだけを対象にし、
    今が見頃のもの・近いものを優先して最大limit件返す。該当が無ければ空リスト。"""
    region_text = region_text or ''
    region_core = re.sub(r'[都道府県市区町村郡]', '', region_text)
    cur_month = base_date.month if base_date else date.today().month
    scored = []
    for sp in FAMOUS_SPOTS:
        # 撮り頃(出してよい月)から外れた参考スポットは出さない。例: 河津桜(2〜3月)は6月には出さない。
        sp_months = sp.get("months")
        if sp_months and cur_month not in sp_months:
            continue
        subj_match = bool(subject) and sp.get("subject") == subject
        reg_match = False
        if region_text:
            if sp.get("pref") and (sp["pref"] in region_text or sp["pref"].rstrip('都道府県') in region_text):
                reg_match = True
            for nm in sp.get("names", []):
                if nm and (nm in region_text or (region_core and (nm in region_core or region_core in nm))):
                    reg_match = True
                    break
        if not (subj_match or reg_match):
            continue
        score = 0
        if subj_match and reg_match:
            score += 100
        elif reg_match:
            score += 60
        elif subj_match:
            score += 40
        if origin_latlng and sp.get("lat") is not None:
            d = haversine(origin_latlng[0], origin_latlng[1], sp["lat"], sp["lng"])
            score -= d / 1000.0  # 近いほど僅かに優先
        scored.append((score, sp))
    scored.sort(key=lambda x: -x[0])
    return [sp for _, sp in scored[:limit]]


def famous_spots_note(subject=None, region_text=None, origin_latlng=None, base_date=None, limit=3):
    """参考撮影地のテキスト（Googleマップのリンク付き）を返す。該当が無ければ None。
    LINEのリンクプレビューは1メッセージにつき最後の1件しか展開されず、複数URLだと
    どの場所か分からない汎用表示になってしまうため、最も近い(または最優先の)1件だけを出す。"""
    spots = pick_famous_spots(subject, region_text, origin_latlng, base_date, limit=1)
    if not spots:
        return None
    sp = spots[0]
    season = f"／撮り頃 {sp['season']}" if sp.get("season") else ""
    return ("参考までに、撮影地として知られている場所です（『風景写真』の入賞作品ではありません）。\n"
            f"・{sp['name']}{season}\n{gmaps_link(sp['query'])}")


def _spot_name_in(text, sp):
    """text に スポット名(names) が含まれるか。県名一致は対象外（ノイズ防止）。"""
    if not text:
        return False
    core = re.sub(r'[都道府県市区町村郡]', '', text)
    for nm in sp.get("names", []):
        if nm and (nm in text or (core and (nm in core or core in nm))):
            return True
    return False


def closed_spot_caution(region_text=None, results=None, base_date=None):
    """指定地（region_text）またはカルーセル結果(results)の撮影地が、開放月(months)の外の
    有名スポットに該当するとき、軽い注意書き(※…)を返す。該当しなければ ''。
    閉山注記(closed_note)を持つスポットのみ対象。一致はスポット名のみ。
    『能動的おすすめでは閉山地を出さない／明示検索では正直に出すが注意を添える』の後者を担う。"""
    if not base_date:
        return ''
    cur_month = base_date.month
    res_texts = []
    for it in (results or []):
        doc = it[2] if isinstance(it, (list, tuple)) and len(it) >= 3 else it
        if isinstance(doc, dict):
            res_texts.append(f"{doc.get('place', '')} {doc.get('area', '')}")
    for sp in FAMOUS_SPOTS:
        note = sp.get("closed_note"); months = sp.get("months")
        if not note or not months or cur_month in months:
            continue  # 注記が無い/開放月のときは何もしない
        if _spot_name_in(region_text, sp) or any(_spot_name_in(t, sp) for t in res_texts):
            return f"※{note}"
    return ''

def _jun_offset(day):
    return {'上旬': 0, '中旬': 1, '下旬': 2}.get(junkun(day), 1)  # 日不明は中旬扱い

def bin_index(month, day):
    return (int(month) - 1) * 3 + _jun_offset(day)

def bin_label(idx):
    return f"{idx // 3 + 1}月{JUN_LABELS[idx % 3]}"

def compute_peaks(bin_counter, min_count=3, max_peaks=2):
    """旬(上中下)単位のヒストグラムから見頃を検出。
    3旬(≈1か月)のローリング窓で点数が min_count 以上集中している中心を、重複を避けて上位 max_peaks 件返す。
    戻り値: 中心の旬インデックス(0..35)のリスト。基準を満たすものが無ければ空。"""
    if not bin_counter:
        return []
    wins = sorted(((c, sum(bin_counter.get((c + o) % 36, 0) for o in (-1, 0, 1))) for c in range(36)),
                  key=lambda x: -x[1])
    peaks, used, first_tot = [], set(), None
    for c, tot in wins:
        if tot < min_count:
            break
        if first_tot is not None and tot < first_tot * 0.34:
            break  # 一番手に比べて弱いピークは見頃と見なさない(冬桜など少数の別季節を除外)
        if c in used:
            continue
        if first_tot is None:
            first_tot = tot
        peaks.append(c)
        for o in range(-4, 5):   # 採用したピークの前後約1.3か月を除外(隣接旬の重複・尾引きを防ぐ)
            used.add((c + o) % 36)
        if len(peaks) >= max_peaks:
            break
    return peaks

def peaks_text(peaks):
    return "・".join(bin_label(c) for c in peaks)

def next_peak_date(peak_bins, today=None):
    """撮り頃ビン(0..35)のうち、今日から見て最も近い未来の旬を選び、
    その代表日(date)と旬ラベル(例『4月中旬』)を返す。該当が無ければ (None, None)。
    『撮り頃で探す』が複数撮り頃のとき"次に近い"へ飛ぶための選定に使う。"""
    today = today or date.today()
    rep = {0: 5, 1: 15, 2: 25}  # 上旬/中旬/下旬の代表日
    best = None
    for b in (peak_bins or []):
        mo = b // 3 + 1
        day = rep[b % 3]
        try:
            d = date(today.year, mo, day)
        except ValueError:
            continue
        if d < today:  # 今年その旬を過ぎていれば来年へ
            try:
                d = date(today.year + 1, mo, day)
            except ValueError:
                continue
        if best is None or d < best[0]:
            best = (d, b)
    if best is None:
        return (None, None)
    return (best[0], bin_label(best[1]))

def peak_reason_text(scope_label, subject, speaks):
    """季節もの×季節外れのときの根拠つき一文を返す。speaks が空なら ''。
    例: scope_label='ちなみに「京都」' → 「ちなみに「京都」では紅葉の入賞作品が
    11月下旬ごろにピークとなることから、この頃が撮り頃と思われます。」
    複数撮り頃はそのまま列挙する（行き先のボタンは"次に近い"1つ）。"""
    if not speaks:
        return ''
    return (f"{scope_label}では{subject}の入賞作品が{peaks_text(speaks)}ごろに"
            f"ピークとなることから、この頃が撮り頃と思われます。")

def time_widen_empty_actions(pterms, base_date, ol, on, subject, center_latlng=None, radius_km=None):
    """off_season時の軽量先読み(検索1回)。期間を広げても in_season の作品が出ない
    （＝その時期に実質作品が無い）なら ['time'] を返す。時期が近づけば自然に空[]になる。
    area/both は全国フォールバックで0にならないため対象外（軽量運用）。"""
    kw = dict(base_date=base_date, origin_latlng=ol, origin_name=on, subject=subject, expand_time=True)
    if center_latlng is not None:
        kw['center_latlng'] = center_latlng
        kw['radius_km'] = radius_km
    pf = search_by_place(pterms or [], **kw)
    return ['time'] if pf.get('status') != 'in_season' else []

def haversine(lat1, lng1, lat2, lng2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    h = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlmb/2)**2
    return 2 * R * math.asin(math.sqrt(h))

def half_month_window(base_date, expand=False):
    pairs = set()
    lo, hi = (-45, 46) if expand else (-7, 14)  # expand=「期間を広げる」: 前後およそ1.5か月
    for delta in range(lo, hi):
        d = base_date + timedelta(days=delta)
        pairs.add((d.month, junkun(d.day)))
    return pairs

def view_image_url(published, pic_filename):
    return "/".join([SERVER_BASE, VIEW_DIR, str(published)[:4], str(published), str(pic_filename)])

def has_valid_image(pic_filename):
    fn = str(pic_filename or '').strip()
    return fn and fn not in ('なし.jpg', 'default.jpg', 'なし', 'none', '')

# ── 壊れた画像(サーバに実体が無い/エラーページ)の除外 ──
VERIFY_IMAGES = True          # 問題があれば False で無効化
_IMG_OK_CACHE = {}            # url -> bool (このプロセス内キャッシュ)

def image_available(url, timeout=2.5):
    """画像URLが実在し画像として返るかを保守的に判定。判定不能なら True(表示維持)。"""
    if not url:
        return False
    if url in _IMG_OK_CACHE:
        return _IMG_OK_CACHE[url]
    ok = True
    try:
        import urllib.request, urllib.error
        req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ct = (r.headers.get('Content-Type') or '').lower()
            # Content-Typeが分かる場合のみ判定。画像でなければ壊れ扱い。不明なら表示維持。
            if ct and not ct.startswith('image'):
                ok = False
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):   # 明確に存在しない場合のみ除外
            ok = False
    except Exception:
        ok = True                  # ネットワーク不調等は表示を維持
    _IMG_OK_CACHE[url] = ok
    return ok

def filter_broken_images(results, max_workers=8):
    """(emoji,label,item) のリストから、画像が壊れている候補を除外して返す。"""
    if not VERIFY_IMAGES or not results:
        return results
    try:
        from concurrent.futures import ThreadPoolExecutor
        urls = [it.get('url') for _, _, it in results]
        with ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as ex:
            oks = list(ex.map(image_available, urls))
        return [r for r, ok in zip(results, oks) if ok]
    except Exception:
        return results  # 判定処理自体が失敗したら従来どおり全件表示

def subject_matches(variants, title='', place='', area='', subject_field='', exclude=None):
    """被写体語が作品に該当するか判定。
    Subject/タイトル一致は確実。地名・エリアでは複合地名(瀧谷・滝沢・滝川など)の
    誤ヒットを避けるため、被写体語の直後がCJK文字でない(=地名の途中でない)場合のみ採用。
    exclude を渡すと、その語を各フィールドから先に除去してから判定する。
    例: 鳥カテゴリで exclude=['鳥居','鳥海山'] とすると、Subjectの「鳥居」由来の"鳥"を
    誤ヒットさせない（「桜 鳥居」→「桜   」となり鳥は残らない。「白鳥 鳥居」→「白鳥   」で
    白鳥は別variantで拾える）。"""
    title = str(title or ''); place = str(place or ''); area = str(area or ''); subject_field = str(subject_field or '')
    if exclude:
        for ex in exclude:
            if not ex:
                continue
            subject_field = subject_field.replace(ex, ' ')
            title = title.replace(ex, ' ')
            place = place.replace(ex, ' ')
            area = area.replace(ex, ' ')
    for v in variants:
        if v and (v in subject_field or v in title):
            return True
    for fld in (place, area):
        for v in variants:
            if not v:
                continue
            for m in re.finditer(re.escape(v), fld):
                nxt = fld[m.end():m.end() + 1]
                if not nxt or not re.match(r'[ぁ-んァ-ヶ一-龥ー]', nxt):
                    return True
    return False

def calc_award_score(award_rank):
    r = str(award_rank or '').strip()
    for k, v in AWARD_SCORE.items():
        if k in r:
            return v
    return 10 if r else 0

def load_exclusions():
    authors = set()
    blocked = []
    today = date.today().isoformat()
    try:
        doc = db.collection('settings').document('excluded_authors').get()
        if doc.exists:
            authors = set(doc.to_dict().get('names', []))
    except:
        pass
    try:
        doc = db.collection('settings').document('blocked_areas').get()
        if doc.exists:
            for item in doc.to_dict().get('items', []):
                if item.get('until', '9999') >= today:
                    blocked.append(item.get('match', ''))
    except:
        pass
    return authors, [b for b in blocked if b]

def is_area_blocked(place, area, blocked_list):
    if not blocked_list:
        return False
    s = str(place or '') + ' ' + str(area or '')
    return any(b and b in s for b in blocked_list)



# ──────────────── Google Geocoding API ────────────────
GEOCODING_API_KEY = os.environ.get('GOOGLE_GEOCODING_API_KEY')
GEOCODE_CACHE = {}

def geocode(place_name):
    if place_name in GEOCODE_CACHE:
        return GEOCODE_CACHE[place_name]
    if not GEOCODING_API_KEY:
        return None
    try:
        import urllib.request
        from urllib.parse import quote
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={quote(place_name)}&language=ja&key={GEOCODING_API_KEY}"
        with urllib.request.urlopen(url, timeout=3) as res:
            data = json.loads(res.read())
        if data['status'] == 'OK':
            loc = data['results'][0]['geometry']['location']
            result = (loc['lat'], loc['lng'])
            GEOCODE_CACHE[place_name] = result
            return result
    except Exception as e:
        print(f"[WARN] Geocoding failed for {place_name}: {e}")
    return None

# ──────────────── メッセージ解析 ────────────────
CITY_TO_PREF = {}
CITY_TO_LATLNG = {}
CITY_TO_PREF_MULTI = {}
AMBIGUOUS_PENDING = {}
EXPAND_PENDING = {}  # 検索拡張待ち  # user_id -> {"city": "小国町", "prefs": ["熊本県", "山形県"]}
SUBJECT_PENDING = {}  # 地域＋被写体が0件のときの選択待ち
RESULT_PENDING = {}  # 件数分岐の統一メニュー待ち  # user_id -> {kind, options, subject, place_terms, ...}
ROUTE_PENDING = {}  # tコマンドで目的地が未確定のときの入力待ち  # user_id -> {center,center_nm,subject,radius}
WARD_PENDING = {}  # 同名の区(中央区など)の選択待ち  # user_id -> {cands,mode,center,...}
USER_LOCATION = {}  # user_id -> {"lat": 35.xxx, "lng": 139.xxx}
USER_HOME = {}  # user_id -> {"lat":.., "lng":.., "name": "..."}  自宅(帰路の基準点)
USER_SEEN = set()  # 初回メッセージ済みuser_id

# ── ユーザー情報(位置・初回フラグ)のFirestore永続化 ──
# メモリ上の USER_LOCATION / USER_SEEN は再起動で消えるため、
# Firestoreの Users コレクション(doc id = user_id)に読み書きして永続化する。
# 書き込みは「メモリ＋Firestore」両方、読み込みは初回だけFirestoreから復元(以後はメモリ)。
_HYDRATED = set()  # このプロセスで既にFirestoreから読み込み済みのuser_id

def hydrate_user(user_id):
    """初回アクセス時にFirestoreからユーザー情報を読み、メモリに復元する。"""
    if user_id in _HYDRATED:
        return
    _HYDRATED.add(user_id)
    if not db:
        return
    try:
        snap = db.collection('Users').document(user_id).get()
        if snap.exists:
            data = snap.to_dict() or {}
            if data.get('seen'):
                USER_SEEN.add(user_id)
            if data.get('lat') is not None and data.get('lng') is not None:
                USER_LOCATION[user_id] = {"lat": data['lat'], "lng": data['lng'], "city": data.get('city', '')}
            if data.get('home_lat') is not None and data.get('home_lng') is not None:
                USER_HOME[user_id] = {"lat": data['home_lat'], "lng": data['home_lng'], "name": data.get('home_name', '')}
    except Exception:
        import traceback
        print(f"[ERROR] hydrate_user failed: {traceback.format_exc()}", flush=True)

def save_user_home(user_id, lat, lng, name=None):
    """自宅(帰路の基準点)をメモリとFirestoreの両方に保存する。"""
    USER_HOME[user_id] = {"lat": lat, "lng": lng, "name": name or ''}
    if not db:
        return
    try:
        payload = {"home_lat": lat, "home_lng": lng, "updated": firestore.SERVER_TIMESTAMP}
        if name:
            payload["home_name"] = name
        db.collection('Users').document(user_id).set(payload, merge=True)
    except Exception:
        import traceback
        print(f"[ERROR] save_user_home failed: {traceback.format_exc()}", flush=True)

def save_user_location(user_id, lat, lng, city=None):
    """位置情報をメモリとFirestoreの両方に保存する。"""
    USER_LOCATION[user_id] = {"lat": lat, "lng": lng, "city": city or ''}
    if not db:
        return
    try:
        payload = {"lat": lat, "lng": lng, "updated": firestore.SERVER_TIMESTAMP}
        if city:
            payload["city"] = city
        db.collection('Users').document(user_id).set(payload, merge=True)
    except Exception:
        import traceback
        print(f"[ERROR] save_user_location failed: {traceback.format_exc()}", flush=True)

def mark_user_seen(user_id):
    """初回フラグをメモリとFirestoreの両方に立てる。"""
    USER_SEEN.add(user_id)
    if not db:
        return
    try:
        db.collection('Users').document(user_id).set(
            {"seen": True, "updated": firestore.SERVER_TIMESTAMP},
            merge=True,
        )
    except Exception:
        import traceback
        print(f"[ERROR] mark_user_seen failed: {traceback.format_exc()}", flush=True)

def record_search(user_id, query):
    """利用状況の観察用。検索回数と最終利用日時を更新し、検索内容を記録する。
    テスト公開中は上限などの制限はかけず、数えて記録するだけ。"""
    if not db:
        return
    try:
        db.collection('Users').document(user_id).set(
            {"search_count": firestore.Increment(1),
             "last_used": firestore.SERVER_TIMESTAMP,
             "last_query": query},
            merge=True,
        )
        db.collection('SearchLogs').add(
            {"user_id": user_id, "query": query, "ts": firestore.SERVER_TIMESTAMP}
        )
    except Exception:
        import traceback
        print(f"[ERROR] record_search failed: {traceback.format_exc()}", flush=True)

def feedback_quick_reply():
    """検索結果に対する満足度フィードバックのクイックリプライ(タップ式)。"""
    return QuickReply(items=[
        QuickReplyButton(action=PostbackAction(
            label="👍 ちょうど良い", data="action=feedback&rating=good", display_text="ちょうど良い")),
        QuickReplyButton(action=PostbackAction(
            label="🤔 ピンとこない", data="action=feedback&rating=meh", display_text="ピンとこない")),
        QuickReplyButton(action=PostbackAction(
            label="📍 場所に違和感", data="action=feedback&rating=place", display_text="場所に違和感")),
    ])

def delete_user_data(user_id):
    """ユーザー本人の記録(Users / SearchLogs / Feedback)をすべて削除する。同意撤回・削除依頼用。"""
    # メモリ上の状態もクリア
    USER_LOCATION.pop(user_id, None)
    USER_SEEN.discard(user_id)
    _HYDRATED.discard(user_id)
    if not db:
        return
    try:
        db.collection('Users').document(user_id).delete()
        for coll in ('SearchLogs', 'Feedback'):
            for d in db.collection(coll).where('user_id', '==', user_id).stream():
                d.reference.delete()
    except Exception:
        import traceback
        print(f"[ERROR] delete_user_data failed: {traceback.format_exc()}", flush=True)

def usage_guide_messages():
    """初回案内・「使い方」コマンドで表示する使い方ガイド。
    読みやすいよう話題ごとに分割したメッセージのリストを返す(最大5通)。"""
    return [
        (
            "【使い方】\n"
            "行きたい「地域」「被写体」「日付」を送ると、『風景写真』の傑作が撮られた撮影地をご提案します。\n"
            "\n"
            "▼送り方の例\n"
            "・地域で探す：栃木県／美瑛／箱根\n"
            "・被写体で探す：滝／桜／紅葉／星空／海／雲海／水田／鳥\n"
            "・日付を添える：週末 京都／明日 滝／3日後\n"
            "\n"
            "▼地名がうまく伝わらないとき\n"
            "頭に「@」を付けると、その語を必ず地名として探します。\n"
            "例：@川越／@海老名／@中央区"
        ),
        (
            "▼使える日付の言い方\n"
            "明日・明後日・今週末・来週末・3日後・6月15日 など\n"
            "（指定しない場合は今の時期に合わせてご提案します)"
        ),
        (
            "▼位置情報を登録すると\n"
            "地域を指定しなくても、今いる場所の近くからご提案します。\n"
            "\n"
            "【登録方法】このトーク画面で位置情報を送るだけです。\n"
            "1. 入力欄の左の「＋」をタップ\n"
            "2. メニューから「位置情報」を選ぶ\n"
            "3. 地図で場所を指定(現在地のまま／検索／地図を動かして調整)\n"
            "4. 右上の「送信」をタップ\n"
            "詳しい解説→ https://guide.line.me/ja/services/location-information.html"
        ),
        (
            "ご提案の下に出るボタンで感想(ちょうど良い／ピンとこない／場所に違和感)を教えていただけると、今後の精度向上に役立ちます。\n"
            "\n"
            "この説明は「使い方」と送るといつでも表示できます。"
        ),
    ]

def command_list_text():
    """「コマンド」で表示するコマンド一覧と用例。"""
    return (
        "【コマンド一覧】\n"
        "\n"
        "■ 基本の探し方（そのまま送る）\n"
        "・地域：栃木県／美瑛／箱根\n"
        "・被写体：滝／桜／紅葉／星空／海／雲海／水田／鳥\n"
        "・地域＋被写体：栃木県 紅葉\n"
        "・日付を添える：週末 京都／明日 滝／3日後\n"
        "（日付を言わなければ今の時期でご提案）\n"
        "\n"
        "■ @地名（必ず地名として探す）\n"
        "・例：@川越／@海老名／@中央区\n"
        "・地名が被写体と紛れるときや、見つかりにくい地名に\n"
        "\n"
        "■ 半径を指定する\n"
        "・地名や被写体の後ろに数字（km）：美瑛150／滝80\n"
        "\n"
        "■ 現在地から探す（位置情報の送信が必要）\n"
        "・<被写体>現在地<半径>：アジサイ現在地100\n"
        "・撮り頃<半径>：撮り頃150（今が撮り頃の被写体一覧）\n"
        "・位置情報を送ると、地域を言わなくても近くからご提案\n"
        "\n"
        "■ 道中・帰り道で探す\n"
        "・自宅を登録：自宅 川越市\n"
        "・帰り道：茅野r／現在地r150（r＝登録した自宅へ）\n"
        "・r<地名>：r板橋区（その地名を自宅に登録し、今回もそこへ）\n"
        "・目的地へ：茅野t函館市（t＝その場限りの目的地）\n"
        "\n"
        "■ その他\n"
        "・使い方／ヘルプ：使い方ガイド\n"
        "・データ削除：記録の消去\n"
        "・コマンド：この一覧"
    )

KEYWORD_NORMALIZE = {
    '滝': ['滝', '瀧', 'たき', 'タキ'],
    '桜': ['桜', '櫻', 'さくら', 'サクラ', '桜花'],
    '紅葉': ['紅葉', 'もみじ', 'モミジ', '紅葉狩り'],
    '雪': ['雪', 'ゆき', '積雪', '雪景色', '吹雪'],
    '富士': ['富士', '富士山', 'ふじさん', 'Mt.Fuji'],
    '棚田': ['棚田', 'たなだ', '千枚田'],
    '水田': ['水田', '田んぼ', '田園', '稲穂', '稲田', '青田', '田面'],
    '海': ['海', '海岸', '海辺', 'うみ', '波'],
    '湖': ['湖', 'みずうみ', '池', '沼'],
    '川': ['川', '河川', '渓流', '河原'],
    '渓谷': ['渓谷', '谷', '峡谷'],
    '朝焼け': ['朝焼け', '朝焼', '夜明け', '日の出'],
    '夕焼け': ['夕焼け', '夕焼', '夕日', '日没', 'サンセット'],
    '星': ['星', '星空', '天体', '星景'],
    '天の川': ['天の川', '天の川', '銀河'],
    '霧': ['霧', '霞', '靄', 'きり', '朝霧', '朝靄', '川霧', '海霧'],
    '雲海': ['雲海', '滝雲'],
    '氷': ['氷', '霜', '結氷', '氷点', 'つらら'],
    'ひまわり': ['ひまわり', 'ヒマワリ', '向日葵'],
    'コスモス': ['コスモス', 'こすもす', '秋桜'],
    'ススキ': ['ススキ', 'すすき', '薄'],
    '紫陽花': ['紫陽花', 'あじさい', 'アジサイ'],
    '菜の花': ['菜の花', 'なのはな', '菜花', '菜の花畑'],
    '芝桜': ['芝桜', 'しばざくら'],
    '藤': ['藤', 'ふじ', '藤の花'],
    'ラベンダー': ['ラベンダー', 'らべんだー'],
    '鉄道': ['鉄道', '列車', '電車', '汽車', 'SL', '蒸気機関車', 'ローカル線'],
    '灯台': ['灯台', 'とうだい'],
    '城': ['城', 'お城', '城郭'],
    '鳥居': ['鳥居'],
    '神社': ['神社', '神宮', '社', '鳥居'],
    '寺': ['寺', 'お寺', '寺院', '仏閣'],
    '白鳥': ['白鳥', 'はくちょう', 'スワン'],
    'タンチョウ': ['タンチョウ', 'たんちょう', '丹頂', '鶴'],
    '鳥': ['鳥', '野鳥', '水鳥', '海鳥', '小鳥', 'サギ', 'シラサギ', 'アオサギ', 'ダイサギ', 'コサギ', '白鷺', 'カモ', '鴨', 'カモメ', '雁', '鷺'],
    'ツツジ': ['ツツジ', 'つつじ', '躑躅', 'ミヤマキリシマ', 'アケボノツツジ', 'イワツツジ', 'シャクナゲ', 'しゃくなげ'],
}

# カテゴリ別の除外語。作品データのSubject/Title等で、被写体variantを部分文字列として含むが
# その被写体ではない語を、判定前に各フィールドから除去する（subject_matchesのexclude引数へ渡す）。
# 例: 「鳥」は「鳥居」(神社)「鳥海山」「鳥甲山」(山名)の一部として現れるため、鳥の野鳥判定から外す。
SUBJECT_EXCLUDE = {
    '鳥': ['鳥居', '鳥海山', '鳥甲山', '害鳥'],
}

def subject_exclude_for(canon):
    """正規キーに対応する除外語リストを返す（無ければ空リスト）。"""
    return SUBJECT_EXCLUDE.get(canon, [])

def detect_subject_longest(text):
    """text に含まれる被写体variantのうち最長一致の正規名を返す（該当なしはNone）。
    辞書の定義順ではなく一致した語の長さで決めるため、「雲海」が「海」(1字)ではなく
    「雲海」(2字→霧)として、「天の川」が「川」ではなく「天の川」として正しく解決される。
    同長で複数一致した場合は辞書の定義順（先勝ち）を保つ。"""
    if not text:
        return None
    best_canon, best_len = None, 0
    for canon, variants in KEYWORD_NORMALIZE.items():
        for v in variants:
            if v and v in text and len(v) > best_len:
                best_canon, best_len = canon, len(v)
    return best_canon

def detect_subject_longest_variant(text):
    """detect_subject_longest と同じ最長一致で、(正規名, 一致した実variant) を返す。
    実variantは呼び出し側で text から除去する用途（extract_subject）に使う。該当なしは (None, None)。"""
    if not text:
        return None, None
    best_canon, best_var, best_len = None, None, 0
    for canon, variants in KEYWORD_NORMALIZE.items():
        for v in variants:
            if v and v in text and len(v) > best_len:
                best_canon, best_var, best_len = canon, v, len(v)
    return best_canon, best_var

WIDE_PREFS = {"北海道", "長野県", "岩手県", "新潟県"}
PREF_CITY = {
    "北海道":"札幌","青森県":"青森市","岩手県":"盛岡市","宮城県":"仙台市",
    "秋田県":"秋田市","山形県":"山形市","福島県":"福島市","茨城県":"水戸市",
    "栃木県":"宇都宮市","群馬県":"前橋市","埼玉県":"さいたま市","千葉県":"千葉市",
    "東京都":"新宿","神奈川県":"横浜市","新潟県":"新潟市","富山県":"富山市",
    "石川県":"金沢市","福井県":"福井市","山梨県":"甲府市","長野県":"長野市",
    "岐阜県":"岐阜市","静岡県":"静岡市","愛知県":"名古屋市","三重県":"津市",
    "滋賀県":"大津市","京都府":"京都市","大阪府":"大阪市","兵庫県":"神戸市",
    "奈良県":"奈良市","和歌山県":"和歌山市","鳥取県":"鳥取市","島根県":"松江市",
    "岡山県":"岡山市","広島県":"広島市","山口県":"山口市","徳島県":"徳島市",
    "香川県":"高松市","愛媛県":"松山市","高知県":"高知市","福岡県":"福岡市",
    "佐賀県":"佐賀市","長崎県":"長崎市","熊本県":"熊本市","大分県":"大分市",
    "宮崎県":"宮崎市","鹿児島県":"鹿児島市","沖縄県":"那覇市",
}

# 県名の略称と同名の「市」が実在する都道府県（地名としての実在で判定。作品データの有無は問わない）。
# 単独で略称が送られたとき(例「静岡」)、まず市で答えてから県・隣県へ広げる「狭→広」のために使う。
PREF_SAME_NAME_CITY = {
    "青森県": "青森市", "秋田県": "秋田市", "山形県": "山形市", "福島県": "福島市",
    "栃木県": "栃木市", "千葉県": "千葉市", "新潟県": "新潟市", "富山県": "富山市",
    "福井県": "福井市", "山梨県": "山梨市", "長野県": "長野市", "岐阜県": "岐阜市",
    "静岡県": "静岡市", "京都府": "京都市", "大阪府": "大阪市", "奈良県": "奈良市",
    "和歌山県": "和歌山市", "鳥取県": "鳥取市", "岡山県": "岡山市", "広島県": "広島市",
    "山口県": "山口市", "徳島県": "徳島市", "高知県": "高知市", "福岡県": "福岡市",
    "佐賀県": "佐賀市", "長崎県": "長崎市", "熊本県": "熊本市", "大分県": "大分市",
    "宮崎県": "宮崎市", "鹿児島県": "鹿児島市", "沖縄県": "沖縄市",
}

# 陸続きで隣接する都道府県（県検索を「県内→隣県」に広げるための表）。海上のみで接する組合せは含めない。
PREF_NEIGHBORS = {
    "北海道": [],
    "青森県": ["岩手県", "秋田県"],
    "岩手県": ["青森県", "秋田県", "宮城県"],
    "宮城県": ["岩手県", "秋田県", "山形県", "福島県"],
    "秋田県": ["青森県", "岩手県", "宮城県", "山形県"],
    "山形県": ["秋田県", "宮城県", "福島県", "新潟県"],
    "福島県": ["宮城県", "山形県", "新潟県", "群馬県", "栃木県", "茨城県"],
    "茨城県": ["福島県", "栃木県", "埼玉県", "千葉県"],
    "栃木県": ["福島県", "茨城県", "群馬県", "埼玉県"],
    "群馬県": ["福島県", "栃木県", "埼玉県", "長野県", "新潟県"],
    "埼玉県": ["群馬県", "栃木県", "茨城県", "千葉県", "東京都", "山梨県", "長野県"],
    "千葉県": ["茨城県", "埼玉県", "東京都"],
    "東京都": ["埼玉県", "千葉県", "神奈川県", "山梨県"],
    "神奈川県": ["東京都", "山梨県", "静岡県"],
    "新潟県": ["山形県", "福島県", "群馬県", "長野県", "富山県"],
    "富山県": ["新潟県", "長野県", "岐阜県", "石川県"],
    "石川県": ["富山県", "岐阜県", "福井県"],
    "福井県": ["石川県", "岐阜県", "滋賀県", "京都府"],
    "山梨県": ["埼玉県", "東京都", "神奈川県", "静岡県", "長野県"],
    "長野県": ["群馬県", "埼玉県", "山梨県", "静岡県", "愛知県", "岐阜県", "富山県", "新潟県"],
    "岐阜県": ["富山県", "石川県", "福井県", "長野県", "愛知県", "三重県", "滋賀県"],
    "静岡県": ["神奈川県", "山梨県", "長野県", "愛知県"],
    "愛知県": ["長野県", "岐阜県", "三重県", "静岡県"],
    "三重県": ["岐阜県", "愛知県", "滋賀県", "京都府", "奈良県", "和歌山県"],
    "滋賀県": ["福井県", "岐阜県", "三重県", "京都府"],
    "京都府": ["福井県", "滋賀県", "三重県", "奈良県", "大阪府", "兵庫県"],
    "大阪府": ["京都府", "兵庫県", "奈良県", "和歌山県"],
    "兵庫県": ["京都府", "大阪府", "鳥取県", "岡山県"],
    "奈良県": ["京都府", "大阪府", "和歌山県", "三重県"],
    "和歌山県": ["大阪府", "奈良県", "三重県"],
    "鳥取県": ["兵庫県", "岡山県", "広島県", "島根県"],
    "島根県": ["鳥取県", "広島県", "山口県"],
    "岡山県": ["兵庫県", "鳥取県", "広島県"],
    "広島県": ["岡山県", "鳥取県", "島根県", "山口県"],
    "山口県": ["島根県", "広島県"],
    "徳島県": ["香川県", "愛媛県", "高知県"],
    "香川県": ["徳島県", "愛媛県"],
    "愛媛県": ["香川県", "徳島県", "高知県"],
    "高知県": ["徳島県", "愛媛県"],
    "福岡県": ["佐賀県", "大分県", "熊本県"],
    "佐賀県": ["福岡県", "長崎県"],
    "長崎県": ["佐賀県"],
    "熊本県": ["福岡県", "大分県", "宮崎県", "鹿児島県"],
    "大分県": ["福岡県", "熊本県", "宮崎県"],
    "宮崎県": ["熊本県", "大分県", "鹿児島県"],
    "鹿児島県": ["熊本県", "宮崎県"],
    "沖縄県": [],
}


JUN_REP_DAY = {'上旬': 5, '中旬': 15, '下旬': 25}  # 旬の代表日（窓の中心に使う）

def _resolve_month(today, mo, rep_day):
    """月/旬用。『その月という季節』なので月単位でロール（同月なら今年のまま、
    過去の月だけ翌年へ）。rep_day は窓の中心に使う代表日。"""
    year = today.year + 1 if mo < today.month else today.year
    try:
        return date(year, mo, rep_day)
    except ValueError:
        return None

def parse_period(text, today=None):
    """対象時期を解釈して {'date','specified','granularity'} を返す。
    granularity: 'day' | 'jun'(上中下旬) | 'month' | None(指定なし)。
    指定が無ければ date=today, specified=False, granularity=None（＝「今の時期」）。
    判定順: 相対(明日等) → M月D日 → M月(上中下旬) → 来週等 → M月単独。"""
    today = today or date.today()
    P = lambda d, s, g: {'date': d, 'specified': s, 'granularity': g}

    if "明日" in text or "あした" in text:
        return P(today + timedelta(days=1), True, 'day')
    if "明後日" in text or "あさって" in text:
        return P(today + timedelta(days=2), True, 'day')
    if "今日" in text or "本日" in text:
        return P(today, True, 'day')
    m = re.search(r'(\d+)日後', text)
    if m:
        return P(today + timedelta(days=int(m.group(1))), True, 'day')

    m = re.search(r'(\d{1,2})月(\d{1,2})日', text)
    if m:
        mo, dy = int(m.group(1)), int(m.group(2))
        try:
            t = date(today.year, mo, dy)
            if t < today:
                t = date(today.year + 1, mo, dy)
            return P(t, True, 'day')
        except ValueError:
            pass

    # M月 + 上旬/中旬/下旬
    m = re.search(r'(\d{1,2})月\s*(上旬|中旬|下旬)', text)
    if m:
        t = _resolve_month(today, int(m.group(1)), JUN_REP_DAY[m.group(2)])
        if t:
            return P(t, True, 'jun')

    if "来週末" in text:
        return P(today + timedelta(days=(5 - today.weekday() + 7)), True, 'day')
    if "来週" in text:
        return P(today + timedelta(days=7), True, 'day')
    if "今週末" in text or "週末" in text:
        days_ahead = 5 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return P(today + timedelta(days=days_ahead), True, 'day')

    # M月 単独（直後が 日/数字 でないとき＝その月全体）。旬は前段で判定済みのため上中下は弾かない
    # （弾くと「12月上高地」の『上』まで巻き込み12月が読めなくなる）
    m = re.search(r'(\d{1,2})月(?!\d)', text)
    if m:
        t = _resolve_month(today, int(m.group(1)), 15)  # 月の中心（±3週窓で月全体を概ねカバー）
        if t:
            return P(t, True, 'month')

    return P(today, False, None)

def period_phrase(pp=None, date_=None, specified=False, granularity=None):
    """検索の対象時期を表す名詞句。見出しの「今の時期」を置換する単一の出所。
    pp（parse_periodの戻り値）を渡すか、date_/specified/granularity を直接渡す。
    指定なしは『今の時期』。日指定は『◯月◯日ごろ』、旬は『◯月中旬』、月は『◯月』。"""
    if pp is not None:
        date_ = pp.get('date'); specified = pp.get('specified'); granularity = pp.get('granularity')
    if not specified or date_ is None:
        return "今の時期"
    if granularity == 'month':
        return f"{date_.month}月"
    if granularity == 'jun':
        return f"{date_.month}月{junkun(date_.day)}"
    return f"{date_.month}月{date_.day}日ごろ"  # 'day' その他

def parse_target_date(text):
    """後方互換: 対象日のみ返す。解釈は parse_period に委譲。"""
    return parse_period(text)['date']

def parse_target_area(text):
    for pref in PREF_LATLNG:
        if pref == "北海道":
            short = "北海道"
        else:
            short = re.sub(r'[都府県]$', '', pref)
        if pref in text or short in text:
            return pref, PREF_LATLNG[pref], pref  # 県のみ指定 → 表示も検索キーも県名（県庁所在地名にしない）
    for city, pref in CITY_PREF.items():
        if city in text:
            return pref, PREF_LATLNG[pref], city
    for city, pref in CITY_TO_PREF.items():
        # 「美瑛」→「美瑛町」のような前方一致も拾う
        city_base = re.sub(r'[市区町村郡]', '', city).strip()
        if city in text:
            if city in CITY_TO_PREF_MULTI:
                return "AMBIGUOUS", None, city
            latlng = geocode(city) or CITY_TO_LATLNG.get(city, PREF_LATLNG[pref])
            matched_name = city_base if city_base in text else city
            return pref, latlng, matched_name
    for city in CITY_TO_PREF_MULTI:
        city_base = re.sub(r'[市区町村郡]', '', city).strip()
        if city in text or (len(city_base) >= 2 and city_base in text):
            return "AMBIGUOUS", None, city
    EXCLUDE_WORDS = {'撮影', '明日', '今日', '明後日', '写真', '行きたい', '探して', '教えて', 'したい', 'ください'}
    words = [w for w in re.split(r'[\s、。！？!?]+', text) if len(w) >= 2 and w not in EXCLUDE_WORDS]
    for word in words:
        latlng = geocode(word + ' 日本')
    return None, None, None
def format_date_jp(d):
    weekdays = ["月","火","水","木","金","土","日"]
    return f"{d.month}月{d.day}日（{weekdays[d.weekday()]}）"

def build_greeting(target_date, area_name, date_specified=False):
    today = date.today()
    delta = (target_date - today).days
    if delta == 1:
        date_str = f"明日（{format_date_jp(target_date)}）に"
    elif delta == 2:
        date_str = f"明後日（{format_date_jp(target_date)}）に"
    elif 3 <= delta <= 14:
        date_str = f"{delta}日後（{format_date_jp(target_date)}）に"
    elif date_specified:
        date_str = f"{format_date_jp(target_date)}に"
    else:
        date_str = ""
    area_str = f"{area_name}に" if area_name and area_name != "現在地" else ""
    if date_str or area_str:
        return (
            f"ようこそ風景写真コンシェルジュの部屋へ。"
            f"{date_str}{area_str}撮影にお出かけですか。"
            f"それでしたらこんなところはいかがでしょう。"
        )
    else:
        return "ようこそ風景写真コンシェルジュの部屋へ。こんなところはいかがでしょう。"

# ──────────────── 3分類選定エンジン ────────────────
def select_three_points(base_date=None, base_latlng=None, radius=None, place_name=None, keyword=None, expand_time=False, target_city=None, origin_latlng=None, origin_name=None, allowed_prefs=None):

    if not db:
        return []

    try:
        # radius未指定(None)時は距離制限なしとして扱う(dist > None のTypeError防止)
        if radius is None:
            radius = float('inf')
        # 距離計算の基準点と、表示用の基準地名("◯◯より △△km")
        tokyo = PREF_LATLNG["東京都"]
        # 距離の起点(現在地 or 新宿区)と、表示用の起点名("◯◯より △△km")。検索中心(base_latlng)とは別概念。
        origin = origin_latlng if origin_latlng else SHINJUKU
        base_name = origin_name or DEFAULT_ORIGIN_NAME
        excl_authors, blocked_areas = load_exclusions()
        tomorrow = base_date if base_date else date.today() + timedelta(days=1)
        if expand_time:
            junkun_window = set()
            for delta in range(-30, 31):
                d2 = tomorrow + timedelta(days=delta)
                junkun_window.add((d2.month, junkun(d2.day)))
        else:
            junkun_window = half_month_window(tomorrow)

        pool = []
        place_years = defaultdict(list)


        # 指定都道府県を特定
        target_pref = None
        if base_latlng:
            target_pref = min(PREF_LATLNG.keys(), key=lambda k: haversine(base_latlng[0], base_latlng[1], PREF_LATLNG[k][0], PREF_LATLNG[k][1]))

        target_months = list(set(str(m) for m, k in junkun_window))
        query = db.collection('Master_Photos').where('Month', 'in', target_months)
        for doc in query.stream():
            d = doc.to_dict()

            try:
                mo = int(d.get('Month'))
            except:
                continue
            if (mo, junkun(d.get('Day'))) not in junkun_window:
                continue

            pref = extract_pref(d.get('Area'))
            if not pref:
                continue
            lat, lng = PREF_LATLNG[pref]
            dist = haversine(tokyo[0], tokyo[1], lat, lng)  # 既存の絞り込み用(従来通り)
            wll = work_latlng(d.get('Area'), pref)
            wlat, wlng = wll if wll else (lat, lng)          # 表示用座標: 市区町村, なければ県重心
            disp_dist = haversine(origin[0], origin[1], wlat, wlng)  # 起点→撮影地の実距離

            # 指定都道府県がある場合の絞り込み
            if target_pref:
                if target_city and base_latlng:
                    # 市指定時は「指定地点中心」で近隣を判定（撮影地の市座標で精密に）
                    base_dist = haversine(base_latlng[0], base_latlng[1], wlat, wlng)
                    if pref != target_pref and base_dist > radius:
                        continue
                elif allowed_prefs is not None:
                    # 県指定時は「対象とする県の集合」で絞る（初回は県内のみ、拡張時は県＋隣県）
                    if pref not in allowed_prefs:
                        continue
                else:
                    if pref != target_pref and dist > radius:
                        continue
            else:
                if dist > radius:
                    continue

            if d.get('Winner') in excl_authors:
                continue
            if is_area_blocked(d.get('Place'), d.get('Area'), blocked_areas):
                continue
            if not has_valid_image(d.get('PicFileName')):
                continue
            # 風景写真祭作品は検索対象外
            pub = d.get('Published', '')
            if pub and pub.endswith('N'):
                continue

            matched_kw = None
            if keyword:
                kw_variants = KEYWORD_NORMALIZE.get(keyword, [keyword])
                if not subject_matches(kw_variants, title=d.get('Title', ''), place=d.get('Place', ''),
                                       area=d.get('Area', ''), subject_field=d.get('Subject', ''),
                                       exclude=subject_exclude_for(keyword)):
                    continue
                _blob = d.get('Subject', '') + d.get('Title', '') + d.get('Place', '') + d.get('Area', '')
                matched_kw = next((v for v in kw_variants if v in _blob), keyword)

            item = {
                'dist': disp_dist,
                'wlatlng': (wlat, wlng),
                'pref': pref,
                'area': d.get('Area', ''),
                'place': d.get('Place', ''),
                'title': d.get('Title', ''),
                'period': format_period(d.get('Month'), d.get('Day')),
                'winner': d.get('Winner', ''),
                'winner_area': d.get('WinnerArea', ''),
                'award': d.get('AwardRank', ''),
                'ascore': calc_award_score(d.get('AwardRank')),
                'pic': d.get('PicFileName', ''),
                'pub': d.get('Published', ''),
                'url': view_image_url(d.get('Published', ''), d.get('PicFileName', '')),
                'base_name': base_name,
                'maplink': d.get('MapLink', ''),
                'dnumb': str(d.get('dNumb', '')),
                'matched_kw': matched_kw,
            }
            pool.append(item)

            try:
                place_years[d.get('Area', '')].append(int(d.get('Year')))
            except:
                pass


        # 地域指定時にpoolが空の場合はTOO_FEWを返す
        if not pool and target_pref:
            return 'TOO_FEW', target_pref, 0, []
        # 地域未指定時にpoolが空の場合、旬ウィンドウを前後1ヶ月に広げてリトライ
        if not pool and base_latlng and not target_pref:
            wider_window = set()
            for delta in range(-30, 31):
                d2 = tomorrow + timedelta(days=delta)
                wider_window.add((d2.month, junkun(d2.day)))
            wider_months = list(set(str(m) for m, k in wider_window))
            wider_query = db.collection('Master_Photos').where('Month', 'in', wider_months)
            for doc in wider_query.stream():
                d = doc.to_dict()
                try:
                    mo = int(d.get('Month'))
                except:
                    continue
                if (mo, junkun(d.get('Day'))) not in wider_window:
                    continue
                pref = extract_pref(d.get('Area'))
                if not pref:
                    continue
                lat, lng = PREF_LATLNG[pref]
                dist = haversine(tokyo[0], tokyo[1], lat, lng)
                if dist > radius:
                    continue
                if d.get('Winner') in excl_authors:
                    continue
                if not has_valid_image(d.get('PicFileName')):
                    continue
                pub = d.get('Published', '')
                if pub and pub.endswith('N'):
                    continue
                item = {
                    'dist': disp_dist,
                    'wlatlng': (wlat, wlng),
                    'pref': pref,
                    'area': d.get('Area', ''),
                    'place': d.get('Place', '') or '',
                    'title': d.get('Title', ''),
                    'period': format_period(d.get('Month'), d.get('Day')),
                    'winner': d.get('Winner', ''),
                    'winner_area': d.get('WinnerArea', ''),
                    'award': d.get('AwardRank', ''),
                    'ascore': calc_award_score(d.get('AwardRank')),
                    'pic': d.get('PicFileName', ''),
                    'pub': d.get('Published', ''),
                    'url': view_image_url(d.get('Published', ''), d.get('PicFileName', '')),
                    'base_name': base_name,
                    'maplink': d.get('MapLink', ''),
                    'dnumb': str(d.get('dNumb', '')),
                    'matched_kw': None,
                }
                pool.append(item)
                try:
                    place_years[d.get('Area', '')].append(int(d.get('Year')))
                except:
                    pass

        if not pool:
            if target_pref:
                return 'TOO_FEW', target_pref, 0, []
            return []

        # 市町村が明示された場合: 市一致をベストマッチ、それ以外を「◯◯周辺の撮影地」に分けて返す
        if target_pref and target_city:
            city_base = re.sub(r'[市区町村郡]', '', target_city).strip()
            CITY_NEARBY_RADIUS_KM = 75  # 市指定時の「周辺」範囲（指定地点中心）
            # 指定地点(base_latlng=検索中心)から撮影地の市座標までの距離（なければ県重心）
            def _city_dist(p):
                if not base_latlng:
                    return 99999
                ll = p.get('wlatlng') or PREF_LATLNG.get(p['pref'])
                if not ll:
                    return 99999
                return haversine(base_latlng[0], base_latlng[1], ll[0], ll[1])
            sorted_pool = sorted(pool, key=lambda x: (-x['ascore'], x['dist']))
            city_pool = [p for p in sorted_pool if city_base and city_base in p['area']]
            nearby_pool = sorted(
                [p for p in sorted_pool
                 if not (city_base and city_base in p['area']) and _city_dist(p) <= CITY_NEARBY_RADIUS_KM],
                key=lambda x: (_city_dist(x), -x['ascore'])
            )
            used_pics = set()
            cresults = []
            # ベストマッチ(市一致): 同一作品のみ除去し、同じ市の作品は複数見せる(撮影地重複を許容)
            for p in city_pool:
                if len(cresults) >= 7:
                    break
                if p['pic'] in used_pics:
                    continue
                cresults.append(('🎯', 'ベストマッチ', p))
                used_pics.add(p['pic'])
            city_count = len(cresults)
            # 周辺候補: 撮影地の重複を避けて補完
            nearby_label = f"{city_base}周辺の撮影地"
            used_areas = set()
            for p in nearby_pool:
                if len(cresults) >= 7:
                    break
                if p['pic'] in used_pics or p['area'] in used_areas:
                    continue
                cresults.append(('📍', nearby_label, p))
                used_pics.add(p['pic'])
                used_areas.add(p['area'])
            return ('CITY', city_base, city_count, filter_broken_images(cresults))

        used_pics = set()
        results = []

        _expanded = allowed_prefs is not None and len(allowed_prefs) > 1
        # 🎯 ベストマッチ（同県優先、最大7枚）
        if target_pref:
            if _expanded:
                # 拡張検索(県＋隣県): 対象県すべてから集める。県内が少なくても隣県で補うのでTOO_FEW判定はしない
                best_pool = sorted(pool, key=lambda x: (-x['ascore'], x['dist']))
            else:
                best_pool = [p for p in sorted(pool, key=lambda x: (-x['ascore'], x['dist'])) if p['pref'] == target_pref]
                if len(best_pool) < 3:
                    return 'TOO_FEW', target_pref, len(best_pool), filter_broken_images([('🎯', 'ベストマッチ', p) for p in best_pool])
        else:
            best_pool = sorted(pool, key=lambda x: (-x['ascore'], x['dist']))
        used_areas = set()
        for p in best_pool:
            if len(results) >= 7:
                break
            if p['area'] in used_areas:
                continue
            results.append(('🎯', 'ベストマッチ', p))
            used_pics.add(p['pic'])
            used_areas.add(p['area'])

        # ✨ 注目・傑作（同県優先、最大2枚）
        recent_cutoff = date.today().year - 5
        attention_score = {
            a: sum(1 for y in ys if y >= recent_cutoff)
            for a, ys in place_years.items()
        }
        hot_pool = sorted(pool, key=lambda x: (-attention_score.get(x['area'], 0), -x['ascore']))
        if target_pref and not _expanded:
            hot_cand = [p for p in hot_pool if p['pref'] == target_pref and p['pic'] not in used_pics] or [p for p in hot_pool if p['pic'] not in used_pics]
        else:
            hot_cand = [p for p in hot_pool if p['pic'] not in used_pics]
        used_areas_hot = set()
        for p in hot_cand:
            if len([r for r in results if r[1] == '注目・傑作']) >= 2:
                break
            if p['area'] in used_areas_hot:
                continue
            results.append(('✨', '注目・傑作', p))
            used_pics.add(p['pic'])
            used_areas_hot.add(p['area'])

        masterpiece = results[0][2] if results else None
        near = results[1][2] if len(results) > 1 else masterpiece

        # 🎲 気まぐれチョイス（地域・キーワード未指定の時のみ、最大2枚）
        show_gamble = not base_latlng and not keyword
        if show_gamble:
            all_docs = list(db.collection('Master_Photos').stream())
        else:
            all_docs = []
        random.shuffle(all_docs)
        gamble_count = 0
        for doc in all_docs:
            if gamble_count >= 2:
                break
            d = doc.to_dict()
            if d.get('PicFileName') in used_pics:
                continue
            if not has_valid_image(d.get('PicFileName')):
                continue
            pub = d.get('Published', '')
            if pub and pub.endswith('N'):
                continue
            item = {
                'dist': haversine(origin[0], origin[1],
                                  *( work_latlng(d.get('Area', '')) or PREF_LATLNG.get(extract_pref(d.get('Area', '')) or '', SHINJUKU) )),
                'pref': extract_pref(d.get('Area', '')),
                'area': d.get('Area', ''),
                'place': d.get('Place', '') or '',
                'title': d.get('Title', ''),
                'period': format_period(d.get('Month'), d.get('Day')),
                'winner': d.get('Winner', ''),
                'winner_area': d.get('WinnerArea', ''),
                'award': d.get('AwardRank', ''),
                'ascore': calc_award_score(d.get('AwardRank')),
                'pic': d.get('PicFileName', ''),
                'pub': d.get('Published', ''),
                'url': view_image_url(d.get('Published', ''), d.get('PicFileName', '')),
                'base_name': base_name,
                'maplink': d.get('MapLink', ''),
                'dnumb': str(d.get('dNumb', '')),
                'matched_kw': matched_kw,
            }
            results.append(('🎲', '気まぐれチョイス', item))
            used_pics.add(item['pic'])
            gamble_count += 1


        # 地域指定がある場合はベストマッチ（同県）を前に並べ替え
        if base_latlng:
            same_pref = [(e, l, p) for e, l, p in results if l == 'ベストマッチ']
            others = [(e, l, p) for e, l, p in results if l != 'ベストマッチ']
            results = same_pref + others

        return filter_broken_images(results)

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        # Renderのログ(stdout)にも出す。ファイルだけだと画面で気づけないため
        print(f"[ERROR] select_three_points exception: {tb}", flush=True)
        return []

# ──────────────── Flex Message 組み立て ────────────────
def search_by_place(place_query, base_date=None, origin_latlng=None, origin_name=None, subject=None, center_latlng=None, radius_km=None, home_latlng=None, expand_time=False):
    """地点名(Place/Area/Title)の自由文検索。
    今の時期に一致する作品があればそれを、無ければ全期間からその地点の作品を返す。
    center_latlng+radius_km を指定すると、その中心から半径内の作品に絞り近い順に返す。
    home_latlng も指定すると、自宅に近づく方向(帰路)の作品だけに絞り、寄り道の少ない順に返す。
    expand_time=True で「今の時期」の判定窓を前後およそ1.5か月に広げる(期間を広げる)。
    返り値: {'status': 'in_season'|'off_season'|'not_found', 'results': [(emoji,label,item),...]}"""
    if not db:
        return {'status': 'not_found', 'results': []}
    base = base_date if base_date else date.today() + timedelta(days=1)
    window = half_month_window(base, expand=expand_time)
    tokyo = PREF_LATLNG["東京都"]
    origin = origin_latlng if origin_latlng else SHINJUKU
    base_name = origin_name or DEFAULT_ORIGIN_NAME
    try:
        excl_authors, blocked_areas = load_exclusions()
    except Exception:
        excl_authors, blocked_areas = set(), []
    in_season, all_time = [], []
    bin_counter = Counter()  # マッチした公開作品の旬分布(見頃クラスタ算出用)
    subject_variants = KEYWORD_NORMALIZE.get(subject, [subject]) if subject else None
    subject_exclude = subject_exclude_for(subject) if subject else []
    place_terms = place_query if isinstance(place_query, (list, tuple)) else [place_query]
    place_terms = [t for t in place_terms if t]
    try:
        for doc in db.collection('Master_Photos').stream():
            d = doc.to_dict()
            place = d.get('Place', '') or ''
            area = d.get('Area', '') or ''
            title = d.get('Title', '') or ''
            if place_terms and not any(t in place or t in area or t in title for t in place_terms):
                continue
            if subject_variants and not subject_matches(subject_variants, title=title, place=place, area=area, subject_field=d.get('Subject', ''), exclude=subject_exclude):
                continue
            if d.get('Winner') in excl_authors:
                continue
            if is_area_blocked(d.get('Place'), d.get('Area'), blocked_areas):
                continue
            if not has_valid_image(d.get('PicFileName')):
                continue
            pub = d.get('Published', '')
            if pub and pub.endswith('N'):
                continue
            pref = extract_pref(area)
            wll = work_latlng(area, pref)
            cll = wll if wll else (PREF_LATLNG.get(pref) if (pref and pref in PREF_LATLNG) else None)
            if center_latlng and radius_km:
                if not cll or haversine(center_latlng[0], center_latlng[1], cll[0], cll[1]) > radius_km:
                    continue
            cdist = haversine(center_latlng[0], center_latlng[1], cll[0], cll[1]) if (center_latlng and cll) else 0
            detour = 0
            if home_latlng and center_latlng:
                if not cll:
                    continue
                d_ch = haversine(center_latlng[0], center_latlng[1], home_latlng[0], home_latlng[1])
                d_wh = haversine(cll[0], cll[1], home_latlng[0], home_latlng[1])
                if d_wh >= d_ch:   # 自宅に近づかない(=帰路方向でない)ものは除外
                    continue
                detour = cdist + d_wh - d_ch   # 寄り道距離(現在地→作品→自宅 と 現在地→自宅 の差)
            if wll:
                dist = haversine(origin[0], origin[1], wll[0], wll[1])
            elif pref and pref in PREF_LATLNG:
                dist = haversine(origin[0], origin[1], PREF_LATLNG[pref][0], PREF_LATLNG[pref][1])
            else:
                dist = 0
            try:
                year = int(d.get('Year'))
            except Exception:
                year = 0
            item = {
                'dist': dist, 'pref': pref or '', 'area': area, 'place': place, 'cdist': cdist, 'detour': detour,
                'title': title, 'period': format_period(d.get('Month'), d.get('Day')), 'winner': d.get('Winner', ''), 'winner_area': d.get('WinnerArea', ''),
                'award': d.get('AwardRank', ''), 'ascore': calc_award_score(d.get('AwardRank')),
                'pic': d.get('PicFileName', ''), 'pub': pub,
                'url': view_image_url(pub, d.get('PicFileName', '')),
                'base_name': base_name, 'maplink': d.get('MapLink', ''),
                'dnumb': str(d.get('dNumb', '')), 'matched_kw': None, '_year': year,
            }
            all_time.append(item)
            try:
                _mo = int(d.get('Month'))
                if 1 <= _mo <= 12:
                    bin_counter[bin_index(_mo, d.get('Day'))] += 1
                if (_mo, junkun(d.get('Day'))) in window:
                    in_season.append(item)
            except Exception:
                pass
    except Exception:
        import traceback
        print(f"[ERROR] search_by_place failed: {traceback.format_exc()}", flush=True)
        return {'status': 'not_found', 'results': []}

    if in_season:
        pool, status = in_season, 'in_season'
    elif all_time:
        pool, status = all_time, 'off_season'
    else:
        return {'status': 'not_found', 'results': []}
    if home_latlng and center_latlng:
        pool.sort(key=lambda x: (x.get('detour', 0), x.get('cdist', 0)))
    elif center_latlng:
        pool.sort(key=lambda x: (x.get('cdist', 0), -x['ascore']))
    else:
        pool.sort(key=lambda x: (-x['ascore'], -x.get('_year', 0)))
    results, used = [], set()
    for p in pool:
        if len(results) >= 7:
            break
        if p['pic'] in used:
            continue
        results.append(('🎯', 'ベストマッチ', p))
        used.add(p['pic'])
    results = filter_broken_images(results)
    if not results:
        return {'status': 'not_found', 'results': []}
    peaks = compute_peaks(bin_counter)
    return {'status': status, 'results': results, 'peaks': peaks}

def subjects_in_peak_near(center_latlng, radius_km, base_date=None):
    """中心から半径内の公開作品を被写体別に集計し、現在(base_date)が見頃にあたる被写体を返す。
    戻り値: [(subject, peaks_text, count), ...] を件数の多い順で。"""
    if not db or not center_latlng:
        return []
    base = base_date or date.today()
    cur_bin = bin_index(base.month, base.day)
    try:
        excl_authors, blocked_areas = load_exclusions()
    except Exception:
        excl_authors, blocked_areas = set(), []
    from collections import defaultdict
    bins = defaultdict(Counter)
    try:
        for doc in db.collection('Master_Photos').stream():
            d = doc.to_dict()
            pub = d.get('Published', '')
            if pub and pub.endswith('N'):
                continue
            if not has_valid_image(d.get('PicFileName')):
                continue
            if d.get('Winner') in excl_authors:
                continue
            area = d.get('Area', '') or ''
            place = d.get('Place', '') or ''
            title = d.get('Title', '') or ''
            if is_area_blocked(place, area, blocked_areas):
                continue
            pref = extract_pref(area)
            wll = work_latlng(area, pref) or (PREF_LATLNG.get(pref) if (pref and pref in PREF_LATLNG) else None)
            if not wll or haversine(center_latlng[0], center_latlng[1], wll[0], wll[1]) > radius_km:
                continue
            try:
                mo = int(d.get('Month'))
            except Exception:
                continue
            if not (1 <= mo <= 12):
                continue
            bi = bin_index(mo, d.get('Day'))
            sfield = d.get('Subject', '')
            for canon, variants in KEYWORD_NORMALIZE.items():
                if subject_matches(variants, title=title, place=place, area=area, subject_field=sfield, exclude=subject_exclude_for(canon)):
                    bins[canon][bi] += 1
    except Exception:
        import traceback
        print(f"[ERROR] subjects_in_peak_near: {traceback.format_exc()}", flush=True)
        return []
    out = []
    for canon, bc in bins.items():
        peaks = compute_peaks(bc)
        if not peaks:
            continue
        for c in peaks:
            if min((cur_bin - c) % 36, (c - cur_bin) % 36) <= 1:  # 現在が見頃クラスタの±1旬以内
                out.append((canon, peaks_text(peaks), sum(bc.values())))
                break
    out.sort(key=lambda x: -x[2])
    return out


def extract_subject(text):
    """テキストから被写体を取り出す。「S<被写体>」明示指定を優先(Sの直後〜末尾を被写体、Sの前を残り)。
    辞書に無い被写体もそのまま採用。S指定が無ければ辞書で自動判定。
    戻り値: (subject_or_None, remaining_text)。"""
    t = text or ''
    m = re.search(r'[SsＳｓ]', t)
    if m:
        after = t[m.end():].strip()
        before = t[:m.start()]
        if after:
            cs = after
            for canon, variants in KEYWORD_NORMALIZE.items():
                if after == canon or after in variants:
                    cs = canon
                    break
            return cs, before
    canon, var = detect_subject_longest_variant(t)
    if canon:
        return canon, t.replace(var, ' ', 1)
    return None, t


def resolve_place(txt):
    """地名文字列を座標に解決。自由文に強い geocode を優先し、ダメなら都道府県/市区町村辞書。
    戻り値: (latlng or None, name or None, confident)。confident は geocode で確定できた場合 True
    (辞書フォールバックは「東京板橋→東京都」のような部分一致があり得るため低信頼=False)。"""
    txt = (txt or '').strip()
    if len(txt) < 2:
        return None, None, False
    try:
        g = geocode(txt)
    except Exception:
        g = None
    if g:
        return g, txt, True
    an, al, ad = parse_target_area(txt)
    if al and an not in (None, "AMBIGUOUS"):
        return al, (ad or txt), False
    return None, None, False


def do_route_search(reply_token, center, center_nm, dest_ll, dest_nm, subject, radius,
                    origin_latlng, origin_name, note=""):
    """起点centerから目的地dest方向・半径radius(km)圏内を寄り道の少ない順に返す。
    radius=None なら起点→目的地の距離(×1.15)を半径にする。"""
    if radius is None:
        d = haversine(center[0], center[1], dest_ll[0], dest_ll[1])
        radius = int(max(30, min(d * 1.15, 2000)))
    else:
        radius = max(5, min(radius, 2000))
    rr = search_by_place([], base_date=date.today(), origin_latlng=origin_latlng, origin_name=origin_name,
                         subject=subject, center_latlng=center, radius_km=radius, home_latlng=dest_ll)
    if rr['status'] == 'not_found' or not rr['results']:
        line_bot_api.reply_message(reply_token, TextSendMessage(
            text=note + f"{center_nm}から{dest_nm}方向・半径{radius}km圏内に{(subject or '撮影地')}の作品が見つかりませんでした。半径を広げるか目的地を変えてお試しください。"))
        return
    subj_txt = (subject + "の") if subject else ""
    reply_with_carousel(reply_token, note + f"{center_nm}から{dest_nm}方向・半径{radius}km圏内の{subj_txt}撮影地を、寄り道の少ない順にご紹介します。", rr['results'])


def ambiguous_ward_candidates(txt, origin_latlng=None, limit=6):
    """txt がちょうど曖昧な区名(中央区など)なら候補を返す。現在地があれば近い順、無ければ主要都市順。
    曖昧でなければ None。戻り値: [(正式名, (lat,lng)), ...]。"""
    fs = WARD_INDEX.get((txt or '').strip())
    if not fs:
        return None
    if origin_latlng:
        ranked = sorted(fs, key=lambda x: haversine(origin_latlng[0], origin_latlng[1], x[1][0], x[1][1]))
    else:
        def _rank(x):
            for i, p in enumerate(MAJOR_PREF_ORDER):
                if x[0].startswith(p):
                    return i
            return len(MAJOR_PREF_ORDER)
        ranked = sorted(fs, key=_rank)
    return ranked[:limit]


def ask_ward(reply_token, user_id, ward_name, cands, mode, center, center_nm,
             subject, radius, origin_latlng, origin_name):
    """同名の区の候補を、クイックリプライ(ボタン)＋本文の番号併記で提示し、選択待ち状態にする。"""
    WARD_PENDING[user_id] = {"cands": cands, "mode": mode, "center": center, "center_nm": center_nm,
                             "subject": subject, "radius": radius,
                             "origin_latlng": origin_latlng, "origin_name": origin_name}
    qr = QuickReply(items=[
        QuickReplyButton(action=PostbackAction(label=full[:20], data=f"action=ward&i={i}", display_text=full))
        for i, (full, _) in enumerate(cands)])
    body = "\n".join(f"{i+1}．{full}" for i, (full, _) in enumerate(cands))
    line_bot_api.reply_message(reply_token, TextSendMessage(
        text=(f"「{ward_name}」は各地にあります。番号でお選びください（例：2）。\n{body}\n\n"
              f"これ以外は『大阪市{ward_name}』のように市名を付けて送ってください。"),
        quick_reply=qr))


def finish_ward_choice(reply_token, user_id, full_name, latlng):
    """WARD_PENDING の文脈に従って、選ばれた区で帰宅(自宅登録+検索) または 目的地検索を実行する。"""
    wp = WARD_PENDING.pop(user_id, None)
    if not wp:
        return
    center, center_nm = wp["center"], wp["center_nm"]
    if wp["mode"] == "home":
        save_user_home(user_id, latlng[0], latlng[1], full_name)
        note = f"自宅を「{full_name}」に登録しました。次回からは末尾に『r』を付けるだけで帰り道をご案内します。\n"
        if center is None:
            line_bot_api.reply_message(reply_token, TextSendMessage(
                text=note + "今回は起点（現在地）が分からないため帰り道の検索はできませんでした。位置情報を送るか『茅野r』のように起点を付けてお試しください。"))
            return
        do_route_search(reply_token, center, center_nm, latlng, full_name,
                        wp["subject"], wp["radius"], wp["origin_latlng"], wp["origin_name"], note=note)
        return
    do_route_search(reply_token, center, center_nm, latlng, full_name,
                    wp["subject"], wp["radius"], wp["origin_latlng"], wp["origin_name"])


def expand_pref_name(s):
    """短縮県名を正式名に展開（例: 東京→東京都、大阪→大阪府、北海道→北海道）"""
    s = str(s or '').strip()
    if not s:
        return ''
    for full in PREF_LATLNG:
        short = re.sub(r'[都府県]$', '', full)
        if s == full or s == short:
            return full
    return s

def build_carousel_bubble(item, label_emoji, area_note="", matched_kw=None, plan_id=None, idx=0):
    place = item.get('place', '')
    area = item.get('area', '')
    location_contents = []
    if place:
        location_contents.append({
            "type": "text",
            "text": place,
            "weight": "bold",
            "size": "xl",
            "wrap": True,
            "color": "#111111"
        })
        if area:
            location_contents.append({
                "type": "text",
                "text": area,
                "size": "sm",
                "color": "#666666",
                "margin": "xs"
            })
    else:
        if area:
            location_contents.append({
                "type": "text",
                "text": area,
                "weight": "bold",
                "size": "xl",
                "wrap": True,
                "color": "#111111"
            })

    from urllib.parse import quote
    map_uri = f"https://maps.google.com/maps?q={quote(area)}" if area else "https://maps.google.com/"
    ref_base = "https://reference.fukei-shashin.co.jp/reference"
    ref_location = place if place else area
    ref_uri = f"{ref_base}?location={quote(ref_location)}" if ref_location else ref_base
    # 撮影プランナーURL
    planner_base = "https://reference.fukei-shashin.co.jp/planner"
    if plan_id:
        # PlanSession方式: 全候補をFirestoreに保存済み、IDとインデックスだけ渡す
        planner_uri = f"{planner_base}?planId={quote(plan_id)}&idx={idx}"
    else:
        # フォールバック: 単品パラメータ方式（候補が1件のとき）
        planner_params = []
        if area:
            planner_params.append(f"area={quote(area)}")
        if place:
            planner_params.append(f"place={quote(place)}")
        if item.get('title'):
            planner_params.append(f"title={quote(item['title'])}")
        if item.get('period'):
            planner_params.append(f"period={quote(item['period'])}")
        if item.get('pub'):
            planner_params.append(f"pub={quote(str(item['pub']))}")
        if item.get('url'):
            planner_params.append(f"img={quote(item['url'])}")
        if item.get('winner'):
            planner_params.append(f"winner={quote(item['winner'])}")
        if item.get('award'):
            planner_params.append(f"award={quote(item['award'])}")
        planner_uri = f"{planner_base}?{'&'.join(planner_params)}" if planner_params else planner_base

    bubble = {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": item['url'],
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover",
            "action": {
                "type": "uri",
                "uri": item['url']
            }
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": f"{label_emoji} {area_note}",
                    "weight": "bold",
                    "size": "md",
                    "color": "#666666"
                },
            ] + location_contents + [
                {
                    "type": "text",
                    "text": (f"{item['title']} {item['period']}" if item.get('period') else item['title']),
                    "size": "sm",
                    "margin": "sm",
                    "wrap": True,
                    "color": "#444444"
                },
                {
                    "type": "text",
                    "text": (f"{item['winner']}（{expand_pref_name(item.get('winner_area',''))}）" if item.get('winner_area') else f"{item['winner']}"),
                    "size": "sm",
                    "color": "#666666",
                    "margin": "xs"
                },
                {
                    "type": "text",
                    "text": (f"{item['base_name']}より {item['dist']:.0f}km" if item['dist'] >= 5 else f"{item['base_name']}周辺"),
                    "size": "sm",
                    "color": "#999999",
                    "margin": "sm"
                }
            ] + ([{
                    "type": "text",
                    "text": f"🔍 '{matched_kw}'を含む",
                    "size": "xs",
                    "color": "#aaaaaa",
                    "margin": "xs"
                }] if matched_kw else [])
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "button",
                            "style": "primary",
                            "height": "sm",
                            "action": {
                                "type": "postback",
                                "label": "作品情報",
                                "data": f"action=detail&pic={item['pic']}&dnumb={item.get('dnumb', '')}"
                            }
                        },
                        {
                            "type": "button",
                            "style": "secondary",
                            "height": "sm",
                            "action": {
                                "type": "uri",
                                "label": "マップ",
                                "uri": map_uri
                            }
                        }
                    ]
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "action": {
                        "type": "uri",
                        "label": "📍 リファレンスをチェック",
                        "uri": ref_uri
                    }
                },
                {
                    "type": "button",
                    "style": "primary",
                    "height": "sm",
                    "color": "#1DB446",
                    "action": {
                        "type": "uri",
                        "label": "📋 撮影プランナー",
                        "uri": planner_uri
                    }
                }
            ]
        }
    }
    return bubble


def build_info_bubble(text):
    """カルーセル先頭に置く説明バブル。テキストがカードと一緒に必ず表示されるようにする。"""
    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "justifyContent": "center",
            "spacing": "md",
            "paddingAll": "20px",
            "contents": [
                {"type": "text", "text": "📷 風景写真コンシェルジュ", "size": "md", "weight": "bold", "color": "#1DB446"},
                {"type": "separator", "margin": "md"},
                {"type": "text", "text": text, "wrap": True, "size": "xl", "weight": "bold", "color": "#222222", "margin": "lg"},
                {"type": "text", "text": "→ 右にスワイプ", "size": "sm", "color": "#AAAAAA", "margin": "lg", "align": "end"},
            ],
        },
    }


def expand_menu_options(enable_peak=False):
    """統一メニューの選択肢リスト(順序が番号に対応)。撮り頃が明確で時期外れのときだけ peak を含める。
    「両方広げる」は廃止（期間→地域と順に押せば同じ状態に到達でき、選択肢を絞って分かりやすくする）。"""
    opts = ['time', 'area']
    if enable_peak:
        opts.append('peak')
    opts.append('cancel')
    return opts

def expand_menu_text(lead, options, peak_text=None, empty_actions=None, area_label=None):
    """統一メニューの本文を作る。options は expand_menu_options() の戻り値。
    empty_actions に含む選択肢には『（今は該当なし）』を付す(時期が近づけば外れる)。
    area_label を渡すと「地域を広げて探す」を、その文言（次にどこまで広げるか）に差し替える。"""
    empty_actions = empty_actions or []
    labels = {
        'time': "期間を広げて探す",
        'area': area_label or "地域を広げて探す",
        'both': "両方広げて探す",
        'peak': (f"撮り頃の作品を見る（{peak_text}ごろ）" if peak_text else "撮り頃の作品を見る"),
        'cancel': "やめる（別の条件で探す）",
    }
    lines = [lead, "どうしますか？"]
    for i, o in enumerate(options, 1):
        suffix = "（今は該当なし）" if o in empty_actions else ""
        lines.append(f"{i}. {labels[o]}{suffix}")
    return "\n".join(lines)


def expand_menu_quick_reply(options, peak_text=None, empty_actions=None, area_label=None):
    """統一メニューのクイックリプライ（タップ式ボタン）。タップすると対応する番号テキストを送り、
    既存の番号ハンドラがそのまま処理する（番号入力との併存）。これによりメニュー到着前に番号を
    押す事故が起きにくくなる。『今は該当なし』の選択肢はタップ不可とするためボタンを出さない
    （テキスト側には注記が残る）。LINEのラベル上限に合わせ20字で切る。
    area_label を渡すと「地域を広げて探す」を、その文言（次にどこまで広げるか）に差し替える。"""
    empty_actions = empty_actions or []
    labels = {
        'time': "期間を広げて探す",
        'area': area_label or "地域を広げて探す",
        'both': "両方広げて探す",
        'peak': (f"撮り頃の作品を見る（{peak_text}ごろ）" if peak_text else "撮り頃の作品を見る"),
        'cancel': "やめる",
    }
    items = []
    for i, o in enumerate(options, 1):
        if o in empty_actions:
            continue
        items.append(QuickReplyButton(action=MessageAction(label=labels[o][:20], text=str(i))))
    return QuickReply(items=items) if items else None


# 県の略称＝同名市があるケースの「狭→広」段階。市→県→隣県→全国の順に広げる。
STAGED_SCOPES = ['city', 'pref', 'neighbor', 'nation']

def _staged_terms(stage, pref, city):
    if stage == 'city':
        return [city]
    if stage == 'pref':
        return [pref]
    if stage == 'neighbor':
        return [pref] + PREF_NEIGHBORS.get(pref, [])
    return []  # nation = 全国（テキスト絞り込みなし）

def reply_staged_area(reply_token, user_id, stage, subject, pref, city, date_, ol, on, expand_time=False,
                      specified=False, granularity=None):
    """県の略称と同名の市があるケース(例「静岡」)を、市→県→隣県→全国と段階的に広げて返す。
    常に上限内・近い順の代表のみを見せ、各段にメニューを添えて段階的に辿れるようにする。"""
    center = ol or SHINJUKU
    terms = _staged_terms(stage, pref, city)
    pr = search_by_place(terms, base_date=date_, origin_latlng=ol, origin_name=on,
                         subject=subject, center_latlng=center, radius_km=3000, expand_time=expand_time)
    speaks = pr.get('peaks', [])
    subjlabel = f"{subject}の" if subject else ""
    sname = city.replace('市', '')
    _phr = period_phrase(date_=date_, specified=specified, granularity=granularity)  # 「今の時期」or「◯月」等
    idx = STAGED_SCOPES.index(stage)
    can_widen = idx < len(STAGED_SCOPES) - 1
    # 期間は使い切り: 一度広げたら(expand_time=True)「期間」は出さない（同じ結果の空回り防止）。
    # 地域(area)は市→県→隣県→全国の段階展開なので、行き着くまで(can_widen)残す。
    # 「両方広げる」は廃止（期間→地域と順に押せば同じ状態に到達できるため、選択肢を絞る）。
    if expand_time:
        opts = (['area'] if can_widen else []) + ['cancel']
    else:
        opts = ['time'] + (['area'] if can_widen else []) + ['cancel']
    # scope_disp=現在の範囲表示、_area_label=「地域を広げる」を押した先の行き先（押す前に分かるように）、
    # widen_hint=その行き先ラベルを引用した案内（本文とボタンの文言を一致させる）
    if stage == 'city':
        scope_disp = f"「{city}」"; _area_label = f"{pref}で調べる"
        widen_hint = f"{pref}全体に広げるなら「{_area_label}」を選んでください。"
    elif stage == 'pref':
        scope_disp = f"「{pref}」"; _area_label = "隣県まで広げて調べる"
        widen_hint = f"近隣の県も含めるなら「{_area_label}」を選んでください。"
    elif stage == 'neighbor':
        scope_disp = f"「{pref}」と近隣の県"; _area_label = "全国で調べる"
        widen_hint = f"全国まで広げるなら「{_area_label}」を選んでください。"
    else:
        scope_disp = "全国"; _area_label = None; widen_hint = ""
    # 初回か「広げた後」かでリード文を切り替える（初回のみ「お出かけですか？」、広げ後は何を広げたかを述べる）
    _time_widened = expand_time
    _area_widened = (stage != 'city')  # 初回は必ず city。stage が進んでいれば地域を広げた後
    # リード冒頭の出し分け:
    #  ・初回: 「お出かけですか？まず〇〇で調べたところ、」
    #  ・期間を広げた: 「期間を広げて調べたところ、〇〇で」（場所は変わらないので、何をしたかを述べる）
    #  ・地域だけ広げた: 「〇〇で調べたところ、」（今いる場所を端的に。地域を広げる選択肢は既に行き先表示済み）
    if _time_widened:
        _lead_open = f"期間を広げて調べたところ、{scope_disp}で"
    elif _area_widened:
        _lead_open = f"{scope_disp}で調べたところ、"
    else:
        _lead_open = f"{sname}に{subjlabel}撮影にお出かけですか？まず{scope_disp}で調べたところ、"
    _lead_phr = "" if _time_widened else f"{_phr}に撮影された"  # 期間を広げた後は「今の時期に」を言わない
    _pend = {'kind': 'staged_area', 'stage': stage, 'subject': subject, 'pref': pref,
             'city': city, 'date': date_, 'origin_latlng': ol, 'origin_name': on, 'options': opts,
             'specified': specified, 'granularity': granularity, 'expanded_time': expand_time}
    peaknote = f"（撮り頃は{peaks_text(speaks)}ごろ）" if (subject in SEASONAL_SUBJECTS and speaks) else ""
    if pr['status'] == 'not_found':
        lead = f"{_lead_open}{_lead_phr}{subjlabel}作品は見つかりませんでした。{widen_hint}"
        RESULT_PENDING[user_id] = _pend
        line_bot_api.reply_message(reply_token, TextSendMessage(
            text=expand_menu_text(lead, opts, area_label=_area_label),
            quick_reply=expand_menu_quick_reply(opts, area_label=_area_label)))
        return
    # 季節もの×季節外れ: 在庫(別季節の作品)を並べず、根拠つきリード＋「撮り頃の作品を見る」へ誘導
    if pr['status'] == 'off_season' and subject in SEASONAL_SUBJECTS and speaks:
        _peak_date, _peak_lbl = next_peak_date(speaks)
        if expand_time:
            opts_peak = (['area'] if can_widen else []) + ['peak', 'cancel']
        else:
            opts_peak = ['time'] + (['area'] if can_widen else []) + ['peak', 'cancel']
        _pend['options'] = opts_peak
        _pend['peak_months'] = speaks
        reason = peak_reason_text(f"ちなみに{scope_disp}", subject, speaks)
        lead = f"{_lead_open}{_lead_phr}{subjlabel}作品は見つかりませんでした。{reason}"
        _empty = time_widen_empty_actions(terms, date_, ol, on, subject, center_latlng=center, radius_km=3000)
        _pend['empty_actions'] = _empty
        RESULT_PENDING[user_id] = _pend
        line_bot_api.reply_message(reply_token, TextSendMessage(
            text=expand_menu_text(lead, opts_peak, peak_text=_peak_lbl, empty_actions=_empty, area_label=_area_label),
            quick_reply=expand_menu_quick_reply(opts_peak, peak_text=_peak_lbl, empty_actions=_empty, area_label=_area_label)))
        return
    results = pr['results']
    count = len(results)
    if stage == 'nation':
        shead = f"全国の{subjlabel}作品を、近い順にご紹介します{peaknote}。"
        if _time_widened:
            mlead = f"期間を広げて調べたところ、全国の{subjlabel}作品を近い順にご紹介しました。"
        else:
            mlead = f"全国の{subjlabel}作品を近い順にご紹介しました。"
    elif _time_widened:
        shead = f"期間を広げて調べたところ、{scope_disp}の{subjlabel}作品です{peaknote}。"
        mlead = f"{_lead_open}{_lead_phr}{subjlabel}作品は{count}件でした。{widen_hint}"
    elif _area_widened:
        shead = f"{scope_disp}で、{_phr}に撮影された{subjlabel}作品はこちらです{peaknote}。"
        mlead = f"{_lead_open}{_lead_phr}{subjlabel}作品は{count}件でした。{widen_hint}"
    else:  # 初回（city）
        shead = f"まず{scope_disp}で、{_phr}に撮影された{subjlabel}作品はこちらです{peaknote}。"
        mlead = f"{_lead_open}{_lead_phr}{subjlabel}作品は{count}件でした。{widen_hint}"
    # 段階探索では常にメニューを添えて段階的に辿れるようにする（上限内・近い順の代表のみ）
    RESULT_PENDING[user_id] = _pend
    reply_with_carousel(reply_token, shead, results, menu_text=expand_menu_text(mlead, opts, area_label=_area_label),
                        menu_quick_reply=expand_menu_quick_reply(opts, area_label=_area_label))


def save_plan_session(results):
    """カルーセル候補一覧を Firestore PlanSessions に保存し、planId を返す。
    プランナーページで複数候補を比較表示するために使用。"""
    if not db or not results:
        return None
    try:
        plan_id = secrets.token_urlsafe(9)  # 12文字のURL安全なID
        from datetime import datetime, timezone
        items = []
        for _emoji, _label, it in results:
            items.append({
                "area": it.get('area', ''),
                "place": it.get('place', ''),
                "title": it.get('title', ''),
                "period": it.get('period', ''),
                "pub": str(it.get('pub', '')),
                "img": it.get('url', ''),
                "winner": it.get('winner', ''),
                "award": it.get('award', ''),
            })
        db.collection('PlanSessions').document(plan_id).set({
            "items": items,
            "created": firestore.SERVER_TIMESTAMP,
            "expires": datetime.now(timezone.utc) + timedelta(days=30),
        })
        return plan_id
    except Exception as e:
        print(f"[save_plan_session] error: {e}", file=sys.stderr)
        return None


def reply_with_carousel(reply_token, head_text, results, alt_text="撮影地のご提案", note_text=None, menu_text=None, base_date=None, region_text=None, menu_quick_reply=None):
    """説明文をカルーセルの先頭バブルに入れて返信する(テキストが画面外に流れて見落とされるのを防ぐ)。
    note_text があれば、カルーセルの後に参考情報のテキストメッセージを続けて送る。
    menu_text があれば、さらにその後に「もっと広げますか?」等のメニューを続けて送る。
    menu_quick_reply があれば、そのメニュー(最後のメッセージ)にタップ式ボタンを付ける。
    base_date を渡すと、結果や指定地が開放月外の閉山スポットに該当する場合に注意書きを添える。"""
    plan_id = save_plan_session(results) if len(results) > 1 else None
    bubbles = [build_carousel_bubble(it, e, l, matched_kw=it.get('matched_kw'), plan_id=plan_id, idx=i) for i, (e, l, it) in enumerate(results)]
    if head_text:
        bubbles = [build_info_bubble(head_text)] + bubbles
    carousel = FlexSendMessage(
        alt_text=alt_text,
        contents={"type": "carousel", "contents": bubbles},
        quick_reply=feedback_quick_reply(),
    )
    msgs = [carousel]
    if note_text:
        msgs.append(TextSendMessage(text=note_text))
    _caution = closed_spot_caution(region_text=region_text, results=results, base_date=base_date)
    if _caution:
        msgs.append(TextSendMessage(text=_caution))
    if menu_text:
        msgs.append(TextSendMessage(text=menu_text, quick_reply=menu_quick_reply) if menu_quick_reply
                    else TextSendMessage(text=menu_text))
    line_bot_api.reply_message(reply_token, msgs)


def format_published(pub):
    if not pub:
        return ''
    import re
    if re.match(r'^\d{4}N$', pub):
        return f"{pub[:4]}年風景写真祭入選作品"
    m = re.match(r'^(\d{4})(\d{2})(\d{2})$', pub)
    if m:
        year, m1, m2 = m.group(1), int(m.group(2)), int(m.group(3))
        if m2 == 0:
            return f"{year}年{m1}月号"
        else:
            return f"風景写真{year}年{m1}-{m2}月号"
    return pub

def normalize_award(award):
    if not award:
        return ''
    a = award.strip()
    title = 'タイトル賞' if 'タイトル' in a else ''
    if '最優秀' in a:
        base = '最優秀作品賞'
    elif '準優秀' in a or '準優勝' in a:
        base = '準優秀作品賞'
    elif '優秀' in a:
        base = '優秀作品賞'
    elif '佳作' in a:
        base = '佳作'
    elif '秀作' in a:
        base = '秀作'
    elif '奨励' in a:
        base = '奨励賞'
    else:
        base = a.split()[0] if a else ''
    return f"{base}　{title}".strip() if title else base

def build_city_to_pref():
    global CITY_TO_PREF
    if not db:
        return
    try:
        import re as _re
        from collections import defaultdict as _dd
        pref_map = _dd(set)
        for doc in db.collection('Master_Photos').stream():
            area = doc.to_dict().get('Area', '')
            pref = extract_pref(area)
            if not pref or not area:
                continue
            city_part = area.replace(pref, '').strip()
            if city_part:
                m = _re.match(r'(.+?[市区町村])', city_part)
                if m:
                    pref_map[m.group(1)].add(pref)
                    CITY_TO_LATLNG[m.group(1)] = PREF_LATLNG[pref]
                # 注: 以前は市区町村以外のバラ地名(例:「志賀高原」)も登録していたが、
                # それらは地点名検索(search_by_place)に回すため、ここでは登録しない。
        for city, prefs in pref_map.items():
            if len(prefs) == 1:
                CITY_TO_PREF[city] = next(iter(prefs))
            else:
                CITY_TO_PREF_MULTI[city] = list(prefs)
        print(f'[INFO] CITY_TO_PREF構築完了: {len(CITY_TO_PREF)}件, 同名地名: {len(CITY_TO_PREF_MULTI)}件')
    except Exception as e:
        print(f'[WARN] CITY_TO_PREF構築失敗: {e}')

build_city_to_pref()

# ──────────────── LINE Webhook ────────────────
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("[WARN] Invalid signature.")
        abort(400)
    except Exception as e:
        print(f"[ERROR] Webhook error: {e}")

    return 'OK', 200

@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):
    user_id = event.source.user_id
    lat = event.message.latitude
    lng = event.message.longitude
    city = format_loc_city(getattr(event.message, 'address', '') or '')
    hydrate_user(user_id)
    save_user_location(user_id, lat, lng, city)
    where = f"現在地（{city}）" if city else "現在地"
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=f"{where}を登録しました。この場所を起点に撮影地をご提案します。\n撮影したい日程や地域があればお知らせください。")
    )
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):

    reply_token = event.reply_token

    # 即座に「お待ちください」を送信
    user_id = event.source.user_id
    # Firestoreに保存済みのユーザー情報(位置・初回フラグ)をメモリへ復元
    hydrate_user(user_id)
    # 「使い方」「ヘルプ」でいつでも案内を表示（初回のみ全文、2回目以降は要約）
    if event.message.text.strip() in ("使い方", "つかいかた", "ヘルプ", "help", "Help"):
        if user_id not in USER_SEEN:
            # 初回: 歓迎メッセージ＋全文ガイド
            mark_user_seen(user_id)
            line_bot_api.reply_message(reply_token, [
                TextSendMessage(text="ようこそ風景写真コンシェルジュの部屋へ。ここでは『風景写真』の誌面を飾った数々の傑作とその生まれた場所へと皆さんをご案内します。"),
                *[TextSendMessage(text=t) for t in usage_guide_messages()]
            ])
        else:
            # 2回目以降: 短い案内のみ
            line_bot_api.reply_message(reply_token, TextSendMessage(
                text="地名（栃木県、美瑛）や被写体（滝、桜）を送ると撮影地をご提案します。\n"
                     "日付を添えることもできます（週末 京都、明日 滝）。\n\n"
                     "詳しい使い方は「コマンド」と送ってください。\n\n"
                     "📖 使い方ガイド\nhttps://reference.fukei-shashin.co.jp/guide?openExternalBrowser=1\n\n"
                     "📋 操作マニュアル\nhttps://reference.fukei-shashin.co.jp/manual?openExternalBrowser=1"
            ))
        return
    # 「コマンド」でコマンド一覧と用例を表示
    if event.message.text.strip() in ("コマンド", "こまんど", "コマンド一覧", "command"):
        line_bot_api.reply_message(reply_token, TextSendMessage(text=command_list_text()))
        return
    # データ削除コマンド(同意の撤回・記録消去)。検索として記録される前に処理する
    if event.message.text.strip() in ("データ削除", "データ消去", "記録削除"):
        delete_user_data(user_id)
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text="あなたの記録(検索された言葉・ご提案への評価・登録された位置情報)をすべて削除しました。\nご協力ありがとうございました。またいつでもご利用いただけます。")
        )
        return
    # 「検索中」表示は実際に検索が走るときだけ出す。メニューで「やめる」や範囲外の番号を
    # 選んだだけのときは検索しないので出さない。新規ワードや検索が走る選択(期間/地域/両方/撮り頃)では出す。
    _norm_txt = event.message.text.strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    _pure_digit = _norm_txt.isdigit()
    _in_pending = any(user_id in _d for _d in (RESULT_PENDING, EXPAND_PENDING, AMBIGUOUS_PENDING, SUBJECT_PENDING, ROUTE_PENDING, WARD_PENDING))
    _show_loading = True
    _mnum = re.match(r'^(\d+)', _norm_txt)
    if _mnum and user_id in RESULT_PENDING:
        _opts = RESULT_PENDING[user_id].get('options') or []
        _empty = RESULT_PENDING[user_id].get('empty_actions') or []
        _n = int(_mnum.group(1))
        _act = _opts[_n - 1] if 1 <= _n <= len(_opts) else None
        if _act not in ('time', 'area', 'both', 'peak') or _act in _empty:  # cancel/範囲外/該当なし = 検索なし
            _show_loading = False
    if _pure_digit and not _in_pending:
        _show_loading = False  # 保留メニューが無い数字のみ → 検索せず安全網へ
    if _show_loading:
        try:
            line_bot_api.push_message(user_id, TextSendMessage(text="少々お待ちください。ご指定の条件で風景写真データベースを調べています。🔍"))
        except:
            pass

    try:

        user_message = event.message.text.strip()
        # 利用状況の観察用に記録(制限はかけない)
        record_search(user_id, user_message)
        # 初回メッセージ時に短い歓迎を案内（全文ガイドは「使い方」コマンドに集約）
        if user_id not in USER_SEEN:
            mark_user_seen(user_id)
            from linebot.models import TextSendMessage as TSM
            line_bot_api.push_message(user_id, TSM(
                text="ようこそ風景写真コンシェルジュの部屋へ。\n"
                     "地名や被写体を送ると、『風景写真』の傑作が撮られた撮影地をご案内します。\n\n"
                     "使い方の詳細は「使い方」と送ってください。"
            ))

        # 安全網: どの保留メニューも無い状態で「数字のみ」が届いたとき（メニューが届く前に番号を
        # 押した等）、検索に流さず、しれっと次の操作を促す。どちらの間違いとも言わない。
        if _pure_digit and not _in_pending:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="地名や被写体名を入れて送ってください。"))
            return

        # 「@地名」コマンド: @に続く文字を必ず地名として検索する。
        # （辞書に無い地名や、川越・海老名のように地名内の単漢字が被写体に化けるケースの確実な回避策）
        _at = re.match(r'^[@＠]\s*(.+)$', user_message)
        if _at:
            for _pd in (SUBJECT_PENDING, EXPAND_PENDING, AMBIGUOUS_PENDING, ROUTE_PENDING, WARD_PENDING, RESULT_PENDING):
                _pd.pop(user_id, None)
            place_q = _at.group(1).strip()
            # @は地名専用。地名以外の語(被写体やつなぎ語)が紛れていても、地名部分だけで検索・表示する。
            _at_tokens = re.split(r'[\s　]+', place_q)
            if len(_at_tokens) >= 2:
                _kept = []
                for _tok in _at_tokens:
                    _is_subj = any(_tok == _c or _tok in _vs for _c, _vs in KEYWORD_NORMALIZE.items())
                    if _is_subj or _tok in FILLER_WORDS:
                        continue  # 被写体語・つなぎ語は地名から落とす
                    _kept.append(_tok)
                if _kept:
                    place_q = ' '.join(_kept).strip()
            _pp = parse_period(place_q)
            target_date = _pp['date']
            _u2 = USER_LOCATION.get(user_id)
            _ol2 = (_u2["lat"], _u2["lng"]) if _u2 else None
            _on2 = (_u2.get("city") or "現在地") if _u2 else DEFAULT_ORIGIN_NAME
            pr = search_by_place(place_q, base_date=target_date, origin_latlng=_ol2, origin_name=_on2)
            _note = famous_spots_note(region_text=place_q, origin_latlng=_ol2, base_date=target_date)
            _proximity = False
            if pr['status'] == 'not_found':
                # 地名そのものの作品が無い場合は、地点として解決し周辺(約80km)の作品を探す
                _pll, _pname, _conf = resolve_place(place_q)
                if _pll:
                    pr2 = search_by_place([], base_date=target_date, origin_latlng=_ol2, origin_name=_on2,
                                          center_latlng=_pll, radius_km=80)
                    if pr2['status'] != 'not_found' and pr2['results']:
                        pr = pr2
                        _proximity = True
            if pr['status'] == 'not_found':
                line_bot_api.reply_message(reply_token, TextSendMessage(
                    text=f"「{place_q}」に合う撮影地は見つかりませんでした。\n地名の表記を変えるか、被写体（滝・桜・紅葉など）でもお試しください。"
                         + (("\n\n" + _note) if _note else "")))
                return
            results = pr['results']
            if _proximity:
                head = f"「{place_q}」の周辺で撮られた作品を近い順にご紹介します。"
            elif pr['status'] == 'in_season':
                head = f"{period_phrase(_pp)}に「{place_q}」で撮影された作品はこちらです。"
            else:
                cur = f"{target_date.month}月{junkun(target_date.day) or ''}"
                _cur_sfx = "" if _pp['specified'] else f"（{cur}）"
                peaks = [c for c in pr.get('peaks', []) if (c // 3 + 1) != target_date.month]
                if peaks:
                    head = (f"「{place_q}」は{period_phrase(_pp)}{_cur_sfx}の作品が少ないようです。"
                            f"撮り頃は{peaks_text(peaks)}あたり。参考にこれまでの作品をご紹介します。")
                else:
                    head = f"「{place_q}」は{period_phrase(_pp)}の作品が見つかりませんでしたが、これまでの作品をご紹介します。"
            reply_with_carousel(reply_token, head, results, note_text=_note,
                                base_date=target_date, region_text=place_q)
            return

        # 統一メニューへの番号応答。番号はpendの options（該当なし含む全選択肢）の位置で決まり、
        # テキスト表示・ボタン送出・この変換の三者が同じ位置基準で一致する（番号は詰めない）。
        # 該当なし(empty_actions)の番号は検索せず「今は選べません」と返す。
        if user_id in RESULT_PENDING:
            pend = RESULT_PENDING[user_id]
            ch = user_message.strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
            m = re.match(r'^(\d+)', ch)
            if not m:
                del RESULT_PENDING[user_id]  # 番号以外は新規クエリとして続行
            else:
                opts = pend.get('options', ['time', 'area', 'cancel'])
                idx = int(m.group(1)) - 1
                if idx < 0 or idx >= len(opts):
                    line_bot_api.reply_message(reply_token, TextSendMessage(
                        text=f"1〜{len(opts)}の番号でお選びください。やめる場合は{len(opts)}番です。"))
                    return
                action = opts[idx]
                if action in (pend.get('empty_actions') or []):
                    # 「（今は該当なし）」の選択肢 → 検索せず、pendを残して再選択を促す
                    line_bot_api.reply_message(reply_token, TextSendMessage(
                        text="その番号は今は選べません。他の番号をお選びください。"))
                    return
                del RESULT_PENDING[user_id]
                if action == 'cancel':
                    line_bot_api.reply_message(reply_token, TextSendMessage(
                        text="承知しました。気になる地名や被写体があれば、いつでも送ってください。"))
                    return
                if pend.get('kind') == 'place_subject':
                    subj = pend['subject']; pterms = pend['place_terms']; disp = pend['place_disp']
                    pll = pend.get('place_latlng'); date_ = pend['date']
                    _ol = pend.get('origin_latlng'); _on = pend.get('origin_name')
                    if action == 'peak':
                        # 撮り頃で探す: 次に近い撮り頃へ時期を移して同条件で再検索
                        _nd, _lbl = next_peak_date(pend.get('peak_months') or [])
                        if not _nd:
                            line_bot_api.reply_message(reply_token, TextSendMessage(
                                text="撮り頃の情報が見つかりませんでした。別の条件でお試しください。"))
                            return
                        rr = search_by_place(pterms, base_date=_nd, origin_latlng=_ol, origin_name=_on, subject=subj)
                        if rr['status'] == 'not_found' or not rr['results']:
                            # 地名内に撮り頃の作品が無ければ、地点周辺(近い順)に広げて撮り頃の作品を出す
                            center = pll or _ol or SHINJUKU
                            rr = search_by_place([], base_date=_nd, origin_latlng=_ol, origin_name=_on,
                                                 subject=subj, center_latlng=center, radius_km=3000)
                        if rr['status'] == 'not_found' or not rr['results']:
                            line_bot_api.reply_message(reply_token, TextSendMessage(
                                text=f"撮り頃（{_lbl}ごろ）の{subj}の作品は見つかりませんでした。"))
                            return
                        head = f"{subj}の撮り頃は{_lbl}ごろです。その時期に「{disp}」周辺で撮影された{subj}の作品はこちらです。"
                        reply_with_carousel(reply_token, head, rr['results'], base_date=_nd, region_text=disp)
                        return
                    et = action in ('time', 'both')
                    widen_area = action in ('area', 'both')
                    if widen_area:
                        # 地域を広げる: 地名のしばりを外し、その地点から近い順に全国で被写体を探す
                        center = pll or _ol or SHINJUKU
                        rr = search_by_place([], base_date=date_, origin_latlng=_ol, origin_name=_on,
                                             subject=subj, center_latlng=center, radius_km=3000, expand_time=et)
                        if et:
                            head = f"「{disp}」にこだわらず期間も広げ、近い順に{subj}の作品を探しました。"
                        else:
                            head = f"「{disp}」にこだわらず、近い順に{subj}の作品を広げて探しました。"
                    else:
                        # 期間だけ広げる: 同じ地域で判定窓を前後およそ1.5か月に広げる
                        rr = search_by_place(pterms, base_date=date_, origin_latlng=_ol, origin_name=_on,
                                             subject=subj, expand_time=True)
                        head = f"「{disp}」で期間を広げて{subj}の作品を探しました。"
                    if rr['status'] == 'not_found' or not rr['results']:
                        line_bot_api.reply_message(reply_token, TextSendMessage(
                            text=f"広げて探しましたが、{subj}の作品は見つかりませんでした。別の地域や被写体でお試しください。"))
                        return
                    reply_with_carousel(reply_token, head, rr['results'])
                    return
                if pend.get('kind') == 'subject_only':
                    subj = pend['subject']; center = pend.get('center_latlng')
                    near_name = pend.get('near_name', '現在地'); rad = pend.get('radius', 150)
                    date_ = pend['date']; _ol = pend.get('origin_latlng'); _on = pend.get('origin_name')
                    if action == 'peak':
                        # 撮り頃で探す: 次に近い撮り頃へ時期を移し、圏内→無ければ全国を近い順で
                        _nd, _lbl = next_peak_date(pend.get('peak_months') or [])
                        if not _nd:
                            line_bot_api.reply_message(reply_token, TextSendMessage(
                                text="撮り頃の情報が見つかりませんでした。別の条件でお試しください。"))
                            return
                        rr = search_by_place([], base_date=_nd, origin_latlng=_ol, origin_name=_on,
                                             subject=subj, center_latlng=center, radius_km=rad)
                        if rr['status'] == 'not_found' or not rr['results']:
                            rr = search_by_place([], base_date=_nd, origin_latlng=_ol, origin_name=_on,
                                                 subject=subj, center_latlng=center, radius_km=3000)
                        if rr['status'] == 'not_found' or not rr['results']:
                            line_bot_api.reply_message(reply_token, TextSendMessage(
                                text=f"撮り頃（{_lbl}ごろ）の{subj}の作品は見つかりませんでした。"))
                            return
                        head = f"{subj}の撮り頃は{_lbl}ごろです。その時期の{subj}の作品を{near_name}から近い順にご紹介します。"
                        reply_with_carousel(reply_token, head, rr['results'], base_date=_nd)
                        return
                    et = action in ('time', 'both')
                    widen_area = action in ('area', 'both')
                    if widen_area:
                        # 地域を広げる: 全国を対象に、起点から近い順に並べる
                        rr = search_by_place([], base_date=date_, origin_latlng=_ol, origin_name=_on,
                                             subject=subj, center_latlng=center, radius_km=3000, expand_time=et)
                        if et:
                            head = f"全国の{subj}の作品を、期間も広げて{near_name}から近い順にご紹介します。"
                        else:
                            head = f"全国の{subj}の作品を、{near_name}から近い順にご紹介します。"
                    else:
                        # 期間だけ広げる: 近く(半径そのまま)で判定窓を前後およそ1.5か月に広げる
                        rr = search_by_place([], base_date=date_, origin_latlng=_ol, origin_name=_on,
                                             subject=subj, center_latlng=center, radius_km=rad, expand_time=True)
                        head = f"{near_name}の近くで期間を広げて{subj}の作品を探しました。"
                    if rr['status'] == 'not_found' or not rr['results']:
                        line_bot_api.reply_message(reply_token, TextSendMessage(
                            text=f"広げて探しましたが、{subj}の作品は見つかりませんでした。別の被写体でもお試しください。"))
                        return
                    reply_with_carousel(reply_token, head, rr['results'])
                    return
                if pend.get('kind') == 'staged_area':
                    stage = pend['stage']; subj = pend['subject']
                    pref = pend['pref']; city = pend['city']; date_ = pend['date']
                    _ol = pend.get('origin_latlng'); _on = pend.get('origin_name')
                    _sp = pend.get('specified', False); _gr = pend.get('granularity')
                    idx = STAGED_SCOPES.index(stage)
                    if action == 'peak':
                        # 撮り頃の作品を見る: 同じスコープのまま、次に近い撮り頃の時期で再表示
                        _nd, _lbl = next_peak_date(pend.get('peak_months') or [])
                        if not _nd:
                            line_bot_api.reply_message(reply_token, TextSendMessage(
                                text="撮り頃の情報が見つかりませんでした。別の条件でお試しください。"))
                            return
                        reply_staged_area(reply_token, user_id, stage, subj, pref, city, _nd, _ol, _on,
                                          specified=True, granularity='jun')
                        return
                    if action == 'time':
                        # 同じ範囲のまま期間を広げる
                        reply_staged_area(reply_token, user_id, stage, subj, pref, city, date_, _ol, _on,
                                          expand_time=True, specified=_sp, granularity=_gr)
                    else:
                        # 地域を広げる（市→県→隣県→全国）。期間は使い切り状態を引き継ぐ（both/既に使用済みなら維持）
                        nxt = STAGED_SCOPES[min(idx + 1, len(STAGED_SCOPES) - 1)]
                        _keep_time = (action == 'both') or pend.get('expanded_time', False)
                        reply_staged_area(reply_token, user_id, nxt, subj, pref, city, date_, _ol, _on,
                                          expand_time=_keep_time, specified=_sp, granularity=_gr)
                    return
                line_bot_api.reply_message(reply_token, TextSendMessage(
                    text="承知しました。別の条件でお試しください。"))
                return

        # 地域＋被写体が0件だったときの選択（1.条件を広げる 2.全国 3.戻る）
        if user_id in SUBJECT_PENDING:
            sp = SUBJECT_PENDING[user_id]
            ch = user_message.strip()
            if ch in ("1", "１"):
                del SUBJECT_PENDING[user_id]
                rr = search_by_place([], base_date=sp['date'], origin_latlng=sp['origin_latlng'],
                                     origin_name=sp['origin_name'], subject=sp['subject'],
                                     center_latlng=sp['place_latlng'], radius_km=100)
                if rr['status'] == 'not_found' or not rr['results']:
                    line_bot_api.reply_message(reply_token, TextSendMessage(
                        text=f"「{sp['place_disp']}」の周辺（約100km）にも{sp['subject']}の作品が見つかりませんでした。全国で探す場合はもう一度「{sp['place_disp']} {sp['subject']}」と送って2をお選びください。"))
                    return
                reply_with_carousel(reply_token, f"「{sp['place_disp']}」の周辺（約100km）で{sp['subject']}の作品をご紹介します。", rr['results'])
                return
            elif ch in ("2", "２"):
                del SUBJECT_PENDING[user_id]
                prn = search_by_place([], base_date=sp['date'], origin_latlng=sp['origin_latlng'], origin_name=sp['origin_name'], subject=sp['subject'])
                if prn['status'] == 'not_found':
                    line_bot_api.reply_message(reply_token, TextSendMessage(text=f"全国でも{sp['subject']}の作品が見つかりませんでした。"))
                    return
                speaks = prn.get('peaks', [])
                if sp['subject'] in SEASONAL_SUBJECTS and speaks:
                    head = f"全国の{sp['subject']}の作品です（撮り頃は{peaks_text(speaks)}ごろ）。"
                else:
                    head = f"全国の{sp['subject']}の作品をご紹介します。"
                reply_with_carousel(reply_token, head, prn['results'])
                return
            elif ch in ("3", "３", "戻る", "もどる"):
                del SUBJECT_PENDING[user_id]
                line_bot_api.reply_message(reply_token, TextSendMessage(text="承知しました。地域名や被写体（例：弘前 桜）をお知らせください。"))
                return
            else:
                del SUBJECT_PENDING[user_id]  # 番号以外は新規クエリとして続行

        # 目的地入力待ち（tコマンドで目的地が未確定だったとき）
        if user_id in ROUTE_PENDING:
            rp = ROUTE_PENDING[user_id]
            ch = user_message.strip()
            if ch in ("戻る", "もどる", "キャンセル", "中止", "やめる"):
                del ROUTE_PENDING[user_id]
                line_bot_api.reply_message(reply_token, TextSendMessage(
                    text="目的地の入力をやめました。地名や被写体（例：弘前 桜）をお知らせください。"))
                return
            _wc = ambiguous_ward_candidates(ch, rp["origin_latlng"])
            if _wc:
                del ROUTE_PENDING[user_id]
                ask_ward(reply_token, user_id, ch, _wc, "dest", rp["center"], rp["center_nm"],
                         rp["subject"], rp["radius"], rp["origin_latlng"], rp["origin_name"])
                return
            _dll, _dnm, _dconf = resolve_place(ch)
            if _dll is not None and _dconf:
                del ROUTE_PENDING[user_id]
                do_route_search(reply_token, rp["center"], rp["center_nm"], _dll, _dnm,
                                rp["subject"], rp["radius"], rp["origin_latlng"], rp["origin_name"])
                return
            line_bot_api.reply_message(reply_token, TextSendMessage(
                text=f"「{ch}」は確認できませんでした。目的地を市区町村名で入力してください（例：函館市、名古屋市中区）。やめる場合は『戻る』。"))
            return

        # 同名の区(中央区など)の選択待ち（番号 or 正式名テキストでも選べる。ボタンはPostbackで処理）
        if user_id in WARD_PENDING:
            wp = WARD_PENDING[user_id]
            ch = user_message.strip()
            if ch in ("戻る", "もどる", "キャンセル", "中止", "やめる"):
                del WARD_PENDING[user_id]
                line_bot_api.reply_message(reply_token, TextSendMessage(
                    text="選択をやめました。地名や被写体（例：弘前 桜）をお知らせください。"))
                return
            idx = None
            mnum = re.match(r'^\s*(\d{1,2})\s*$', ch)
            if mnum:
                i = int(mnum.group(1)) - 1
                if 0 <= i < len(wp["cands"]):
                    idx = i
            if idx is None:  # 正式名・部分一致でも選べるように
                for i, (full, _) in enumerate(wp["cands"]):
                    if ch and (ch == full or ch in full or full in ch):
                        idx = i
                        break
            if idx is not None:
                full, ll = wp["cands"][idx]
                finish_ward_choice(reply_token, user_id, full, ll)
                return
            line_bot_api.reply_message(reply_token, TextSendMessage(
                text="番号（例：2）でお選びください。やめる場合は『戻る』。"))
            return

        # 検索拡張の回答処理
        if user_id in EXPAND_PENDING:
            pending = EXPAND_PENDING[user_id]
            choice = user_message.strip()
            if choice in ['4', '４']:
                del EXPAND_PENDING[user_id]
                line_bot_api.reply_message(reply_token, TextSendMessage(text="別の地域やキーワードを入力してください。"))
                return
            del EXPAND_PENDING[user_id]
            expand_time = choice in ['1', '１', '3', '３']
            expand_area = choice in ['2', '２', '3', '３']
            _pref = pending.get('pref')
            # 地域を広げる → 県＋隣接県を対象に。広げない → 県内のみ。
            if expand_area and _pref in PREF_NEIGHBORS:
                _eallowed = {_pref} | set(PREF_NEIGHBORS.get(_pref, []))
            elif _pref in PREF_NEIGHBORS:
                _eallowed = {_pref}
            else:
                _eallowed = None
            _eu = USER_LOCATION.get(user_id)
            _eo = (_eu["lat"], _eu["lng"]) if _eu else None
            _en = (_eu.get("city") or "現在地") if _eu else DEFAULT_ORIGIN_NAME
            results = select_three_points(
                base_date=pending['date'],
                base_latlng=pending['latlng'],
                radius=None,
                place_name=pending['display'],
                keyword=pending['keyword'],
                expand_time=expand_time,
                origin_latlng=_eo,
                origin_name=_en,
                allowed_prefs=_eallowed,
            )
            if not results or isinstance(results, tuple):
                line_bot_api.reply_message(reply_token, TextSendMessage(text="条件を広げても見つかりませんでした。別の地域やキーワードをお試しください。"))
                return
            if expand_area and expand_time:
                _ehead = f"期間を広げ、{_pref}と近隣の県も含めて探しました。こんなところはいかがでしょう。"
            elif expand_area:
                _ehead = f"{_pref}と近隣の県も含めて探しました。こんなところはいかがでしょう。"
            else:
                _ehead = f"期間を広げて{_pref}で探しました。こんなところはいかがでしょう。"
            reply_with_carousel(reply_token, _ehead, results)
            return

        # ── 便利コマンド ──
        # 「<被写体>現在地<半径>」(例: アジサイ現在地100) / 「見頃<半径>」(例: 見頃150)
        _u = USER_LOCATION.get(user_id)
        _ccenter = (_u["lat"], _u["lng"]) if _u else SHINJUKU
        _cname = (_u.get("city") or "現在地") if _u else "東京"
        _co = (_u["lat"], _u["lng"]) if _u else None
        _con = (_u.get("city") or "現在地") if _u else DEFAULT_ORIGIN_NAME

        m_now = re.match(r'^\s*(.+?)\s*現在地\s*(\d+)\s*(?:km|キロ\S*)?\s*$', user_message)
        if m_now:
            subj_txt, radius = m_now.group(1), max(5, min(int(m_now.group(2)), 2000))
            _cs, _ = extract_subject(subj_txt)
            if _cs:
                rr = search_by_place([], base_date=date.today(), origin_latlng=_co, origin_name=_con,
                                     subject=_cs, center_latlng=_ccenter, radius_km=radius)
                if rr['status'] == 'not_found' or not rr['results']:
                    line_bot_api.reply_message(reply_token, TextSendMessage(
                        text=f"{_cname}から半径{radius}km圏内に{_cs}の作品が見つかりませんでした。半径を広げてお試しください。"))
                    return
                speaks = rr.get('peaks', [])
                if _cs in SEASONAL_SUBJECTS and speaks:
                    head = f"{_cname}から半径{radius}km圏内の{_cs}の作品です（撮り頃は{peaks_text(speaks)}ごろ）。近い順にご紹介します。"
                else:
                    head = f"{_cname}から半径{radius}km圏内の{_cs}の作品を近い順にご紹介します。"
                reply_with_carousel(reply_token, head, rr['results'])
                return
            # 被写体が認識できなければ通常処理へフォールスルー

        m_peak = re.match(r'^\s*(?:見頃|撮り頃|撮りごろ|みごろ)\s*(\d+)?\s*(?:km|キロ\S*)?\s*$', user_message)
        if m_peak:
            radius = max(5, min(int(m_peak.group(1) or 100), 2000))
            lst = subjects_in_peak_near(_ccenter, radius, date.today())
            if not lst:
                line_bot_api.reply_message(reply_token, TextSendMessage(
                    text=f"{_cname}から半径{radius}km圏内では、今が撮り頃の被写体が見つかりませんでした。半径を広げてお試しください。"))
                return
            lines = "\n".join(f"・{s}（撮り頃 {pk}・{n}件）" for s, pk, n in lst[:12])
            line_bot_api.reply_message(reply_token, TextSendMessage(
                text=f"{_cname}から半径{radius}km圏内で、今が撮り頃の被写体です。\n{lines}\n\n気になる被写体名を送ると撮影地をご案内します。"))
            return

        # 自宅(帰路の基準点)の登録: 「自宅 川越市」「帰宅先 ○○」
        m_home = re.match(r'^\s*(?:自宅|帰宅先|帰路先)\s*[:：]?\s*(.+?)\s*$', user_message)
        if m_home:
            hname = m_home.group(1).strip()
            hll = geocode(hname)
            if not hll:
                _an, _all, _ad = parse_target_area(hname)
                if _all:
                    hll = _all
            if not hll:
                line_bot_api.reply_message(reply_token, TextSendMessage(text=f"「{hname}」の場所が特定できませんでした。市区町村名でお試しください（例：自宅 川越市）。"))
                return
            save_user_home(user_id, hll[0], hll[1], hname)
            line_bot_api.reply_message(reply_token, TextSendMessage(text=f"自宅を「{hname}」に登録しました。『現在地r』や『茅野r』のように送ると、起点から{hname}方向（帰り道）の撮影地を寄り道の少ない順にご案内します。半径は『現在地r150』のように付けられます。"))
            return

        # ルートコマンド: r=帰宅(目的地=登録した自宅)、t=目的地指定(その場限り)
        #   r: 「[起点]S[被写体]r[半径]」      例: 茅野s滝r / 現在地r150 / 美瑛r
        #   r<地名>: その地名を自宅として登録(上書き)し、今回もそこへ向かう  例: r板橋区 / 茅野s滝r板橋区
        #   t: 「[起点]S[被写体]t[半径][目的地]」例: 茅野s滝t函館市 / 現在地t名古屋栄 / 美瑛s桜t札幌150
        #   起点は現在地(省略時)または地名。半径省略時は起点→目的地の距離(×1.15)。
        #   r で自宅未登録&地名なし → r<地名>での登録を案内。t で目的地が未指定/未確定 → ROUTE_PENDING で入力待ち。
        m_route = re.match(r'^\s*(.*?)([RＲｒrTＴｔt])(.*)$', user_message)
        if m_route:
            pre, marker, after = m_route.group(1), m_route.group(2), m_route.group(3)
            is_home = marker in 'RＲｒr'
            _cs, _rem = extract_subject(pre)
            start_txt = re.sub(r'現在地|[\s　]+', '', _rem)
            num_m = re.search(r'(\d{1,4})', after)
            radius = int(num_m.group(1)) if num_m else None
            dest_txt = (after[:num_m.start()] + after[num_m.end():]) if num_m else after
            dest_txt = re.sub(r'(?:km|キロ\S*)', '', dest_txt)
            dest_txt = re.sub(r'[、,。.・/／｜|\s　]+', '', dest_txt).strip()
            # 起点(center)を決める: 空なら現在地、地名なら解決
            center = center_nm = None
            start_is_current = (start_txt == '')
            if start_is_current:
                if _u:
                    center, center_nm = _ccenter, _cname
            elif len(start_txt) >= 2:
                center, center_nm, _ = resolve_place(start_txt)
            # コマンド成立の意思判定（誤爆防止）
            if start_is_current:
                intent = (radius is not None or '現在地' in pre or _cs is not None or dest_txt != '')
            else:
                intent = (center is not None)  # 地名起点が解決できれば意思あり
            if intent:
                # r<地名>: その地名を自宅として登録(上書き)し、今回もそこへ向かう。
                #          現在地が無くても登録だけは行う。
                if is_home and len(dest_txt) >= 2:
                    _wc = ambiguous_ward_candidates(dest_txt, _co)
                    if _wc:
                        ask_ward(reply_token, user_id, dest_txt, _wc, "home",
                                 center, center_nm, _cs, radius, _co, _con)
                        return
                    _dll, _dnm, _dconf = resolve_place(dest_txt)
                    if _dll is None or not _dconf:
                        line_bot_api.reply_message(reply_token, TextSendMessage(
                            text=f"「{dest_txt}」は確認できませんでした。『r板橋区』のように市区町村名でお試しください。"))
                        return
                    save_user_home(user_id, _dll[0], _dll[1], _dnm)
                    note = f"自宅を「{_dnm}」に登録しました。次回からは末尾に『r』を付けるだけで帰り道をご案内します。\n"
                    if center is None:  # 現在地が無く今回の検索はできないが、登録は完了
                        line_bot_api.reply_message(reply_token, TextSendMessage(
                            text=note + "今回は起点（現在地）が分からないため帰り道の検索はできませんでした。位置情報を送るか『茅野r』のように起点を付けてお試しください。"))
                        return
                    do_route_search(reply_token, center, center_nm, _dll, _dnm, _cs, radius, _co, _con, note=note)
                    return
                if center is None:  # 現在地起点なのに位置情報なし
                    line_bot_api.reply_message(reply_token, TextSendMessage(
                        text="現在地が分からないため方向を計算できません。先にLINEの位置情報を送るか、起点の地名を付けて『茅野t函館市』のようにお試しください。"))
                    return
                if is_home:
                    # 地名なしの r → 登録済み自宅へ。未登録なら『r<地名>』での登録を案内。
                    _hu = USER_HOME.get(user_id)
                    if not _hu:
                        line_bot_api.reply_message(reply_token, TextSendMessage(
                            text="帰宅先（自宅）が未登録です。次に『r板橋区』のように市区町村名を付けて送れば、それを自宅として登録します（例：r板橋区）。登録後は末尾に『r』を付けるだけで、帰り道（自宅方向）の撮影地をご案内します。"))
                        return
                    do_route_search(reply_token, center, center_nm, (_hu["lat"], _hu["lng"]),
                                    _hu.get("name") or "自宅", _cs, radius, _co, _con)
                    return
                # 目的地指定(t): 確定できれば検索、できなければ入力待ち(勝手に倒さない)
                if len(dest_txt) >= 2:
                    _wc = ambiguous_ward_candidates(dest_txt, _co)
                    if _wc:
                        ask_ward(reply_token, user_id, dest_txt, _wc, "dest",
                                 center, center_nm, _cs, radius, _co, _con)
                        return
                    _dll, _dnm, _dconf = resolve_place(dest_txt)
                    if _dll is not None and _dconf:
                        do_route_search(reply_token, center, center_nm, _dll, _dnm, _cs, radius, _co, _con)
                        return
                    ROUTE_PENDING[user_id] = {"center": center, "center_nm": center_nm,
                                              "subject": _cs, "radius": radius,
                                              "origin_latlng": _co, "origin_name": _con}
                    line_bot_api.reply_message(reply_token, TextSendMessage(
                        text=f"「{dest_txt}」は確認できませんでした。目的地を市区町村名で入力してください（例：函館市、名古屋市中区）。"))
                    return
                ROUTE_PENDING[user_id] = {"center": center, "center_nm": center_nm,
                                          "subject": _cs, "radius": radius,
                                          "origin_latlng": _co, "origin_name": _con}
                line_bot_api.reply_message(reply_token, TextSendMessage(
                    text="目的地を市区町村名で入力してください（例：函館市、名古屋市中区）。"))
                return
            # コマンドでなければ通常処理へフォールスルー

        # 「[被写体]<地名><半径>」(例: 美瑛150 / 弘前 桜 100 / 美瑛 ひまわり 150)
        #  → その地名を中心に半径内の「今の時期に撮れる」撮影地を近い順に。地名が解決できる場合のみ発動。
        m_pl = re.match(r'^\s*(.+?)\s*(\d{2,4})\s*(?:km|キロ\S*)?\s*$', user_message)
        if m_pl:
            body, radius = m_pl.group(1), max(10, min(int(m_pl.group(2)), 2000))
            _cs, body = extract_subject(body)
            place_txt = re.sub(r'[、,。.・/／｜|\s　]+', ' ', body)
            place_txt = re.sub(r'現在地', ' ', place_txt).strip()
            center = center_name = None
            if len(place_txt) >= 2:
                center, center_name, _ = resolve_place(place_txt)
            if center is None and not place_txt and _cs and radius <= 999:
                center, center_name = _ccenter, _cname  # 地名なし＋被写体 → 現在地中心(年号誤認回避のため999km以下)
            if center is not None:  # 地名が解決できたときだけコマンドとして処理
                rr = search_by_place([], base_date=date.today(), origin_latlng=_co, origin_name=_con,
                                     subject=_cs, center_latlng=center, radius_km=radius)
                if rr['status'] == 'not_found' or not rr['results']:
                    line_bot_api.reply_message(reply_token, TextSendMessage(
                        text=f"{center_name}から半径{radius}km圏内に{(_cs or '撮影地')}が見つかりませんでした。半径を広げてお試しください。"))
                    return
                subj_txt = (_cs + "の") if _cs else ""
                speaks = rr.get('peaks', [])
                _note = famous_spots_note(subject=_cs, region_text=(center_name or ''), origin_latlng=_co, base_date=date.today())
                if rr['status'] == 'in_season':
                    head = f"{center_name}から半径{radius}km圏内で、今の時期に撮れる{subj_txt}撮影地を近い順にご紹介します。"
                elif _cs in SEASONAL_SUBJECTS and speaks:
                    head = f"{center_name}から半径{radius}km圏内は、今の時期の{subj_txt}作品が少なめです（{_cs}の撮り頃は{peaks_text(speaks)}ごろ）。これまでの作品を近い順にご紹介します。"
                else:
                    head = f"{center_name}から半径{radius}km圏内は、今の時期の作品が少なめでした。これまでの{subj_txt}作品を近い順にご紹介します。"
                reply_with_carousel(reply_token, head, rr['results'], note_text=_note)
                return
            # 地名が解決できなければ通常処理へフォールスルー

        # 問い返し待ちの回答処理
        _amb_keyword = None  # 同名地名の問い返しで「被写体として」を選んだ場合に確定する被写体
        if user_id in AMBIGUOUS_PENDING:
            pending = AMBIGUOUS_PENDING[user_id]
            prefs = pending["prefs"]
            city = pending["city"]
            kw_option = pending.get('kw_option')
            kw_num = str(len(prefs) + 1)
            choice = user_message.strip()
            resolved_pref = None
            if choice in ("1", "１") and prefs:
                resolved_pref = prefs[0]
            elif choice in ("2", "２") and len(prefs) >= 2:
                resolved_pref = prefs[1]
            else:
                for p in prefs:
                    short = re.sub(r'[都府県道]$', '', p)
                    if p in user_message or short in user_message:
                        resolved_pref = p
                        break
            if kw_option and choice == kw_num:
                # 被写体候補を選択
                del AMBIGUOUS_PENDING[user_id]
                _amb_keyword = kw_option[0]
                search_keyword = kw_option[0]
                _pp = parse_period(user_message); target_date = _pp['date']
                area_name, area_latlng, area_display = None, None, None
            elif resolved_pref:
                # 地域を確定（番号や県名で選択）
                del AMBIGUOUS_PENDING[user_id]
                latlng = geocode(f"{resolved_pref}{city}") or CITY_TO_LATLNG.get(city) or PREF_LATLNG.get(resolved_pref)
                _pp = parse_period(user_message); target_date = _pp['date']
                area_name, area_latlng, area_display = resolved_pref, latlng, city
            else:
                # 番号でも県名でもない → 新規クエリとして処理
                del AMBIGUOUS_PENDING[user_id]
                _pp = parse_period(user_message); target_date = _pp['date']
                area_name, area_latlng, area_display = parse_target_area(user_message)
        else:
            _pp = parse_period(user_message); target_date = _pp['date']
            area_name, area_latlng, area_display = parse_target_area(user_message)
        # 被写体（キーワード）を先に判定する。地名の部分一致（例：「桜」がさいたま市桜区に一致）に
        # 被写体を取られないよう、被写体語を除いた文字列で地名を取り直す。
        # まず、検出済みの地名（県名・市区町村名）は被写体判定の対象から外す
        # （「茨城」「神奈川」の“城/川”、「川越」「海老名」の“川/海”などを被写体と誤認しないため）。
        _msg_for_subj = user_message
        for _rm in (area_name, area_display):
            if isinstance(_rm, str) and _rm not in ('', 'AMBIGUOUS', '現在地'):
                _msg_for_subj = _msg_for_subj.replace(_rm, " ")
        if area_name in PREF_NEIGHBORS:
            _short = area_name if area_name == "北海道" else re.sub(r'[都府県]$', '', area_name)
            _msg_for_subj = _msg_for_subj.replace(_short, " ")
        _subj = detect_subject_longest(_msg_for_subj)
        if _amb_keyword:
            # 同名地名で「被写体として」を選んだ場合は、その被写体で確定（入力番号から再判定しない）
            _subj = _amb_keyword
            area_name, area_latlng, area_display = None, None, None
        if _subj and not _amb_keyword:
            _msg_wo_subj = user_message
            for v in KEYWORD_NORMALIZE.get(_subj, []):
                _msg_wo_subj = _msg_wo_subj.replace(v, ' ')
            _msg_wo_subj = re.sub(r'[、,。.・/／｜|\s　]+', ' ', _msg_wo_subj).strip()
            if len(_msg_wo_subj) >= 2:
                area_name, area_latlng, area_display = parse_target_area(_msg_wo_subj)
            else:
                area_name, area_latlng, area_display = None, None, None
        # キーワード抽出（被写体があればそれを採用。無い場合のみ全文から検出）
        search_keyword = _subj
        if not search_keyword and not (area_name and area_name not in [None, 'AMBIGUOUS']):
            search_keyword = detect_subject_longest(user_message)
        # 県の略称と同名の市があるケース（静岡・山梨など）。県/府も市も付けず単独略称で送られたら、
        # まず市(狭い)で答え、メニューの「地域を広げる」で市→県→隣県→全国と段階的に広げる（狭→広）。
        _short_pref = None
        _short_city = None
        if not _amb_keyword:
            for _pf, _ct in PREF_SAME_NAME_CITY.items():
                _sh = re.sub(r'[都府県]$', '', _pf)  # 末尾の都/府/県のみ除去（「京都府」→「京都」、「東京都」を誤って「京」にしない）
                if _sh in user_message and _pf not in user_message and _ct not in user_message:
                    _short_pref, _short_city = _pf, _ct
                    break
        if _short_pref:
            _u = USER_LOCATION.get(user_id)
            _ol = (_u["lat"], _u["lng"]) if _u else None
            _on = (_u.get("city") or "現在地") if _u else DEFAULT_ORIGIN_NAME
            reply_staged_area(reply_token, user_id, 'city', _subj, _short_pref, _short_city, target_date, _ol, _on,
                              specified=_pp['specified'], granularity=_pp['granularity'])
            return
        # 「地域名＋被写体」(例: 吉野山 桜 / 奈良、京都 滝 / 青森県 紅葉) → その地域・被写体で絞り込む。
        # 同名地名の問い返しより前に処理（被写体があれば地名はその語で直接検索でき、問い返し不要）。
        if _subj:
            txt = user_message
            for v in KEYWORD_NORMALIZE.get(_subj, []):
                txt = txt.replace(v, ' ')
            txt = re.sub(r'(撮り頃|撮りごろ|撮り|見頃|みごろ|時期|いつ|頃|ごろ)', ' ', txt)
            txt = re.sub(r'\d{1,2}月(?:上旬|中旬|下旬)?\d{0,2}日?|上旬|中旬|下旬|\d+日後|明日|あした|明後日|あさって|今日|本日|来週末|今週末|来週|今週|週末', ' ', txt)
            for _fw in FILLER_WORDS:
                txt = txt.replace(_fw, ' ')
            txt = re.sub(r'[、,。.・/／｜|\s　]+', ' ', txt)
            place_terms = []
            for tok in txt.split():
                tok = re.sub(r'^[のはをがでとへもに]+|[のはをがでとへもに]+$', '', tok).strip()
                if len(tok) >= 2:
                    place_terms.append(tok)
            place_terms = list(dict.fromkeys(place_terms))  # 重複除去・順序維持
            _u = USER_LOCATION.get(user_id)
            _ol = (_u["lat"], _u["lng"]) if _u else None
            _on = (_u.get("city") or "現在地") if _u else DEFAULT_ORIGIN_NAME
            place_disp = "・".join(place_terms)
            # ① 地域＋被写体（件数で出し分け: 0件=メニューのみ / 1〜3件=カルーセル+メニュー / 4件以上=カルーセルのみ）
            if place_terms:
                pr = search_by_place(place_terms, base_date=target_date, origin_latlng=_ol, origin_name=_on, subject=_subj)
                _note = famous_spots_note(subject=_subj, region_text=place_disp, origin_latlng=_ol, base_date=target_date)
                speaks = pr.get('peaks', [])
                _pend_ctx = {
                    'kind': 'place_subject', 'subject': _subj, 'place_terms': place_terms,
                    'place_disp': place_disp, 'place_latlng': area_latlng or geocode(place_terms[0]),
                    'date': target_date, 'origin_latlng': _ol, 'origin_name': _on, 'peak_months': speaks,
                }
                _peak_on = (_subj in SEASONAL_SUBJECTS and bool(speaks))
                _peak_date, _peak_lbl = next_peak_date(speaks) if _peak_on else (None, None)
                _opts = expand_menu_options(enable_peak=_peak_on)
                if pr['status'] in ('not_found', 'off_season'):
                    # 対象時期に該当なし → カルーセルは出さずメニューのみ（季節外の作品はメニューで広げて出す）
                    if pr['status'] == 'off_season':
                        hint = (peak_reason_text(f"ちなみに「{place_disp}」", _subj, speaks)
                                if (_subj in SEASONAL_SUBJECTS and speaks)
                                else "期間を広げると作品が見つかります。")
                        _lead = f"{period_phrase(_pp)}に「{place_disp}」で撮影された{_subj}の作品は見つかりませんでした。{hint}"
                        _empty = (time_widen_empty_actions(pterms, target_date, _ol, _on, _subj)
                                  if (_subj in SEASONAL_SUBJECTS and speaks) else [])
                    else:
                        _lead = (f"{period_phrase(_pp)}に「{place_disp}」で撮影された{_subj}の作品は見つかりませんでした。\n"
                                 f"再度検索する場合は地域を広げて探すことをおすすめします。")
                        _empty = []
                    RESULT_PENDING[user_id] = dict(_pend_ctx, options=_opts, empty_actions=_empty)
                    line_bot_api.reply_message(reply_token, TextSendMessage(
                        text=expand_menu_text(_lead, _opts, peak_text=_peak_lbl, empty_actions=_empty) + (("\n\n" + _note) if _note else ""),
                        quick_reply=expand_menu_quick_reply(_opts, peak_text=_peak_lbl, empty_actions=_empty)))
                    return
                results = pr['results']
                count = len(results)
                if _subj in SEASONAL_SUBJECTS and speaks:
                    shead = f"{period_phrase(_pp)}に「{place_disp}」で撮影された{_subj}の作品はこちらです（撮り頃は{peaks_text(speaks)}ごろ）。"
                else:
                    shead = f"{period_phrase(_pp)}に「{place_disp}」で撮影された{_subj}の作品はこちらです。"
                # 1〜3件 → カルーセル＋「もっと広げますか?」メニュー / 4件以上 → カルーセルのみ
                if count <= 3:
                    RESULT_PENDING[user_id] = dict(_pend_ctx, options=_opts)
                    _mlead = f"{period_phrase(_pp)}の「{place_disp}」の{_subj}は{count}件でした。もっと広げて探せます。"
                    reply_with_carousel(reply_token, shead, results, note_text=_note,
                                        menu_text=expand_menu_text(_mlead, _opts, peak_text=_peak_lbl),
                                        menu_quick_reply=expand_menu_quick_reply(_opts, peak_text=_peak_lbl),
                                        base_date=target_date, region_text=place_disp)
                else:
                    reply_with_carousel(reply_token, shead, results, note_text=_note,
                                        base_date=target_date, region_text=place_disp)
                return
            # 地名なしの被写体のみ → 現在地(既定は東京)中心・半径150kmで近い順に探す。件数で出し分け、足りなければメニューで広げる
            center = _ol or SHINJUKU
            RADIUS_SUBJ = 150
            near_name = _on if _ol else "東京"
            prn = search_by_place([], base_date=target_date, origin_latlng=_ol, origin_name=_on, subject=_subj, center_latlng=center, radius_km=RADIUS_SUBJ)
            speaks = prn.get('peaks', [])
            _note_subj = famous_spots_note(subject=_subj, origin_latlng=_ol, base_date=target_date)
            _pend_ctx = {
                'kind': 'subject_only', 'subject': _subj, 'center_latlng': center,
                'near_name': near_name, 'radius': RADIUS_SUBJ, 'date': target_date,
                'origin_latlng': _ol, 'origin_name': _on, 'peak_months': speaks,
            }
            _peak_on = (_subj in SEASONAL_SUBJECTS and bool(speaks))
            _peak_date, _peak_lbl = next_peak_date(speaks) if _peak_on else (None, None)
            _opts = expand_menu_options(enable_peak=_peak_on)
            if prn['status'] == 'in_season':
                results = prn['results']
                count = len(results)
                if _subj in SEASONAL_SUBJECTS and speaks:
                    shead = f"{period_phrase(_pp)}に{near_name}から半径{RADIUS_SUBJ}km圏内で撮影された{_subj}の作品はこちらです（撮り頃は{peaks_text(speaks)}ごろ）。"
                else:
                    shead = f"{period_phrase(_pp)}に{near_name}から半径{RADIUS_SUBJ}km圏内で撮影された{_subj}の作品はこちらです。"
                if count <= 3:
                    RESULT_PENDING[user_id] = dict(_pend_ctx, options=_opts)
                    _mlead = f"{period_phrase(_pp)}に{near_name}から半径{RADIUS_SUBJ}km圏内で見つかった{_subj}は{count}件でした。もっと広げて探せます。"
                    reply_with_carousel(reply_token, shead, results, note_text=_note_subj,
                                        menu_text=expand_menu_text(_mlead, _opts, peak_text=_peak_lbl),
                                        menu_quick_reply=expand_menu_quick_reply(_opts, peak_text=_peak_lbl),
                                        base_date=target_date)
                else:
                    reply_with_carousel(reply_token, shead, results, note_text=_note_subj,
                                        base_date=target_date)
                return
            # 対象時期に圏内で該当なし(0件 または 季節外) → メニューのみ（「地域を広げる」で全国を近い順に、季節外は期間を広げて出す）
            if prn['status'] == 'off_season':
                hint = (peak_reason_text("この圏内", _subj, speaks)
                        if (_subj in SEASONAL_SUBJECTS and speaks)
                        else "期間を広げると圏内に作品が見つかります。")
                _lead = f"{period_phrase(_pp)}に{near_name}から半径{RADIUS_SUBJ}km圏内で撮影された{_subj}の作品は見つかりませんでした。{hint}"
                _empty = (time_widen_empty_actions(None, target_date, _ol, _on, _subj, center_latlng=center, radius_km=RADIUS_SUBJ)
                          if (_subj in SEASONAL_SUBJECTS and speaks) else [])
            else:
                _lead = (f"{period_phrase(_pp)}に{near_name}から半径{RADIUS_SUBJ}km圏内で撮影された{_subj}の作品は見つかりませんでした。\n"
                         f"再度検索する場合は地域を広げて探すことをおすすめします。")
                _empty = []
            RESULT_PENDING[user_id] = dict(_pend_ctx, options=_opts, empty_actions=_empty)
            line_bot_api.reply_message(reply_token, TextSendMessage(
                text=expand_menu_text(_lead, _opts, peak_text=_peak_lbl, empty_actions=_empty) + (("\n\n" + _note_subj) if _note_subj else ""),
                quick_reply=expand_menu_quick_reply(_opts, peak_text=_peak_lbl, empty_actions=_empty)))
            return

        # 同名地名の問い返し
        if area_name == "AMBIGUOUS":
            prefs = CITY_TO_PREF_MULTI.get(area_display, [])
            # キーワード候補があるか確認
            keyword_variants = {
                '朝日': ('朝焼け', '朝日（風景・被写体）'),
                '桜': ('桜', '桜（花）'),
            }
            kw_option = keyword_variants.get(area_display) or keyword_variants.get(re.sub(r'[市区町村郡]', '', area_display).strip())
            AMBIGUOUS_PENDING[user_id] = {"city": area_display, "prefs": prefs, "kw_option": kw_option}
            msg = TextSendMessage(
                text=f"{area_display}は複数の地域にあります。\n" + "\n".join(f"{i+1}．{p}{area_display}" for i, p in enumerate(prefs)) + (f"\n{len(prefs)+1}．{kw_option[1]}" if kw_option else "") + "\n\n番号でお答えください。"
            )
            line_bot_api.reply_message(reply_token, msg)
            return

        city_specified = any(c in user_message for c in ["市","町","村","区","郡"])

        # 地域・キーワードに解決できない具体的な語は「地点名検索」を試みる(無関係な全国結果を出さない)
        place_query = None
        if not area_name and not search_keyword and not city_specified:
            residual = user_message.strip()
            for w in ['明日','あした','明後日','あさって','今日','本日','今週末','来週末','来週','今週','週末']:
                residual = residual.replace(w, '')
            residual = re.sub(r'\d+日後', '', residual)
            residual = re.sub(r'\d{1,2}月\d{1,2}日', '', residual)
            residual = re.sub(r'\d{1,2}月(?:上旬|中旬|下旬)?', '', residual)
            residual = re.sub(r'上旬|中旬|下旬', '', residual)
            for w in FILLER_WORDS:
                residual = residual.replace(w, '')
            residual = re.sub(r'[、,。.・/／｜|\s　]+', '', residual).strip()
            if len(residual) >= 2:
                place_query = residual
        # 距離の起点: 現在地(あれば市区町村名つき) / なければ新宿区。検索中心とは独立。
        _uloc = USER_LOCATION.get(user_id)
        if _uloc:
            origin_latlng = (_uloc["lat"], _uloc["lng"])
            origin_name = _uloc.get("city") or "現在地"
        else:
            origin_latlng = None
            origin_name = DEFAULT_ORIGIN_NAME

        if place_query:
            pr = search_by_place(place_query, base_date=target_date, origin_latlng=origin_latlng, origin_name=origin_name)
            _note = famous_spots_note(region_text=place_query, origin_latlng=origin_latlng, base_date=target_date)
            if pr['status'] == 'not_found':
                line_bot_api.reply_message(reply_token, TextSendMessage(
                    text=f"「{place_query}」に合う撮影地は見つかりませんでした。\n地域名(県名・市町村名)や被写体(滝・桜・紅葉・星空など)でもお試しください。"
                         + (("\n\n" + _note) if _note else "")))
                return
            results = pr['results']
            if pr['status'] == 'in_season':
                head = f"{period_phrase(_pp)}に「{place_query}」で撮影された作品はこちらです。"
            else:
                cur = f"{target_date.month}月{junkun(target_date.day) or ''}"
                _cur_sfx = "" if _pp['specified'] else f"（{cur}）"
                peaks = [c for c in pr.get('peaks', []) if (c // 3 + 1) != target_date.month]
                if peaks:
                    head = (f"「{place_query}」は{period_phrase(_pp)}{_cur_sfx}の作品が少ないようです。"
                            f"撮り頃は{peaks_text(peaks)}あたり。参考にこれまでの作品をご紹介します。")
                else:
                    head = f"「{place_query}」は{period_phrase(_pp)}の作品が見つかりませんでしたが、これまでの作品をご紹介します。"
            reply_with_carousel(reply_token, head, results, note_text=_note,
                                base_date=target_date, region_text=place_query)
            return


        # CITY_TO_PREFでヒットした場合（市町村名指定）はWIDE_PREFSスキップ
        city_from_dict = any(city in user_message or re.sub(r'[市区町村郡]', '', city) in user_message for city in CITY_TO_PREF)
        _radius = 150 if (city_specified or city_from_dict) else (300 if search_keyword else None)

        if area_name and area_name in WIDE_PREFS and not city_specified and not city_from_dict:
            msg = TextSendMessage(
                text=f"{area_name[:-1]}ですか。それは楽しみですね。どのあたりに行かれますか？市町村名や地域名を教えていただけますか。"
            )
            line_bot_api.reply_message(reply_token, msg)
            return
        if area_latlng is None and user_id in USER_LOCATION:
            loc = USER_LOCATION[user_id]
            area_latlng = (loc["lat"], loc["lng"])
            if not area_display:
                area_display = "現在地"
        elif area_latlng is None:
            pass  # 位置情報未登録時は何も言わない
        # 県名そのもの(例:「山梨県」)は市ではない。県のみ指定のときは市扱いにせず県内検索にする。
        # （「山梨県」に「山梨」(山梨市)が含まれる等の city_from_dict 誤判定で隣県が混ざるのを防ぐ）
        _is_bare_pref = (area_name in PREF_NEIGHBORS) and (area_display == area_name)
        target_city = None if _is_bare_pref else (area_display if (city_specified or city_from_dict) else None)
        # 県のみ指定(市区町村でない)のときは、まず県内だけを対象にする（足りなければ後で隣県に広げる）
        _allowed = {area_name} if (area_name in PREF_NEIGHBORS and not target_city) else None
        results = select_three_points(base_date=target_date, base_latlng=area_latlng, radius=_radius, place_name=area_display, keyword=search_keyword, target_city=target_city, origin_latlng=origin_latlng, origin_name=origin_name, allowed_prefs=_allowed)
        if isinstance(results, tuple) and results[0] == 'CITY':
            _, city_base, city_count, results = results
            if not results:
                line_bot_api.reply_message(reply_token, TextSendMessage(
                    text=f"{target_date.month}月{target_date.day}日の前後で{city_base}とその周辺を調べましたが、該当する作品が見つかりませんでした。\n時期や地域を変えてお試しください。"))
                return
            if city_count == 0:
                head = f"{target_date.month}月{target_date.day}日の前後で{city_base}を調べましたが該当はありませんでした。{city_base}周辺の候補をご紹介します。"
            elif city_count <= 3:
                head = f"{target_date.month}月{target_date.day}日の前後で{city_base}で調べたところ該当は{city_count}件でした。周辺の候補も合わせて表示します。"
            else:
                head = f"{period_phrase(_pp)}に「{city_base}」で撮影された作品はこちらです。"
            reply_with_carousel(reply_token, head, results,
                                base_date=target_date, region_text=city_base)
            return
        if isinstance(results, tuple) and results[0] == 'TOO_FEW':
            _, found_pref, count, few_results = results
            EXPAND_PENDING[user_id] = {
                'pref': found_pref,
                'date': target_date,
                'latlng': area_latlng,
                'display': area_display,
                'keyword': search_keyword,
            }
            _disp = area_display or found_pref
            _opts = expand_menu_options(enable_peak=False)  # 撮り頃オプションはステップ2で有効化
            if count == 0 or not few_results:
                # 0件 → メニューのみ
                _lead = f"{period_phrase(_pp)}に「{_disp}」で撮影された作品は見つかりませんでした。"
                line_bot_api.reply_message(reply_token, TextSendMessage(text=expand_menu_text(_lead, _opts),
                                                                        quick_reply=expand_menu_quick_reply(_opts)))
            else:
                # 1〜3件 → 県内の作品をカルーセルで出し、続けてメニュー
                _shead = f"{period_phrase(_pp)}に「{_disp}」で撮影された作品はこちらです。"
                _mlead = f"{period_phrase(_pp)}の「{_disp}」の作品は{count}件でした。もっと広げて探せます。"
                reply_with_carousel(reply_token, _shead, few_results,
                                    menu_text=expand_menu_text(_mlead, _opts),
                                    menu_quick_reply=expand_menu_quick_reply(_opts),
                                    base_date=target_date, region_text=_disp)
            return
        if not results:
            results = []
        masterpiece = results[0][2] if results else None
        near = results[1][2] if len(results) > 1 else None


        if not masterpiece or not near:
            msg = TextSendMessage(
                text="今の時期にぴったりの作品が見つかりませんでした。\n地域名やキーワード（例：滝、桜、紅葉）を変えてもう一度お試しください。位置情報を登録していただくと、お近くの撮影地もご提案できます。"
            )
            line_bot_api.reply_message(reply_token, msg)
            return

        _date_specified = _pp['specified']
        _note = famous_spots_note(subject=search_keyword, region_text=(area_display or area_name or ''),
                                  origin_latlng=origin_latlng, base_date=target_date)
        reply_with_carousel(
            reply_token,
            build_greeting(target_date, area_display, date_specified=_date_specified),
            results,
            alt_text="風景写真コンシェルジュ・今日の3選",
            note_text=_note,
            base_date=target_date,
            region_text=(area_display or area_name or ''),
        )


    except Exception as e:
        import traceback
        err = traceback.format_exc()
        sys.stderr.write(f"[ERROR] Exception in handle_message: {err}\n")
        try:
            msg = TextSendMessage(
                text="申し訳ございません。処理中にエラーが発生しました。"
            )
            line_bot_api.reply_message(reply_token, msg)
        except:
            pass

@handler.default()
def handle_default(event):
    """テキスト・位置情報・ポストバック以外(スタンプ・画像・友だち追加など)の
    フォールバック。SDK 2.4.3 では未対応イベントは _default に回る。
    返信できるイベント(reply_tokenあり)にだけ、使い方をやさしく案内する。"""
    reply_token = getattr(event, 'reply_token', None)
    if not reply_token:
        return  # Unfollow等、返信トークンが無いイベントは何もしない
    try:
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text="ありがとうございます。撮影したい『地域名』や『日程』、被写体の『キーワード』をテキストで送っていただくと、その場所にちなんだ作品をご提案します。\n例：「宮城県」「来週末 北海道」「滝」")
        )
    except Exception as e:
        print(f"[ERROR] handle_default error: {e}", flush=True)

@handler.add(PostbackEvent)
def handle_postback(event):
    reply_token = event.reply_token

    try:
        data = event.postback.data
        params = dict(item.split('=') for item in data.split('&'))
        action = params.get('action')
        pic_filename = params.get('pic', '')

        if action == 'ward':
            user_id = event.source.user_id
            wp = WARD_PENDING.get(user_id)
            try:
                i = int(params.get('i', '-1'))
            except ValueError:
                i = -1
            if wp and 0 <= i < len(wp["cands"]):
                full, ll = wp["cands"][i]
                finish_ward_choice(reply_token, user_id, full, ll)
            else:
                line_bot_api.reply_message(reply_token, TextSendMessage(
                    text="選択の有効期限が切れたようです。もう一度コマンドを送ってください。"))
            return

        if action == 'menu_concierge':
            line_bot_api.reply_message(reply_token, TextSendMessage(
                text="撮りたい被写体名や撮りに行きたい地域名を入力してください。\n\n"
                     "例：滝／桜／美瑛／栃木県 紅葉\n\n"
                     "📖 使い方の詳細は「使い方」と送ってください。"
            ))
            return

        if action == 'feedback':
            rating = params.get('rating', '')
            user_id = event.source.user_id
            last_query = ''
            if db:
                try:
                    snap = db.collection('Users').document(user_id).get()
                    if snap.exists:
                        last_query = (snap.to_dict() or {}).get('last_query', '')
                    db.collection('Feedback').add({
                        "user_id": user_id,
                        "rating": rating,
                        "query": last_query,
                        "ts": firestore.SERVER_TIMESTAMP,
                    })
                except Exception:
                    import traceback
                    print(f"[ERROR] feedback save failed: {traceback.format_exc()}", flush=True)
            line_bot_api.reply_message(reply_token, TextSendMessage(text="ありがとうございます。いただいた声は今後のご提案の参考にいたします。"))
            return

        if action == 'detail':
            # Master_Photosから写真情報を取得
            photo_data = None
            if db:
                dnumb = params.get('dnumb', '')
                if dnumb:
                    docs = db.collection('Master_Photos').where('dNumb', '==', dnumb).limit(1).stream()
                else:
                    docs = db.collection('Master_Photos').where('PicFileName', '==', pic_filename).limit(1).stream()
                for doc in docs:
                    photo_data = doc.to_dict()
                    break

            if not photo_data:
                line_bot_api.reply_message(reply_token, TextSendMessage(text="作品情報が見つかりませんでした。"))
            else:
                # Location masterから地域情報を取得
                loc_data = None
                dnumb = str(photo_data.get('dNumb', ''))
                if db and dnumb:
                    loc_docs = db.collection('Location master').where('Related_dNumb', '==', dnumb).limit(1).stream()
                    for doc in loc_docs:
                        loc_data = doc.to_dict()
                        break

                # 作品情報テキスト組み立て
                lines = []
                lines.append(f"📸 {photo_data.get('Title', '')}")
                if photo_data.get('SubTitle'):
                    lines.append(f"　{photo_data.get('SubTitle')}")
                lines.append(f"\n📍 {photo_data.get('Area', '')}")
                if photo_data.get('Place'):
                    lines.append(f"　{photo_data.get('Place')}")
                lines.append(f"\n👤 {photo_data.get('Winner', '')}")
                if photo_data.get('AwardRank'):
                    lines.append(f"🏅 {normalize_award(photo_data.get('AwardRank'))}")
                if photo_data.get('Published'):
                    lines.append(f"📖 {format_published(photo_data.get('Published', ''))}")
                if photo_data.get('Selection Comments'):
                    judge = photo_data.get('Judge', '')
                    comment = photo_data.get('Selection Comments', '')
                    lines.append(f'\n［選評］\n{comment}\n（{judge}）')

                if loc_data:
                    lines.append(f"\n━━━━━━━━━━")
                    lines.append(f"🗺 撮影地情報")
                    if loc_data.get('Best_Season'):
                        lines.append(f"🌸 ベストシーズン: {loc_data.get('Best_Season')}")
                    if loc_data.get('Best_Time'):
                        lines.append(f"🕐 ベスト時間: {loc_data.get('Best_Time')}")
                    if loc_data.get('Lighting'):
                        lines.append(f"💡 光の条件: {loc_data.get('Lighting')}")
                    if loc_data.get('Lens_Selection'):
                        lines.append(f"📷 レンズ: {loc_data.get('Lens_Selection')}")
                    if loc_data.get('Point_Description'):
                        lines.append(f"\n📝 ポイント\n{loc_data.get('Point_Description')}")
                    if loc_data.get('Access_Info'):
                        lines.append(f"\n🚗 アクセス・装備\n{loc_data.get('Access_Info')}")

                # MapLinkはカルーセルのマップボタンと同じため省略

                text = "\n".join(lines)
                # LINEのテキストメッセージは5000文字まで
                if len(text) > 4900:
                    text = text[:4900] + "..."
                line_bot_api.reply_message(reply_token, TextSendMessage(text=text))

        elif action == 'record':
            if db:
                route_data = {
                    'timestamp': date.today().isoformat(),
                    'pic_filename': pic_filename,
                    'user_id': event.source.user_id if hasattr(event.source, 'user_id') else 'unknown',
                }
                db.collection('Saved_Routes').add(route_data)

            msg = TextSendMessage(
                text="✨ ルート記録完了\nコンシェルジュの部屋に保存しました。"
            )
            line_bot_api.reply_message(reply_token, msg)

    except Exception as e:
        print(f"[ERROR] Postback handling error: {e}")
        msg = TextSendMessage(
            text="処理中にエラーが発生しました。"
        )
        line_bot_api.reply_message(reply_token, msg)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
