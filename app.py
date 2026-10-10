# -*- coding: utf-8 -*-
"""
風景写真コンシェルジュ
LINE Bot（Flask / Firestore）。『風景写真』入賞作品データから、
地域・被写体・時期に応じて撮影地を提案する。
被写体検索は KEYWORD_NORMALIZE 辞書＋最長一致。継続開発中。
"""
import os
import json
import gzip
import sys
import re
import math
import random
import secrets
import hashlib
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from collections import defaultdict, Counter
from flask import Flask, request, abort, jsonify, make_response
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, LocationMessage, PostbackEvent, TextSendMessage, FlexSendMessage, QuickReply, QuickReplyButton, PostbackAction, MessageAction, LocationAction
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

# ──────────────── 作品データの共有キャッシュ ────────────────
# Master_Photos(約14,700件)は、誌面データを入れ替えたときしか変わらない。
# それを検索のたびにFirestoreから読んでいたため、1回の検索で約14,700件の
# 読み取りが発生し、応答にも10数秒かかっていた(無料枠は1日5万件なので、
# 1日3〜4回の検索で使い切ってしまう)。
#
# 検索に使う17列だけを取り出してメモリに置き、以後はそれを使い回す。
# 同じ文字列は1つにまとめているので、消費はおよそ14MB。
# 中身は変えていないので、検索の答えは従来とまったく同じになる。
_PHOTO_FIELDS = ("Place", "Area", "Title", "Subject", "Winner", "Winner4Search",
                 "WinnerArea", "AwardRank", "PicFileName", "Published", "Month",
                 "Day", "Year", "dNumb", "MapLink", "Judge", "Judge4Search",
                 "Hour", "Weather")
_PHOTOS = None
_PHOTOS_AT = 0.0
_PHOTOS_TTL = 6 * 3600     # 6時間で読み直す

def build_photo_cache():
    """Master_Photos を一度だけ読んで、検索に使う列だけを手元に置く。
    失敗したら None を返す(その場合は前のものを使い続ける)。"""
    if not db:
        return None
    pool = {}
    def share(v):
        # 同じ文字(地域名・作者名など)は1つにまとめて、memoryを節約する
        if isinstance(v, str):
            return pool.setdefault(v, v)
        return v
    rows = []
    try:
        for doc in db.collection('Master_Photos').stream():
            d = doc.to_dict() or {}
            rows.append({f: share(d.get(f, '')) for f in _PHOTO_FIELDS})
    except Exception:
        import traceback
        print(f"[ERROR] build_photo_cache: {traceback.format_exc()}", flush=True)
        return None
    print(f"[INFO] photo cache built: {len(rows)}件 / 文字列 {len(pool)}種類", flush=True)
    return rows

# ──────────────── 索引の保存(起き抜けの全件読みを避ける) ────────────────
# Renderの無料プランはアクセスが途切れるとサービスが寝てしまい、起きるたびに
# 上のキャッシュを作り直すため、そのたびに約14,700件の読み取りが発生する。
# 1日に数回寝起きするだけで無料枠(1日5万件)に届いてしまう。
#
# そこで、作ったものをgzipで固めてFirestoreの photo_index に置いておく。
# 次に起きたインスタンスは、そこから数件の読み取りだけで復元できる。
# 24時間経ったら Master_Photos を読み直して置き換えるので、誌面データを
# 入れ替えても遅くとも翌日には反映される(すぐ反映したいときは /api/_reindex)。
_SNAP_COLL  = 'photo_index'   # 索引の置き場(専用コレクション)
_SNAP_CHUNK = 500_000         # 1件あたりの上限(Firestoreの1MB制限に対して余裕を取る)
_SNAP_TTL   = 24 * 3600       # 保存した索引を信用する時間
_SNAP_VER   = 2               # 形式を変えたらここを上げる(古い索引は自動で捨てられる)
                              # 2: 撮影計画のために Hour・Weather を加えた

def _snapshot_pack(rows):
    """索引をgzipで固めて返す。JSONにできない値が混じっていたら None を返す。"""
    table = []
    for r in rows:
        row = []
        for f in _PHOTO_FIELDS:
            v = r.get(f, '')
            if v is not None and not isinstance(v, (str, int, float, bool)):
                print(f"[WARN] 索引の保存を見送ります: {f} に {type(v).__name__} が入っています", flush=True)
                return None
            row.append(v)
        table.append(row)
    body = json.dumps({"fields": list(_PHOTO_FIELDS), "rows": table},
                      ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return gzip.compress(body, 6)

def _snapshot_unpack(blob):
    """固めた索引を元の形(辞書のリスト)に戻す。列が今と違えば None。
    memoryの山を低くするため、読み終えた行はその場で手放しながら進める。"""
    obj = json.loads(gzip.decompress(blob))
    if obj.get("fields") != list(_PHOTO_FIELDS):
        print("[INFO] 保存してある索引の列が今と違うので作り直します", flush=True)
        return None
    table = obj.get("rows") or []
    obj = None
    pool = {}
    rows = []
    for i in range(len(table)):
        row = table[i]
        table[i] = None               # 済んだ行はすぐ手放す(順番は変えない)
        if len(row) != len(_PHOTO_FIELDS):
            return None
        rows.append({f: (pool.setdefault(v, v) if isinstance(v, str) else v)
                     for f, v in zip(_PHOTO_FIELDS, row)})
    return rows

def save_photo_snapshot(rows):
    """索引をFirestoreに保存する。何が起きたかを dict で返す(確認用)。"""
    if not db:
        return {"saved": False, "reason": "Firestoreに繋がっていません"}
    if not rows or len(rows) < 1000:
        # 読み取りが途中で落ちたときの不完全な索引を保存してしまわないための歯止め
        return {"saved": False, "reason": f"件数が少なすぎます({len(rows or [])}件)"}
    blob = _snapshot_pack(rows)
    if blob is None:
        return {"saved": False, "reason": "JSONにできない値が混じっています"}
    parts = [blob[i:i + _SNAP_CHUNK] for i in range(0, len(blob), _SNAP_CHUNK)]
    stamp = int(time.time())
    try:
        col = db.collection(_SNAP_COLL)
        batch = db.batch()
        for i, p in enumerate(parts):
            batch.set(col.document(f"part{i}"),
                      {"ver": _SNAP_VER, "i": i, "n": len(parts),
                       "count": len(rows), "built_at": stamp, "data": p})
        batch.commit()
    except Exception:
        import traceback
        print(f"[ERROR] save_photo_snapshot: {traceback.format_exc()}", flush=True)
        return {"saved": False, "reason": "書き込みに失敗しました"}

    # ここから先の後片付けが失敗しても、保存そのものは成立している
    removed = 0
    try:
        keep = {f"part{i}" for i in range(len(parts))}
        for ref in col.list_documents():
            if ref.id.startswith("part") and ref.id not in keep:
                ref.delete()          # 分割数が減ったときに古い断片を残さない
                removed += 1
    except Exception:
        import traceback
        print(f"[WARN] 古い断片の後片付けに失敗: {traceback.format_exc()}", flush=True)
        removed = -1
    print(f"[INFO] 索引を保存: {len(rows)}件 / {len(blob):,}バイト / {len(parts)}分割", flush=True)
    return {"saved": True, "count": len(rows), "bytes": len(blob),
            "parts": len(parts), "removed": removed, "built_at": stamp}

def load_photo_snapshot(max_age=None):
    """保存してある索引を読み出す。無い・形式が古い・壊れているときは None。
    読み取りは保存件数(いまのところ2〜3件)だけで済む。
    max_age(秒)を渡すと、それより古い索引は展開する前に見送る。"""
    if not db:
        return None
    try:
        docs = list(db.collection(_SNAP_COLL).stream())
    except Exception:
        import traceback
        print(f"[ERROR] load_photo_snapshot: {traceback.format_exc()}", flush=True)
        return None
    if not docs:
        return None
    parts, n, count, stamp = {}, None, None, 0
    for doc in docs:
        d = doc.to_dict() or {}
        if d.get("ver") != _SNAP_VER:
            print("[INFO] 保存してある索引の形式が古いので作り直します", flush=True)
            return None
        blob = d.get("data")
        if isinstance(blob, bytearray):
            blob = bytes(blob)
        if not isinstance(blob, bytes):
            return None
        try:
            parts[int(d.get("i"))] = blob
        except (TypeError, ValueError):
            return None
        n = d.get("n")
        count = d.get("count")
        stamp = max(stamp, int(d.get("built_at") or 0))
    if not isinstance(n, int) or sorted(parts.keys()) != list(range(n)):
        print(f"[WARN] 索引の断片が揃っていません({len(parts)}/{n})。作り直します", flush=True)
        return None
    age = (time.time() - stamp) / 3600 if stamp else -1
    if max_age is not None and (not stamp or (time.time() - stamp) >= max_age):
        # 古いものは展開せずに見送る(展開はそれなりに手間がかかるため)
        print(f"[INFO] 保存してある索引は作成から{age:.1f}時間で古いため、読み直します", flush=True)
        return None
    try:
        rows = _snapshot_unpack(b"".join(parts[i] for i in range(n)))
    except Exception:
        import traceback
        print(f"[ERROR] 索引の復元に失敗: {traceback.format_exc()}", flush=True)
        return None
    if rows is None:
        return None
    if isinstance(count, int) and len(rows) != count:
        print(f"[WARN] 索引の件数が合いません({len(rows)}≠{count})。作り直します", flush=True)
        return None
    print(f"[INFO] 索引を復元: {len(rows)}件 / 読み取り{len(docs)}件 / 作成から{age:.1f}時間", flush=True)
    return {"rows": rows, "built_at": stamp, "reads": len(docs)}

def get_photos():
    """作品データを返す。無ければ作る。期限が切れていれば作り直す。
    返るリストは共有物なので、並べ替えるときは list() で写しを取ること。"""
    global _PHOTOS, _PHOTOS_AT
    now = time.time()
    if _PHOTOS is not None and (now - _PHOTOS_AT) < _PHOTOS_TTL:
        return _PHOTOS

    # ① 保存してある索引が新しければ、そこから復元する(読み取りは数件)
    snap = load_photo_snapshot(max_age=_SNAP_TTL)
    if snap:
        _PHOTOS, _PHOTOS_AT = snap["rows"], now
        return _PHOTOS

    # ② 無い・古いときだけ Master_Photos を全件読み、読めたら保存しておく
    built = build_photo_cache()
    if built is not None:
        _PHOTOS, _PHOTOS_AT = built, now
        save_photo_snapshot(built)
        return _PHOTOS

    # ③ 全件読みに失敗したときは、古くても保存してある索引で凌ぐ
    old = load_photo_snapshot()
    if old:
        print("[WARN] Master_Photos が読めないので、古い索引で凌ぎます", flush=True)
        _PHOTOS, _PHOTOS_AT = old["rows"], now
    return _PHOTOS if _PHOTOS is not None else []

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
# ── 会話の途中の状態 ──────────────────────────────────────────
# LINEで「番号でお答えください」と聞き返したあと、その答えを待っている状態。
# このプロセスの中だけに持っている。
#
# ★ ここが、動かし方（gunicorn）の決め方を縛っている。
#   プロセスを増やす（--workers 2 以上）と、同じ人の次の発言が別のプロセスに
#   届きうる。そのプロセスには聞き返した覚えが無いので、番号を送っても効かず、
#   利用者から見れば「無反応」になる。
#   同時に捌く数を増やしたいときは、プロセスではなくスレッドを増やすこと。
#       gunicorn app:app --workers 1 --threads 8
#   スレッドならこの状態はそのまま共有される。誌面データの写しや索引も
#   1人分で済むので、使うメモリも増えない。
#   どうしてもプロセスを増やすなら、その前にこれらを Firestore へ移すこと。
#                                                       （2026-10-10）
AMBIGUOUS_PENDING = {}
EXPAND_PENDING = {}  # 検索拡張待ち  # user_id -> {"city": "小国町", "prefs": ["熊本県", "山形県"]}
SUBJECT_PENDING = {}  # 地域＋被写体が0件のときの選択待ち
RESULT_PENDING = {}  # 件数分岐の統一メニュー待ち  # user_id -> {kind, options, subject, place_terms, ...}
ROUTE_PENDING = {}  # tコマンドで目的地が未確定のときの入力待ち  # user_id -> {center,center_nm,subject,radius}
WARD_PENDING = {}  # 同名の区(中央区など)の選択待ち  # user_id -> {cands,mode,center,...}
CATEGORY_PENDING = {}  # カテゴリ(「花」など)の候補選択待ち  # user_id -> {names:[...]}
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
    'ネモフィラ': ['ネモフィラ', 'ねもふぃら'],
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
# 被写体の上位カテゴリ。「花」のように、それ自体は被写体名でないが写真家が実際に使う括り。
# 撮影者は「今どんな花が撮れるか」という単位で考えるが、KEYWORD_NORMALIZE は個々の被写体名しか
# 持たないため、その差を埋める層。値は KEYWORD_NORMALIZE の正規キーであること。
SUBJECT_CATEGORIES = {
    '花': ['桜', '芝桜', '菜の花', '藤', 'ツツジ', '紫陽花', 'ひまわり',
           'コスモス', 'ラベンダー', 'ネモフィラ', 'ススキ'],
}

# カテゴリ語として受け付ける表記のゆれ。→ SUBJECT_CATEGORIES のキー
CATEGORY_ALIASES = {
    '花': '花', 'はな': '花', 'ハナ': '花', '花々': '花', 'お花': '花',
}


def detect_category(text):
    """text がカテゴリ語そのもの（前後の助詞・空白を除く）なら正規キーを返す。該当なしは None。
    部分一致にしないのは、「花火」「菜の花」等を巻き込まないため。"""
    t = re.sub(r'[\s　、,。.・]+', '', str(text or '')).strip()
    t = re.sub(r'^[のはをがでとへもに]+|[のはをがでとへもに]+$', '', t)
    return CATEGORY_ALIASES.get(t)


def category_members_in_peak(canon_list, center_latlng, radius_km, base_date=None):
    """カテゴリ内の被写体のうち、いま撮り頃のものを (被写体, 撮り頃ラベル, 件数) で返す。
    subjects_in_peak_near の結果をカテゴリで絞り込むだけなので、判定基準は既存と同じ。"""
    if not center_latlng:
        return []
    allow = set(canon_list or [])
    return [row for row in subjects_in_peak_near(center_latlng, radius_km, base_date)
            if row[0] in allow]


def category_next_peaks(canon_list, center_latlng, radius_km, base_date=None, limit=3):
    """カテゴリ内で『次に近い撮り頃』の被写体を返す。撮り頃の花が一つも無い季節（冬など）に、
    無いものは無いと言った上で次の見込みを案内するために使う。
    戻り値: [(被写体, 撮り頃ラベル, date), ...] を日付の近い順で最大limit件。"""
    if not db or not center_latlng:
        return []
    base = base_date or date.today()
    try:
        excl_authors, blocked_areas = load_exclusions()
    except Exception:
        excl_authors, blocked_areas = set(), []
    allow = set(canon_list or [])
    bins = defaultdict(Counter)
    try:
        for d in get_photos():
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
            for canon in allow:
                variants = KEYWORD_NORMALIZE.get(canon, [canon])
                if subject_matches(variants, title=title, place=place, area=area,
                                   subject_field=sfield, exclude=subject_exclude_for(canon)):
                    bins[canon][bi] += 1
    except Exception:
        import traceback
        print(f"[ERROR] category_next_peaks: {traceback.format_exc()}", flush=True)
        return []
    out = []
    for canon, bc in bins.items():
        peaks = compute_peaks(bc)
        if not peaks:
            continue
        nd, lbl = next_peak_date(peaks, base)
        if nd:
            out.append((canon, lbl, nd))
    out.sort(key=lambda x: x[2])
    return out[:limit]
# カテゴリ別の除外語。作品データのSubject/Title等で、被写体variantを部分文字列として含むが
# その被写体ではない語を、判定前に各フィールドから除去する（subject_matchesのexclude引数へ渡す）。
# 例: 「鳥」は「鳥居」(神社)「鳥海山」「鳥甲山」(山名)の一部として現れるため、鳥の野鳥判定から外す。
# 被写体の判定は Subject とタイトルについては単純な文字列の含みで見るため、
# 短い語が長い語の一部として誤って当たることがある。
# 「雲海」に「海」が含まれるために、尾瀬ヶ原の雲海の作品が「海」として数えられていた。
# ここに挙げた語は、その被写体を判定する前に取り除く。
# 「海霧」「川霧」「海鳥」「白鳥」は、実際に海や川、鳥が写っているので残す。
SUBJECT_EXCLUDE = {
    '鳥': ['鳥居', '鳥海山', '鳥甲山', '害鳥'],
    '海': ['雲海', 'みずうみ'],          # 雲の海、湖
    '桜': ['秋桜', '芝桜'],              # コスモス、シバザクラ
    '川': ['天の川'],                    # 銀河
    '滝': ['滝雲'],                      # 雲海の一種
    '藤': ['ふじさん', 'ふじ山'],        # 富士山をひらがなで書いたもの
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

# ──────────────── 県の略称の取り違え防止 ────────────────
# 「静岡」「京都」のように県・府から末尾の都/府/県を取った呼び方は、同名の市と
# 県のどちらを指すのか分からない。そこで単独で送られたときだけ、市→県→隣県→全国と
# 段階的に広げて答える（reply_staged_area）。
#
# ところがこの略称は、別の地名の一部としても現れる。
#     「東京都板橋区」の中の『京都』   ← 東[京都]板橋区
#     「長野原町」の中の『長野』
#     「大阪市福島区」の中の『福島』
# 以前は単に含まれるかどうかだけを見ていたため、東京都内の地名を送った方は
# 全員が京都の案内を受け取っていた。全国2,830件のうち73件が誤判定で、
# うち66件が東京都内。利用者のいちばん多い地域がまるごと該当していた。
# （2026-10-03 修正）
#
# 直し方は、判定の前に本物の地名を伏せること。「東京都板橋区」を伏せてしまえば
# 残りに『京都』は出てこない。「京都　紅葉」のように略称だけなら何も伏せられず、
# これまでどおり段階検索に入る。
_SHORT_PREF_OF = {re.sub(r'[都府県]$', '', _p): (_p, _c)
                  for _p, _c in PREF_SAME_NAME_CITY.items()}

def _build_short_mask_names():
    """略称を中に含んでしまう本物の地名を集める。長い名前から先に伏せるため降順に並べる。
    略称そのもの（「京都」「静岡」）は伏せる対象から外す。伏せてしまうと判定できなくなる。"""
    names = set(PREF_LATLNG.keys())                  # 東京都・京都府 など
    names |= set(CITY_LATLNG.keys())                 # 東京都板橋区 など（県名つき）
    for _list in CITY_NAMES_BY_PREF.values():
        names |= set(_list)                          # 板橋区・長野原町 など（県名なし）
    keep = [n for n in names
            if n not in _SHORT_PREF_OF and any(s in n for s in _SHORT_PREF_OF)]
    return sorted(keep, key=len, reverse=True)

_SHORT_MASK_NAMES = _build_short_mask_names()
print(f"[INFO] short-pref mask names: {len(_SHORT_MASK_NAMES)}", flush=True)

def bare_pref_short(user_message):
    """県・府の略称だけが単独で送られたなら (県名, 同名市) を返す。
    別の地名の一部として現れただけなら (None, None)。"""
    masked = user_message
    for _n in _SHORT_MASK_NAMES:
        if _n in masked:
            masked = masked.replace(_n, '　')
    for _sh, (_pf, _ct) in _SHORT_PREF_OF.items():
        if _sh in masked:
            return _pf, _ct
    return None, None


# 上と同じ考え方を、47都道府県すべてに広げたもの。parse_target_area が使う。
# 「北広島市」の中の『広島』、「河内長野市」の中の『長野』を拾わないようにする。
_PREF_SHORT_OF = {}
for _p in PREF_LATLNG:
    _PREF_SHORT_OF["北海道" if _p == "北海道" else re.sub(r'[都府県]$', '', _p)] = _p

def _build_area_mask_names():
    names = set(PREF_LATLNG.keys())
    names |= set(CITY_LATLNG.keys())
    for _list in CITY_NAMES_BY_PREF.values():
        names |= set(_list)
    keep = [n for n in names
            if n not in _PREF_SHORT_OF and any(s in n for s in _PREF_SHORT_OF)]
    return sorted(keep, key=len, reverse=True)

_AREA_MASK_NAMES = _build_area_mask_names()
print(f"[INFO] area mask names: {len(_AREA_MASK_NAMES)}", flush=True)

def pref_by_short(text):
    """県の略称だけから県を決める。本物の地名を伏せてから探し、先に現れたものを採る。
    見つからなければ None。"""
    masked = text
    for _n in _AREA_MASK_NAMES:
        if _n in masked:
            masked = masked.replace(_n, '　')
    best = None
    for _sh, _pf in _PREF_SHORT_OF.items():
        i = masked.find(_sh)
        if i >= 0 and (best is None or i < best[0]):
            best = (i, _pf)
    return best[1] if best else None


# ──────────────── 市区町村名から県を引く索引 ────────────────
# city_latlng.json（全国2,830件）から、県名を外した呼び方→県 の対応を作る。
# 長い名前から順に見るのが肝心で、そうしないと
#   「横浜市港北区」→『北区』→東京都
#   「上三川町」　　→『三川町』→山形県
#   「東村山市」　　→『村山市』→山形県
# のように、短い地名を中に見つけて取り違える。
# 同じ名前が複数の県にあるとき（伊達市＝北海道と福島県）は AMBIGUOUS を返し、
# これまでどおり利用者に問い返す。
_plain_prefs = {}
for _full in CITY_LATLNG:
    _m = PREF_RE.match(_full)
    if not _m:
        continue
    _p = _m.group(1)
    _plain = _full[len(_p):]
    if len(_plain) >= 2:
        _plain_prefs.setdefault(_plain, set()).add(_p)
PLAIN_CITY_SORTED = sorted(_plain_prefs, key=len, reverse=True)
PLAIN_CITY_TO_PREF = {_k: (next(iter(_v)) if len(_v) == 1 else "AMBIGUOUS")
                      for _k, _v in _plain_prefs.items()}
PLAIN_CITY_PREFS = {_k: sorted(_v) for _k, _v in _plain_prefs.items() if len(_v) >= 2}
print(f"[INFO] plain city index: {len(PLAIN_CITY_SORTED)} names "
      f"({len(PLAIN_CITY_PREFS)} ambiguous)", flush=True)

def city_by_plain_name(text):
    """文中にある市区町村名のうち、いちばん長いものを採る。
    戻り値は (県名 or 'AMBIGUOUS' or None, 座標 or None, 名前 or None)。"""
    for _name in PLAIN_CITY_SORTED:
        if _name in text:
            _pf = PLAIN_CITY_TO_PREF[_name]
            if _pf == "AMBIGUOUS":
                return "AMBIGUOUS", None, _name
            return _pf, (CITY_LATLNG.get(_pf + _name) or PREF_LATLNG[_pf]), _name
    return None, None, None

def ambiguous_city_prefs(name):
    """同じ名前の市区町村がある県を並べて返す。問い返しの選択肢に使う。

    まず誌面データから作った表（CITY_TO_PREF_MULTI）を見て、空なら全国の
    市区町村表（PLAIN_CITY_PREFS）で補う。
    「府中市」のように、同名の市が複数あっても誌面には片方の県の作品しか
    無い地名だと前者は空になる。それでも city_by_plain_name は全国表を見て
    AMBIGUOUS を返すので、「番号でお答えください」と言いながら選択肢が
    1つも出ない、という状態になっていた。（2026-10-08）"""
    n = str(name or '').strip()
    if not n:
        return []
    out = list(CITY_TO_PREF_MULTI.get(n) or [])
    if not out:
        out = list(PLAIN_CITY_PREFS.get(n) or [])
    if not out:
        base = re.sub(r'[市区町村郡]', '', n).strip()
        if base:
            for _k, _v in PLAIN_CITY_PREFS.items():
                if re.sub(r'[市区町村郡]', '', _k).strip() == base:
                    out = list(_v)
                    break
    return out

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
    """文中から地域を1つ選ぶ。戻り値は (県名 or 'AMBIGUOUS' or None, 座標, 表示名)。

    見る順番が結果を左右する。
      1. 都道府県名がそのまま書かれていれば、いちばん先に現れたものを採る。
      2. 次に市区町村名。
      3. 最後に県の略称（「大阪」「福島」）。本物の地名を伏せてから探す。

    以前は1と3をまとめて先頭で見ていたため、県の略称が別の地名の一部から
    拾われていた。「大阪府大阪市福島区」は福島県、「河内長野市」は長野県、
    「北広島市」は広島県と解釈されていた。県名をはっきり書いていても起きる。
    全国2,830件のうち25件が該当。（2026-10-03 修正）
    """
    # 1. 都道府県名そのもの。複数あればいちばん先に現れたものを採る。
    hit_pos, hit_pref = None, None
    for pref in PREF_LATLNG:
        i = text.find(pref)
        if i >= 0 and (hit_pos is None or i < hit_pos):
            hit_pos, hit_pref = i, pref
    if hit_pref:
        # 県のみ指定 → 表示も検索キーも県名（県庁所在地名にしない）
        return hit_pref, PREF_LATLNG[hit_pref], hit_pref
    for city, pref in CITY_PREF.items():
        if city in text:
            return pref, PREF_LATLNG[pref], city
    # 2b. 市区町村名そのもの。長い名前を優先して取り違えを防ぐ。
    _cp, _cll, _cnm = city_by_plain_name(text)
    if _cp == "AMBIGUOUS":
        return "AMBIGUOUS", None, _cnm
    if _cp:
        return _cp, _cll, _cnm
    for city, pref in CITY_TO_PREF.items():
        # 「美瑛」→「美瑛町」のような前方一致も拾う
        city_base = re.sub(r'[市区町村郡]', '', city).strip()
        if city in text:
            if city in CITY_TO_PREF_MULTI:
                return "AMBIGUOUS", None, city
            # 手元の市区町村表を先に見る。地図への問い合わせは、そこに無いときだけ。
            # 逆順にすると、2,798件そろっている表を差し置いて毎回外に聞きに行くことになり、
            # 返事を待つぶん遅くなるうえ、表と違う座標が返ることもある。（2026-10-05）
            latlng = CITY_TO_LATLNG.get(city) or geocode(city) or PREF_LATLNG[pref]
            matched_name = city_base if city_base in text else city
            return pref, latlng, matched_name
    for city in CITY_TO_PREF_MULTI:
        city_base = re.sub(r'[市区町村郡]', '', city).strip()
        if city in text or (len(city_base) >= 2 and city_base in text):
            return "AMBIGUOUS", None, city
    # 3. 県の略称。市区町村で決まらなかったときだけ見る。
    #    「大阪　夜景」のような書き方を拾うための最後の手当て。
    _sp = pref_by_short(text)
    if _sp:
        return _sp, PREF_LATLNG[_sp], _sp
    # かつてここで、残りの語をひとつずつ地図に問い合わせていた。
    # ただし結果をどこにも渡しておらず、戻り値は必ず (None, None, None) だった。
    # 地図への問い合わせが1語ごとに走るぶんだけ遅くなるので取り除いた。（2026-10-05）
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

        target_months = set(str(m) for m, k in junkun_window)
        for d in get_photos():
            if d.get('Month') not in target_months:   # 以前は Firestore の where で絞っていた箇所
                continue

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
            # 撮影地そのものの座標を先に見る。無ければ市区町村、それも無ければ県重心。
            # 市区町村の中心で測っていたころは、同じ市の中はどこでも同じ距離になっていた。（2026-10-09）
            wll = place_latlng(d.get('Area'), d.get('Place')) or work_latlng(d.get('Area'), pref)
            wlat, wlng = wll if wll else (lat, lng)          # 表示用座標
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
                place_years[spot_key(d.get('Area', ''), d.get('Place', ''))].append(int(d.get('Year')))
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
            wider_months = set(str(m) for m, k in wider_window)
            for d in get_photos():
                if d.get('Month') not in wider_months:   # 以前は Firestore の where で絞っていた箇所
                    continue
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
                # ここは1件ごとに座標と距離を出す。以前は上のループの最後の値
                # （disp_dist / wlat / wlng）が残ったまま全件に入っていた。
                # いまはこの分岐に入らないので表には出ていないが、
                # 条件が変われば全件が同じ距離になる。（2026-10-09 修正）
                _wll2 = place_latlng(d.get('Area'), d.get('Place')) or work_latlng(d.get('Area'), pref)
                _wlat2, _wlng2 = _wll2 if _wll2 else (lat, lng)
                item = {
                    'dist': haversine(origin[0], origin[1], _wlat2, _wlng2),
                    'wlatlng': (_wlat2, _wlng2),
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
                    place_years[spot_key(d.get('Area', ''), d.get('Place', ''))].append(int(d.get('Year')))
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
            used_spots = set()
            for p in nearby_pool:
                if len(cresults) >= 7:
                    break
                _sk = spot_key(p['area'], p.get('place'))
                if p['pic'] in used_pics or _sk in used_spots:
                    continue
                cresults.append(('📍', nearby_label, p))
                used_pics.add(p['pic'])
                used_spots.add(_sk)
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
        # 撮影地ごとに分ける。ただし1つの市区町村に偏ると選びようがなくなるので、
        # まずは1市区町村2件までで並べ、それで3件に満たなければ上限を外して補う。
        # （以前は市区町村そのものが鍵だったため、日光市からは必ず1件しか出なかった）
        used_spots = set()
        _area_n = defaultdict(int)
        for _pass in (0, 1):
            for p in best_pool:
                if len(results) >= 7:
                    break
                _sk = spot_key(p['area'], p.get('place'))
                if _sk in used_spots:
                    continue
                if _pass == 0 and _area_n[p['area']] >= 2:
                    continue
                results.append(('🎯', 'ベストマッチ', p))
                used_pics.add(p['pic'])
                used_spots.add(_sk)
                _area_n[p['area']] += 1
            if len(results) >= 3:
                break

        # ✨ 注目・傑作（同県優先、最大2枚）
        recent_cutoff = date.today().year - 5
        # 直近5年の入選数。撮影地ごとに数える（市区町村ではなく）。
        attention_score = {
            k: sum(1 for y in ys if y >= recent_cutoff)
            for k, ys in place_years.items()
        }
        hot_pool = sorted(pool, key=lambda x: (-attention_score.get(spot_key(x['area'], x.get('place')), 0), -x['ascore']))
        if target_pref and not _expanded:
            hot_cand = [p for p in hot_pool if p['pref'] == target_pref and p['pic'] not in used_pics] or [p for p in hot_pool if p['pic'] not in used_pics]
        else:
            hot_cand = [p for p in hot_pool if p['pic'] not in used_pics]
        # ベストマッチで出した撮影地は避ける。同じ場所が2行に並ぶと、選択肢が減る。
        for p in hot_cand:
            if len([r for r in results if r[1] == '注目・傑作']) >= 2:
                break
            _sk = spot_key(p['area'], p.get('place'))
            if _sk in used_spots:
                continue
            results.append(('✨', '注目・傑作', p))
            used_pics.add(p['pic'])
            used_spots.add(_sk)

        masterpiece = results[0][2] if results else None
        near = results[1][2] if len(results) > 1 else masterpiece

        # 🎲 気まぐれチョイス（地域・キーワード未指定の時のみ、最大2枚）
        show_gamble = not base_latlng and not keyword
        if show_gamble:
            all_docs = list(get_photos())   # 共有物を並べ替えないよう、写しを取る
        else:
            all_docs = []
        random.shuffle(all_docs)
        gamble_count = 0
        for d in all_docs:
            if gamble_count >= 2:
                break
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
# 地域の通称で引くときの決まり。文字で引いて、これに満たなければ地図に頼る。
# 10kmは、裏磐梯（桧原湖・五色沼・雄国沼）がちょうど収まる広さ。
# 広げすぎると、山の向こう側（表磐梯）まで混ざる。（2026-10-10）
_REGION_MIN = 3
_REGION_RADIUS_KM = 10.0

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
        for d in get_photos():
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
            # 撮影地そのものの座標を先に見る。無ければ市区町村、それも無ければ県。
            # 市区町村の中心から測っていたころは、同じ市の中のどこでも同じ距離になり、
            # 「板橋から渋峠まで2時間半」のような案内が出ていた。（2026-10-09）
            wll = place_latlng(area, place) or work_latlng(area, pref)
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

    def _region_fallback(found):
        """文字で引けなかったときの逃げ道。その言葉を地図で引いて、周りの撮影地を集める。

        「裏磐梯」「奥日光」「尾瀬」のように、通称で呼ばれる地域がある。
        雄国沼も桧原湖も裏磐梯だが、Area は「福島県喜多方市」「福島県北塩原村」で、
        Place にも「裏磐梯」とは書かれていない。文字を突き合わせるだけでは、
        地域まるごとが検索から漏れる。風景写真では、そういう地域こそ要になる。

        撮影地ごとの座標が入ったので、場所で集められるようになった。
        市区町村の中心しか無かったころは、同じ市の撮影地が全部同じ点にいたので、
        半径で切っても意味がなかった。（2026-10-10）"""
        if center_latlng or not place_terms or found >= _REGION_MIN:
            return None
        ll = geocode(place_terms[0])
        if not ll:
            return None
        r2 = search_by_place([], base_date=base_date, origin_latlng=origin_latlng,
                             origin_name=origin_name, subject=subject,
                             center_latlng=ll, radius_km=_REGION_RADIUS_KM,
                             home_latlng=home_latlng, expand_time=expand_time)
        if len(r2.get('results') or []) <= found:
            return None
        r2['region'] = place_terms[0]
        r2['region_radius_km'] = _REGION_RADIUS_KM
        r2['region_found'] = found     # 文字で引けた件数。0なら「見つからなかった」
        return r2

    if in_season:
        pool, status = in_season, 'in_season'
    elif all_time:
        pool, status = all_time, 'off_season'
    else:
        return _region_fallback(0) or {'status': 'not_found', 'results': []}
    if home_latlng and center_latlng:
        pool.sort(key=lambda x: (x.get('detour', 0), x.get('cdist', 0)))
    elif center_latlng:
        pool.sort(key=lambda x: (x.get('cdist', 0), -x['ascore']))
    else:
        pool.sort(key=lambda x: (-x['ascore'], -x.get('_year', 0)))
    # 1つの撮影地が7枠を埋めてしまわないようにする。探しているのは作品ではなく場所なので、
    # 同じ場所の2枚目より、別の場所の1枚目のほうが役に立つ。
    # 補うのは、場所が1か所しか見つからなかったときだけ。
    # はじめ「3件に満たなければ」としていたが、それでは2か所あるときにも
    # 3枚目を作ろうとして同じ場所が並んだ。2か所あるなら、2か所そのまま出すほうが素直。
    # 同じ場所を2枚見せる値打ちがあるのは、ほかに選びようが無いときだけ。（2026-10-10）
    results, used, used_spots = [], set(), set()
    for _pass in (0, 1):
        for p in pool:
            if len(results) >= 7:
                break
            if p['pic'] in used:
                continue
            _sk = spot_key(p['area'], p.get('place'))
            if _pass == 0 and _sk in used_spots:
                continue
            # 2周目で足したものは、すでに出した撮影地の別の作品。
            # 同じ名前が並ぶので、別の場所だと思わせないよう名札を分ける。（2026-10-10）
            if _pass and _sk in used_spots:
                results.append(('📷', '同じ撮影地の別の作品', p))
            else:
                results.append(('🎯', 'ベストマッチ', p))
            used.add(p['pic'])
            used_spots.add(_sk)
        if len(used_spots) >= 2:
            break
    results = filter_broken_images(results)
    if not results:
        return _region_fallback(0) or {'status': 'not_found', 'results': []}
    wide = _region_fallback(len(results))
    if wide:
        return wide
    peaks = compute_peaks(bin_counter)
    return {'status': status, 'results': results, 'peaks': peaks}

def normalize_name_query(s):
    """人名を照合用の形にそろえる(空白・区切り記号を落とす)。
    Master_Photos の Winner4Search / Judge4Search と同じ形になる。"""
    return re.sub(r'[\s　,、.。・･／/｜|]+', '', str(s or '')).strip()

def search_by_person(name_query, origin_latlng=None, origin_name=None):
    """作者名での検索。地名でも被写体でも見つからなかったときの、最後の照合。

    Master_Photos には検索用に空白を除いた氏名が入っている(Winner4Search /
    Judge4Search)ので、そこを完全一致で引く。全件走査ではなく該当行だけを読む。

    返り値:
      {'status':'author', 'results':[...], 'display':氏名, 'total':件数}
          … 案内できる作品がある方
      {'status':'judge', 'display':氏名}
          … 本誌フォトコンテストの審査員としてご登場の方
      {'status':'listed_only', 'display':氏名}
          … 誌面に掲載はあるが、案内の対象にしていない作品だけの方
      {'status':'not_found'}
    """
    q = normalize_name_query(name_query)
    if not db or len(q) < 2:
        return {'status': 'not_found'}
    try:
        excl_authors, blocked_areas = load_exclusions()
    except Exception:
        excl_authors, blocked_areas = set(), []
    origin = origin_latlng if origin_latlng else SHINJUKU
    base_name = origin_name or DEFAULT_ORIGIN_NAME
    items = []
    listed = 0          # 氏名は一致したが、案内の対象にしていない作品の数
    display = str(name_query or '').strip()
    try:
        for d in get_photos():
            if d.get('Winner4Search') != q:      # 以前は Firestore の完全一致で絞っていた箇所
                continue
            listed += 1
            if d.get('Winner'):
                display = str(d.get('Winner')).strip()
            if d.get('Winner') in excl_authors:
                continue
            pub = d.get('Published', '')
            if pub and pub.endswith('N'):      # 風景写真祭作品は検索対象外
                continue
            if not has_valid_image(d.get('PicFileName')):
                continue
            if is_area_blocked(d.get('Place'), d.get('Area'), blocked_areas):
                continue
            area = d.get('Area', '') or ''
            pref = extract_pref(area)
            wll = work_latlng(area, pref)
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
            items.append({
                'dist': dist, 'pref': pref or '', 'area': area, 'place': d.get('Place', '') or '',
                'cdist': 0, 'detour': 0,
                'title': d.get('Title', '') or '', 'period': format_period(d.get('Month'), d.get('Day')),
                'winner': d.get('Winner', ''), 'winner_area': d.get('WinnerArea', ''),
                'award': d.get('AwardRank', ''), 'ascore': calc_award_score(d.get('AwardRank')),
                'pic': d.get('PicFileName', ''), 'pub': pub,
                'url': view_image_url(pub, d.get('PicFileName', '')),
                'base_name': base_name, 'maplink': d.get('MapLink', ''),
                'dnumb': str(d.get('dNumb', '')), 'matched_kw': None, '_year': year,
            })
    except Exception:
        import traceback
        print(f"[ERROR] search_by_person failed: {traceback.format_exc()}", flush=True)
        return {'status': 'not_found'}

    if items:
        items.sort(key=lambda x: (-x['ascore'], -x.get('_year', 0)))
        results, used = [], set()
        for p in items:
            if len(results) >= 7:
                break
            if p['pic'] in used:
                continue
            results.append(('🎯', 'ベストマッチ', p))
            used.add(p['pic'])
        results = filter_broken_images(results)
        if results:
            return {'status': 'author', 'results': results,
                    'display': display, 'total': len(items)}

    # 作者として案内できる作品が無いときは、審査員として登場していないかを見る
    try:
        for d in get_photos():
            if d.get('Judge4Search') != q:       # 以前は Firestore の完全一致＋1件で絞っていた箇所
                continue
            jname = str(d.get('Judge') or '').strip()
            return {'status': 'judge', 'display': jname or display}
    except Exception:
        pass

    if listed:
        return {'status': 'listed_only', 'display': display}
    return {'status': 'not_found'}

# ──────────────── 撮り頃の集計用インデックス ────────────────
# 「風景撮ろうよ！」(/enjoy)の撮り頃カードは、以前は呼ばれるたびに
# Master_Photos を全件(約14,700件)読み、1件ごとに被写体カテゴリ37種類と
# 照合していた。1回の応答に13秒前後かかり、Firestoreの読み取りも
# 1回あたり約14,700。無料枠(1日5万)なら3回で使い切ってしまう。
#
# 集計に要るのは「座標・旬・その作品が該当する被写体」の3つだけで、
# これは誌面データを入れ替えたときしか変わらない。そこで一度だけ作って
# メモリに置き、一定時間そのまま使い回す。
# 除外設定(作者・地域)は日付で変わりうるので、索引には入れず毎回適用する。
# ──────────────── 撮影計画のための道具 ────────────────
# 天候の表記ゆれをそろえる。誌面データには「晴」「晴れ」「快晴」が混在し、
# さらに文字化けが70件ある(UTF-8のバイト列をShift_JISとして読んでしまったもの。
# 置換文字が入って元のバイトが失われているため、壊れていない先頭で判別する)。
_WEATHER_VARIANTS = (
    ('晴れ', ('快晴', '日本晴れ', '日本晴', '晴れ', '晴')),
    ('曇り', ('薄曇り', '薄曇', 'うす曇り', 'くもり', '曇り', '曇')),
    ('雨',   ('霧雨', '小雨', '大雨', '雨')),
    ('雪',   ('吹雪', '小雪', '大雪', '雪')),
    ('霧',   ('濃霧', '朝霧', '霧')),
)
_WEATHER_BROKEN = (('譎エ', '晴れ'), ('譖', '曇り'))

def normalize_weather(value):
    """天候の記載を『晴れ・曇り・雨・雪・霧』のどれかにそろえる。
    当てはまらなければ None。『晴れ時々曇り』のような複合は、先に出るほうを採る。"""
    s = str(value or '').strip()
    if not s:
        return None
    for head, canon in _WEATHER_BROKEN:          # 文字化けは先頭で見分ける
        if s.startswith(head):
            return canon
    best = None                                   # (位置, 長さの負値, 正式名)
    for canon, variants in _WEATHER_VARIANTS:
        for v in variants:
            i = s.find(v)
            if i >= 0:
                cand = (i, -len(v), canon)
                if best is None or cand < best:
                    best = cand
    return best[2] if best else None

def photo_hour(value):
    """Hour列を0〜23の整数にする。255(不明を表す印)や空、範囲外は None。"""
    s = str(value or '').strip()
    if not s:
        return None
    try:
        h = int(float(s))
    except (TypeError, ValueError):
        return None
    if h == 255 or not (0 <= h <= 23):
        return None
    return h

# 移動時間の見積り。直線距離では実際の道のりに足りないので1.3倍し、
# 時速45kmで走るものとする(実質 約35km/h)。地図の吹き出しと同じ式にそろえること。
ROAD_FACTOR = 1.3
DRIVE_KMH = 45.0

def drive_minutes(km):
    """直線距離(km)から、車での移動時間(分)を見積もる。"""
    try:
        return int(round(float(km) * ROAD_FACTOR / DRIVE_KMH * 60))
    except (TypeError, ValueError):
        return 0

_DIR_NAMES = ('北', '北東', '東', '南東', '南', '南西', '西', '北西')

def bearing(lat1, lng1, lat2, lng2):
    """1点目から2点目を見た方位角(北=0度、東=90度)を返す。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

def bearing_label(deg):
    """方位角を『北』『北西』などの8方位の名前にする。"""
    return _DIR_NAMES[int((float(deg) + 22.5) % 360.0 // 45.0)]

def sun_times(lat, lng, d, tz_hours=9.0):
    """その土地・その日の日の出と日の入りを、0時からの分で返す。
    白夜・極夜で太陽が昇らない(沈まない)ときは None を返す。
    NOAAの略算式による。数分の誤差は撮影計画には差し支えない。"""
    try:
        doy = d.timetuple().tm_yday
        g = 2.0 * math.pi / 365.0 * (doy - 1 + 0.5)          # 年内の位置(ラジアン)
        eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                           - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
        decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
                - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
                - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
        p = math.radians(lat)
        cos_ha = (math.cos(math.radians(90.833)) / (math.cos(p) * math.cos(decl))
                  - math.tan(p) * math.tan(decl))
        if cos_ha > 1 or cos_ha < -1:                         # 昇らない/沈まない
            return (None, None)
        ha = math.degrees(math.acos(cos_ha))
        rise = 720.0 - 4.0 * (lng + ha) - eqtime + tz_hours * 60.0
        sets = 720.0 - 4.0 * (lng - ha) - eqtime + tz_hours * 60.0
        return (int(round(rise)) % 1440, int(round(sets)) % 1440)
    except Exception:
        return (None, None)

def hhmm(minutes):
    """0時からの分を『5:30』の形にする。"""
    if minutes is None:
        return ''
    m = int(round(minutes))
    return f"{(m // 60) % 24}:{m % 60:02d}"


_PEAK_INDEX = None          # [(lat, lng, bin, (被写体,...), 作者名, 地名+地域,
                            #   時刻, 天候, 地域, 県, 地名), ...]
_PEAK_INDEX_AT = 0.0        # 索引を作った時刻
_PEAK_INDEX_TTL = 6 * 3600  # 6時間で作り直す
_PEAK_BEST = {}             # 地域 → {旬index: その旬の代表作品}
                            # 代表作品 = {'score','title','winner','award','period','pub','img'}
                            # 撮影地を写真で選べるようにするためのもの。索引と一緒に作る。

def build_peak_index():
    """Master_Photos を一度だけ読んで、撮り頃の集計に必要なぶんだけ取り出す。
    失敗したら None を返す(その場合は古い索引を使い続ける)。"""
    if not db:
        return None
    idx = []
    best = {}
    try:
        for d in get_photos():
            pub = d.get('Published', '')
            if pub and pub.endswith('N'):      # 風景写真祭作品は対象外
                continue
            if not has_valid_image(d.get('PicFileName')):
                continue
            try:
                mo = int(d.get('Month'))
            except Exception:
                continue
            if not (1 <= mo <= 12):
                continue
            area = d.get('Area', '') or ''
            place = d.get('Place', '') or ''
            title = d.get('Title', '') or ''
            pref = extract_pref(area)
            wll = work_latlng(area, pref) or (PREF_LATLNG.get(pref) if (pref and pref in PREF_LATLNG) else None)
            if not wll:
                continue
            sfield = d.get('Subject', '')
            subs = tuple(
                canon for canon, variants in KEYWORD_NORMALIZE.items()
                if subject_matches(variants, title=title, place=place, area=area,
                                   subject_field=sfield, exclude=subject_exclude_for(canon))
            )
            if not subs:                        # どの被写体にも当たらない作品は集計に使わない
                continue
            bi = bin_index(mo, d.get('Day'))
            idx.append((wll[0], wll[1], bi, subs,
                        d.get('Winner', ''), place + ' ' + area,
                        photo_hour(d.get('Hour')), normalize_weather(d.get('Weather')),
                        area, pref, place))

            # 地域ごと・旬ごとに、受賞順位がいちばん高い作品を1点だけ覚えておく。
            # 旬で分けておくのは、行く時期に近い作品を後で選べるようにするため。
            # 末尾N（風景写真祭）と画像の無い作品は、この上で既に除いてある。
            score = calc_award_score(d.get('AwardRank'))
            slot = best.setdefault(area, {})
            cur = slot.get(bi)
            if cur is None or score > cur['score']:
                slot[bi] = {
                    'score': score,
                    'title': title,
                    'winner': d.get('Winner', '') or '',
                    'award': d.get('AwardRank', '') or '',
                    'period': format_period(mo, d.get('Day')),
                    'pub': pub,
                    'img': view_image_url(pub, d.get('PicFileName')),
                }
    except Exception:
        import traceback
        print(f"[ERROR] build_peak_index: {traceback.format_exc()}", flush=True)
        return None
    global _PEAK_BEST
    _PEAK_BEST = best
    print(f"[INFO] peak index built: {len(idx)} 件 / 代表作品 {len(best)} 地域", flush=True)
    return idx

def best_work_for(area, target_bin=None):
    """その地域の代表作品を1点返す。撮影地を写真で選べるようにするためのもの。
    target_bin（行く時期の旬）に近い作品を優先し、同じくらい近ければ受賞順位の高いほうを選ぶ。
    10月の計画に1月の雪景色を出しても、行き先を選ぶ材料にならないため。
    索引がまだ無い、またはその地域の作品が無ければ空の辞書を返す。"""
    slot = _PEAK_BEST.get(area)
    if not slot:
        return {}
    if target_bin is None:
        return max(slot.values(), key=lambda w: w['score'])
    def near(bi):
        return min((target_bin - bi) % 36, (bi - target_bin) % 36)
    return min(slot.items(), key=lambda kv: (near(kv[0]), -kv[1]['score']))[1]

def works_for(area, target_bin=None, limit=6):
    """その地域の受賞作を、行く時期に近い順に数点返す。
    撮影地を決めたあと「ここではどんな写真が撮られているのか」を見るためのもの。
    旬ごとに1点ずつ持っているので、並べると季節のちがいが見える。
    末尾N（風景写真祭）と画像の無い作品は、索引を作る段階で既に除いてある。"""
    slot = _PEAK_BEST.get(area)
    if not slot:
        return []
    items = list(slot.items())
    if target_bin is None:
        items.sort(key=lambda kv: -kv[1]['score'])
    else:
        def near(bi):
            return min((target_bin - bi) % 36, (bi - target_bin) % 36)
        items.sort(key=lambda kv: (near(kv[0]), -kv[1]['score']))
    return [{'title': w['title'], 'winner': w['winner'], 'award': w['award'],
             'period': w['period'], 'img': w['img']}
            for _bi, w in items[:limit]]

def get_peak_index():
    """索引を返す。無ければ作る。期限が切れていれば作り直す。"""
    global _PEAK_INDEX, _PEAK_INDEX_AT
    now = time.time()
    if _PEAK_INDEX is not None and (now - _PEAK_INDEX_AT) < _PEAK_INDEX_TTL:
        return _PEAK_INDEX
    built = build_peak_index()
    if built is not None:
        _PEAK_INDEX, _PEAK_INDEX_AT = built, now
    return _PEAK_INDEX if _PEAK_INDEX is not None else []

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
    clat, clng = center_latlng[0], center_latlng[1]
    for lat, lng, bi, subs, winner, pa, *_rest in get_peak_index():
        if haversine(clat, clng, lat, lng) > radius_km:
            continue
        if winner and winner in excl_authors:
            continue
        if blocked_areas and any(b and b in pa for b in blocked_areas):
            continue
        for canon in subs:
            bins[canon][bi] += 1
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
def safe_uri(u, fallback=None):
    """LINEの uri アクションに渡せる形に整える。
    LINEは未エンコードの空白・非ASCIIを含むURIを400『Invalid action URI』で弾き、
    その1件のためにメッセージ全体が送信されなくなる。ここで確実に通る形に正規化する。
    ・空/None、http(s)以外、ホスト無し → fallback
    ・パス/クエリの空白・非ASCIIを percent-encode
    ・1000文字超（LINEの上限）→ fallback
    """
    s = str(u or '').strip()
    if not s:
        return fallback
    try:
        from urllib.parse import urlsplit, urlunsplit, quote as _q
        p = urlsplit(s)
        if p.scheme not in ('http', 'https') or not p.netloc:
            return fallback
        out = urlunsplit((
            p.scheme,
            p.netloc,
            _q(p.path, safe="/%"),
            _q(p.query, safe="=&%+"),
            _q(p.fragment, safe="%"),
        ))
        return out if len(out) <= 1000 else fallback
    except Exception:
        return fallback
def build_carousel_bubble(item, label_emoji, area_note="", matched_kw=None, plan_id=None, idx=0):
    """カルーセルの1バブルを組み立てる。
    画像URIが不正な場合は None を返す（呼び出し側で除外する）。1件の不正データで
    メッセージ全体が送れなくなるのを防ぐため、URIはすべて safe_uri を通す。"""
    from urllib.parse import quote

    img_url = safe_uri(item.get('url'))
    if not img_url:
        print(f"[WARN] bubble skipped (bad image url): pic={item.get('pic')!r} "
              f"pub={item.get('pub')!r} url={item.get('url')!r}", flush=True)
        return None

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

    map_uri = safe_uri(
        f"https://maps.google.com/maps?q={quote(area)}" if area else "https://maps.google.com/",
        fallback="https://maps.google.com/")
    ref_base = "https://reference.fukei-shashin.co.jp/reference"
    ref_location = place if place else area
    ref_uri = safe_uri(
        f"{ref_base}?location={quote(ref_location)}" if ref_location else ref_base,
        fallback=ref_base)

    # 撮影ノート（リファレンス側 /planner）のURL
    planner_base = "https://reference.fukei-shashin.co.jp/planner"
    if plan_id:
        # PlanSession方式: 全候補をFirestoreに保存済み、IDとインデックスだけ渡す
        planner_uri = f"{planner_base}?planId={quote(str(plan_id))}&idx={idx}"
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
    planner_uri = safe_uri(planner_uri, fallback=planner_base)

    footer_buttons = [
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
                "label": "📋 撮影ノート",
                "uri": planner_uri
            }
        }
    ]

    bubble = {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": img_url,
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover",
            "action": {
                "type": "uri",
                "uri": img_url
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
            "contents": footer_buttons
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
    base_date を渡すと、結果や指定地が開放月外の閉山スポットに該当する場合に注意書きを添える。

    送信は必ず例外を捕まえる。LINEに1件でも不正なバブルがあると400で全通が届かず、
    利用者からは『無反応』にしか見えないため、失敗時は平文で代替の返信を出す。"""
    plan_id = save_plan_session(results) if len(results) > 1 else None
    bubbles = [build_carousel_bubble(it, e, l, matched_kw=it.get('matched_kw'), plan_id=plan_id, idx=i)
               for i, (e, l, it) in enumerate(results)]
    _skipped = sum(1 for b in bubbles if b is None)
    bubbles = [b for b in bubbles if b]          # 不正データのバブルは落とす(全体は生かす)
    if _skipped:
        print(f"[WARN] {_skipped} bubble(s) skipped due to invalid uri", flush=True)
    if not bubbles:
        # 全滅した場合だけ、カルーセルを諦めて文章で返す
        print("[ERROR] all bubbles invalid; falling back to text", flush=True)
        _t = (head_text or "撮影地の候補が見つかりましたが、画像の表示に問題があり一覧を出せませんでした。")
        try:
            line_bot_api.reply_message(reply_token, TextSendMessage(text=_t))
        except Exception:
            import traceback
            print(f"[ERROR] fallback reply failed: {traceback.format_exc()}", flush=True)
        return
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
    try:
        line_bot_api.reply_message(reply_token, msgs)
    except Exception:
        import traceback
        print(f"[ERROR] reply_with_carousel send failed: {traceback.format_exc()}", flush=True)
        # 何が弾かれたのかを後から特定できるよう、送ろうとした中身を残す
        try:
            print("[DEBUG] payload: " + json.dumps(
                [m.as_json_dict() for m in msgs], ensure_ascii=False)[:4000], flush=True)
        except Exception:
            pass
        # カルーセルを諦め、文章だけでも届ける（無反応にしない）
        try:
            _parts = [p for p in (head_text, note_text, menu_text) if p]
            _t = "\n\n".join(_parts) if _parts else "検索結果の表示に失敗しました。もう一度お試しください。"
            line_bot_api.reply_message(reply_token, TextSendMessage(text=_t[:4900]))
        except Exception:
            print(f"[ERROR] fallback reply failed: {traceback.format_exc()}", flush=True)

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
        for d in get_photos():
            area = d.get('Area', '')
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
                     # 2026-10-03 /guide へのリンクを外した。
                     # あのページには改名前の名前（撮影プランナー・撮影プラン・候補マップ）と
                     # 改定前の料金（PRO 月額990円）が残っていて、いまの案内と食い違う。
                     # マニュアル(/manual)は10月2日に全面改訂済みなので、こちらだけを出す。
                     "📋 操作マニュアル\nhttps://reference.fukei-shashin.co.jp/manual?openExternalBrowser=1"
            ))
        return

    # 「現在地」だけで送られたとき（リッチメニューの「現在地から探す」）。
    # 単独では検索の形になっていないため、そのままだと地名として検索されて空振りする。
    # LINEのリッチメニューからは位置情報を直接送れないので、
    # ここで「位置情報を送る」ボタン（LocationAction）を出して1タップで送れるようにする。
    if event.message.text.strip() in ("現在地", "現在地から探す", "いまいる場所", "今いる場所"):
        _u = USER_LOCATION.get(user_id)
        _items = [QuickReplyButton(action=LocationAction(label="位置情報を送る"))]
        if _u:
            # すでに起点がある人は、送り直さなくてもそのまま探せる。
            _items.append(QuickReplyButton(action=MessageAction(label="撮り頃を見る", text="撮り頃")))
            _city = _u.get("city") or "登録済みの地点"
            _txt = (f"いまの起点は「{_city}」です。\n"
                    "別の場所にいるときは、下の「位置情報を送る」で更新してください。\n\n"
                    "この起点から探すには、こんな送り方ができます。\n"
                    "・撮り頃150 … いま撮り頃の被写体を半径150kmから\n"
                    "・滝現在地100 … 被写体を指定して半径100kmから\n"
                    "・現在地r150 … 登録した自宅へ向かう帰り道で")
        else:
            _txt = ("まず、いまいる場所を教えてください。\n"
                    "下の「位置情報を送る」を押すと地図が開きます。\n\n"
                    "登録すると、こんな探し方ができるようになります。\n"
                    "・撮り頃150 … いま撮り頃の被写体を半径150kmから\n"
                    "・滝現在地100 … 被写体を指定して半径100kmから\n"
                    "・現在地r150 … 登録した自宅へ向かう帰り道で")
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text=_txt, quick_reply=QuickReply(items=_items))
        )
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
                RESULT_PENDING.pop(user_id, None)  # 番号以外は新規クエリとして続行
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
                RESULT_PENDING.pop(user_id, None)
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
                SUBJECT_PENDING.pop(user_id, None)
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
                SUBJECT_PENDING.pop(user_id, None)
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
                SUBJECT_PENDING.pop(user_id, None)
                line_bot_api.reply_message(reply_token, TextSendMessage(text="承知しました。地域名や被写体（例：弘前 桜）をお知らせください。"))
                return
            else:
                SUBJECT_PENDING.pop(user_id, None)  # 番号以外は新規クエリとして続行

        # 目的地入力待ち（tコマンドで目的地が未確定だったとき）
        if user_id in ROUTE_PENDING:
            rp = ROUTE_PENDING[user_id]
            ch = user_message.strip()
            if ch in ("戻る", "もどる", "キャンセル", "中止", "やめる"):
                ROUTE_PENDING.pop(user_id, None)
                line_bot_api.reply_message(reply_token, TextSendMessage(
                    text="目的地の入力をやめました。地名や被写体（例：弘前 桜）をお知らせください。"))
                return
            _wc = ambiguous_ward_candidates(ch, rp["origin_latlng"])
            if _wc:
                ROUTE_PENDING.pop(user_id, None)
                ask_ward(reply_token, user_id, ch, _wc, "dest", rp["center"], rp["center_nm"],
                         rp["subject"], rp["radius"], rp["origin_latlng"], rp["origin_name"])
                return
            _dll, _dnm, _dconf = resolve_place(ch)
            if _dll is not None and _dconf:
                ROUTE_PENDING.pop(user_id, None)
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
                WARD_PENDING.pop(user_id, None)
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
                EXPAND_PENDING.pop(user_id, None)
                line_bot_api.reply_message(reply_token, TextSendMessage(text="別の地域やキーワードを入力してください。"))
                return
            EXPAND_PENDING.pop(user_id, None)
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
                AMBIGUOUS_PENDING.pop(user_id, None)
                _amb_keyword = kw_option[0]
                search_keyword = kw_option[0]
                _pp = parse_period(user_message); target_date = _pp['date']
                area_name, area_latlng, area_display = None, None, None
            elif resolved_pref:
                # 地域を確定（番号や県名で選択）
                AMBIGUOUS_PENDING.pop(user_id, None)
                # ここも手元の表が先。（2026-10-05）
                latlng = CITY_TO_LATLNG.get(city) or geocode(f"{resolved_pref}{city}") or PREF_LATLNG.get(resolved_pref)
                _pp = parse_period(user_message); target_date = _pp['date']
                area_name, area_latlng, area_display = resolved_pref, latlng, city
            else:
                # 番号でも県名でもない → 新規クエリとして処理
                AMBIGUOUS_PENDING.pop(user_id, None)
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
        # カテゴリ語（「花」など）の問い返し。被写体名ではなく上位カテゴリで来たとき、
        # いま撮り頃のものだけを選択肢にして返す。「今どんな花が撮れるか」という問いへの答え。
        # カテゴリ判定の前に日付表現を落とす（「1月 花」「週末 花」等でもカテゴリとして拾うため）。
        # 日付は _pp で解析済みなので、ここで除いても情報は失われない。
        _msg_for_cat = re.sub(
            r'\d{1,2}月(?:\d{1,2}日)?|\d+日後|上旬|中旬|下旬|明日|あした|明後日|あさって|今日|本日|来週末|今週末|来週|今週|週末',
            ' ', user_message)
        _cat = detect_category(_msg_for_cat) if not _amb_keyword else None
        if _cat and not _subj:
            _u = USER_LOCATION.get(user_id)
            _ol = (_u["lat"], _u["lng"]) if _u else None
            _on = (_u.get("city") or "現在地") if _u else DEFAULT_ORIGIN_NAME
            _ccent = _ol or SHINJUKU
            _cnear = _on if _ol else "東京"
            RADIUS_CAT = 300   # カテゴリ一覧は広めに見る（被写体一つに絞る前の段階のため）
            _members = SUBJECT_CATEGORIES.get(_cat, [])
            _inpeak = category_members_in_peak(_members, _ccent, RADIUS_CAT, target_date)
            if _inpeak:
                _picks = _inpeak[:8]
                _lines = [f"{i+1}．{s}（撮り頃 {pk}・{n}件）" for i, (s, pk, n) in enumerate(_picks)]
                _qr = QuickReply(items=[
                    QuickReplyButton(action=MessageAction(label=s[:20], text=s))
                    for s, _pk, _n in _picks])
                CATEGORY_PENDING[user_id] = {'names': [s for s, _p, _n in _picks]}
                line_bot_api.reply_message(reply_token, TextSendMessage(
                    text=(f"「{_cat}」で探します。{_cnear}から半径{RADIUS_CAT}km圏内で、"
                          f"いま撮り頃なのはこちらです。\n" + "\n".join(_lines) +
                          "\n\n番号か名前を送ると、その撮影地をご案内します。"),
                    quick_reply=_qr))
                return
            # 撮り頃が一つも無い季節（冬など）→ 無いものは無いと言った上で、次に近い撮り頃を示す
            _nexts = category_next_peaks(_members, _ccent, RADIUS_CAT, target_date)
            if _nexts:
                _picks = _nexts[:3]
                _lines = [f"{i+1}．{s}（{lbl}ごろ）" for i, (s, lbl, _d) in enumerate(_picks)]
                _qr = QuickReply(items=[
                    QuickReplyButton(action=MessageAction(label=s[:20], text=s))
                    for s, _l, _d in _picks])
                CATEGORY_PENDING[user_id] = {'names': [s for s, _l, _d in _picks]}
                line_bot_api.reply_message(reply_token, TextSendMessage(
                    text=(f"{_cnear}の周辺では、いま撮り頃の{_cat}は見つかりませんでした。\n"
                          f"次に近い撮り頃はこちらです。\n" + "\n".join(_lines) +
                          "\n\n番号か名前を送ると、その撮影地をご案内します。"),
                    quick_reply=_qr))
                return
            line_bot_api.reply_message(reply_token, TextSendMessage(
                text=(f"{_cnear}の周辺では、{_cat}の作品が見つかりませんでした。"
                      f"「桜」「ひまわり」のように具体的な名前でもお試しください。")))
            return

        # カテゴリの問い返しへの番号応答（名前で直接送られた場合は通常の被写体検索に流れる）
        if user_id in CATEGORY_PENDING:
            _cp = CATEGORY_PENDING[user_id]
            _mnum2 = re.match(r'^\s*(\d{1,2})\s*$',
                              user_message.translate(str.maketrans("０１２３４５６７８９", "0123456789")))
            if _mnum2:
                _i = int(_mnum2.group(1)) - 1
                _names = _cp.get('names') or []
                if 0 <= _i < len(_names):
                    CATEGORY_PENDING.pop(user_id, None)
                    _subj = _names[_i]
                    search_keyword = _subj
                    area_name, area_latlng, area_display = None, None, None
                else:
                    line_bot_api.reply_message(reply_token, TextSendMessage(
                        text=f"1〜{len(_names)}の番号でお選びください。"))
                    return
            else:
                CATEGORY_PENDING.pop(user_id, None)  # 番号以外は新規クエリとして続行
                
        # 県の略称と同名の市があるケース（静岡・山梨など）。県/府も市も付けず単独略称で送られたら、
        # まず市(狭い)で答え、メニューの「地域を広げる」で市→県→隣県→全国と段階的に広げる（狭→広）。
        _short_pref = None
        _short_city = None
        if not _amb_keyword:
            # 本物の地名を伏せてから略称を探す。詳しくは bare_pref_short の説明を参照。
            _short_pref, _short_city = bare_pref_short(user_message)
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
            prefs = ambiguous_city_prefs(area_display)
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
                # 地名でも被写体でも見つからないとき、最後に作者名として照合する。
                # ここまで来た語は既存の検索がすべて空振りしているので、既存の経路に影響しない。
                _per = search_by_person(place_query, origin_latlng=origin_latlng, origin_name=origin_name)
                if _per['status'] == 'author':
                    _n = _per['total']
                    _more = f"（本誌掲載は全{_n}点）" if _n > len(_per['results']) else ""
                    _head = (f"{_per['display']}さんの入選作をご紹介します。{_more}\n"
                             f"それぞれの撮影地もあわせてご覧ください。")
                    reply_with_carousel(reply_token, _head, _per['results'], base_date=target_date)
                    return
                if _per['status'] == 'judge':
                    line_bot_api.reply_message(reply_token, TextSendMessage(
                        text=f"{_per['display']}さんは、本誌フォトコンテストの審査員としてご登場の方です。\n\n"
                             f"コンシェルジュがご案内しているのは応募作品の撮影地ですので、"
                             f"審査員やプロの方の作品は対象にしておりません。\n"
                             f"地名や被写体（滝・桜・紅葉など）でお探しください。"))
                    return
                if _per['status'] == 'listed_only':
                    line_bot_api.reply_message(reply_token, TextSendMessage(
                        text=f"{_per['display']}さんの作品は本誌に掲載がありますが、"
                             f"撮影地のご案内の対象にはしておりません。\n"
                             f"地名や被写体（滝・桜・紅葉など）でお探しください。"))
                    return
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
                # 末尾1文字を落として「長野県」→「長野」と呼びかける。
                # ただし「北海道」は道まで含めて名前なので、落とすと「北海」になる。（2026-10-08 修正）
                text=f"{area_name if area_name == '北海道' else area_name[:-1]}ですか。それは楽しみですね。どのあたりに行かれますか？市町村名や地域名を教えていただけますか。"
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
                # 以前は Firestore の完全一致＋1件で引いていた箇所。いまは手元の作品データから探す。
                for d in get_photos():
                    if dnumb:
                        if str(d.get('dNumb', '')) != str(dnumb):
                            continue
                    else:
                        if d.get('PicFileName', '') != pic_filename:
                            continue
                    photo_data = d
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
# ──────────────── 道の駅 ────────────────
# 全国約1,200駅。誌面データと同じく、めったに変わらないのでメモリに置いて使い回す。
# 出典：駅名・所在地は国土交通省ウェブサイト「道の駅」一覧（公共データ利用規約PDL1.0）、
#       緯度経度は Wikidata（CC0）。
_EKI = None
_EKI_AT = 0.0
_EKI_TTL = 24 * 3600     # 1日で読み直す（新規登録は年に数回なので長めでよい）

def get_michinoeki():
    """道の駅の一覧を返す。無ければ読む。期限が切れていれば読み直す。"""
    global _EKI, _EKI_AT
    now = time.time()
    if _EKI is not None and (now - _EKI_AT) < _EKI_TTL:
        return _EKI
    if not db:
        return _EKI or []
    rows = []
    try:
        for doc in db.collection('michinoeki').stream():
            d = doc.to_dict() or {}
            try:
                rows.append({'name': d.get('name', ''), 'pref': d.get('pref', ''),
                             'city': d.get('city', ''), 'site': d.get('site', ''),
                             'lat': float(d['lat']), 'lng': float(d['lng'])})
            except (KeyError, TypeError, ValueError):
                continue
    except Exception:
        import traceback
        print(f"[ERROR] get_michinoeki: {traceback.format_exc()}", flush=True)
        return _EKI or []
    print(f"[INFO] michinoeki loaded: {len(rows)}件", flush=True)
    _EKI, _EKI_AT = rows, now
    return _EKI

# ──────────────── 天候の予報（撮影地ごと） ────────────────
# 出発地1点の予報では足りない。同じ日でも「渡良瀬遊水地は終日霧雨、日光は午後から
# 晴れ」ということが実際に起きる。Open-Meteo は1回の呼び出しで複数地点を返せるので、
# 候補の撮影地をまとめて1回だけ聞く。
#
# 取れなかったときは天候なしで従来どおり組む。予報は計画を良くする材料であって、
# 計画が出ない理由にしてはいけない。
_WX_URL = "https://api.open-meteo.com/v1/forecast"
_WX_TIMEOUT = 8            # 秒。ここで待たされて計画が出ないほうが困る
_WX_TTL = 3600             # 同じ日・同じ地点の予報は1時間使い回す
_WX_MAX_POINTS = 60        # 1回に聞く地点の上限
_WX_AHEAD_MAX = 14         # 何日先まで予報が届くか（実測した値）
_WX_BACK_MAX = 60          # 何日前までさかのぼれるか

_WX_CACHE = {}

# Open-Meteo の天気コード（WMO）を、誌面で使う言い方に寄せる
_WX_CODE_NAME = {0: '快晴', 1: '晴れ', 2: '晴れ', 3: '曇り', 45: '霧', 48: '霧',
                 51: '霧雨', 53: '霧雨', 55: '霧雨', 56: '霧雨', 57: '霧雨',
                 61: '雨', 63: '雨', 65: '雨', 66: '雨', 67: '雨',
                 71: '雪', 73: '雪', 75: '雪', 77: '雪',
                 80: 'にわか雨', 81: 'にわか雨', 82: 'にわか雨',
                 85: 'にわか雪', 86: 'にわか雪',
                 95: '雷雨', 96: '雷雨', 99: '雷雨'}
# 霧雨(51-57)と本降りの雨は分けて持つ。霧雨のコードは降水確率が低い日にも出るので、
# これを雨として扱うと、降水確率27%の日まで雨の日の組み方になってしまう。
_WX_DRIZZLE = {51, 53, 55, 56, 57}
_WX_RAIN = {61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
_WX_SNOW = set(range(71, 78)) | {85, 86}
_WX_FOG = {45, 48}
_WX_THUNDER = {95, 96, 99}
# 雨として扱う境目。降水確率が半分を超えたら雨、本降りのコードが出ていれば4割で雨とみなす。
_WX_WET_POP = 50
_WX_WET_POP_HARD = 40

def forecast_for(points, base_date):
    """points（[(lat, lng), ...]）と同じ順番で、その日の1時間ごとの天気を返す。
    各要素は {'code': [24個], 'pop': [24個]} か None。まとめて取れなければ None。"""
    if not points:
        return None
    ahead = (base_date - date.today()).days
    if ahead > _WX_AHEAD_MAX or ahead < -_WX_BACK_MAX:
        return None                       # 予報の届かない日。天候なしで組む
    pts = [(round(float(a), 2), round(float(b), 2)) for a, b in points][:_WX_MAX_POINTS]
    key = (base_date.isoformat(), tuple(pts))
    now = time.time()
    hit = _WX_CACHE.get(key)
    if hit and now - hit[0] < _WX_TTL:
        return hit[1]

    def _ask(hourly):
        q = urllib.parse.urlencode({
            'latitude': ','.join(str(a) for a, _ in pts),
            'longitude': ','.join(str(b) for _, b in pts),
            'hourly': hourly,
            'timezone': 'Asia/Tokyo',
            'start_date': base_date.isoformat(),
            'end_date': base_date.isoformat(),
        })
        with urllib.request.urlopen(f"{_WX_URL}?{q}", timeout=_WX_TIMEOUT) as r:
            return json.loads(r.read().decode('utf-8'))

    # 雲の高さ別の割合まで頼む。取れなければ、これまでの項目だけで取り直す。
    # 項目名がひとつでも通らないと返事そのものが来ないので、
    # 増やした項目のせいで天候が丸ごと無くなることのないようにしておく。（2026-10-10）
    raw = None
    try:
        raw = _ask('weather_code,precipitation_probability,cloud_cover,'
                   'cloud_cover_low,cloud_cover_mid,cloud_cover_high')
    except Exception as e:
        print(f"[WARN] 雲の高さ別を取れませんでした（通常の項目で取り直します）: {e}", flush=True)
        try:
            raw = _ask('weather_code,precipitation_probability')
        except Exception as e2:
            print(f"[WARN] 予報を取れませんでした: {e2}", flush=True)
            _WX_CACHE[key] = (now, None)
            return None

    blocks = raw if isinstance(raw, list) else [raw]   # 1地点だけのときは配列にならない
    out = []
    for b in blocks:
        h = (b or {}).get('hourly') or {}
        code = h.get('weather_code') or []
        pop = list(h.get('precipitation_probability') or [])
        if len(code) < 24:
            out.append(None)
            continue
        pop = (pop + [0] * 24)[:24]

        # 雲量（％）。空模様の『晴れ・曇り』の3段階では、星景写真に要る
        # 「どの程度の雲か」が分からないため、数で持っておく。
        # 雲量そのものは『空に占める割合』で、厚さではない。厚さの代わりに
        # 高さ別の割合を使う。下層・中層の雲は厚くて星を隠すが、
        # 高層（巻層雲）は薄曇りで、星は写る。（2026-10-10）
        def _col(name):
            v = list(h.get(name) or [])
            v = (v + [None] * 24)[:24]
            return [None if c is None else int(c) for c in v]

        out.append({'code': [int(c or 0) for c in code[:24]],
                    'pop': [int(p or 0) for p in pop],
                    'cloud': _col('cloud_cover'),
                    'cloud_low': _col('cloud_cover_low'),
                    'cloud_mid': _col('cloud_cover_mid')})
    while len(out) < len(pts):
        out.append(None)
    _WX_CACHE[key] = (now, out)
    print(f"[INFO] 予報を取得: {len(pts)}地点 / {base_date.isoformat()}", flush=True)
    return out

def wx_span(f, start_min, end_min):
    """その時間帯をひとまとめにして見る。降水確率は最大、空模様は悪いほうを採る。"""
    if not f:
        return None
    a = max(0, min(23, int(start_min // 60)))
    b = max(a, min(23, int((end_min + 59) // 60)))
    codes = f['code'][a:b + 1] or [0]
    pops = f['pop'][a:b + 1] or [0]
    clds = [c for c in (f.get('cloud') or [])[a:b + 1] if c is not None]
    # 厚い雲（下層＋中層）の覆い。重なり方は分からないので、
    # 互いに無関係に広がっているとみて合わせる。
    _lo = (f.get('cloud_low') or [])[a:b + 1]
    _mi = (f.get('cloud_mid') or [])[a:b + 1]
    thick = []
    for i in range(max(len(_lo), len(_mi))):
        lo = _lo[i] if i < len(_lo) else None
        mi = _mi[i] if i < len(_mi) else None
        if lo is None and mi is None:
            continue
        lo, mi = (lo or 0), (mi or 0)
        thick.append(100 - (100 - lo) * (100 - mi) / 100.0)
    worst = max(codes, key=lambda c: (c in _WX_THUNDER, c in _WX_SNOW, c in _WX_RAIN,
                                      c in _WX_DRIZZLE, c in _WX_FOG, c))
    pop = max(pops)
    hard = any(c in _WX_RAIN or c in _WX_SNOW for c in codes)
    return {
        'pop': pop,
        'sky': _WX_CODE_NAME.get(worst, '曇り'),
        'wet': pop >= _WX_WET_POP or (hard and pop >= _WX_WET_POP_HARD),
        'thunder': any(c in _WX_THUNDER for c in codes),
        'fog': any(c in _WX_FOG for c in codes),
        # その時間帯の平均の雲量（％）。取れなければ None。
        'cloud': (round(sum(clds) / len(clds)) if clds else None),
        # そのうち、厚い雲（下層＋中層）の覆い。星を隠すのはこちら。
        'cloud_thick': (round(sum(thick) / len(thick)) if thick else None),
    }

# 入賞作品に記録されていた天候のうち、雨がかりと呼べるもの
_WX_WET_NAMES = ('雨', '雪', '霧')

def wx_weight(s, span):
    """雨の日に、その撮影地がどれだけ向くかの重み。
    その地点の入賞作品に、雨・雪・霧で撮られたものが多いほど下がらない。
    滝や渓流、霧の出る林は雨のほうが撮れる、という実績がそのまま出る。
    使うのは記録された数だけで、こちらの好みは入れない。"""
    if not span or not span['wet']:
        return 1.0
    counts = s.get('weather')
    tot = sum(counts.values()) if counts else 0
    if not tot:
        return 0.7                         # 天候の記録が無い地点は中ほどに置く
    wet = sum(k for w, k in counts.items() if w in _WX_WET_NAMES)
    return max(0.45, min(1.15, 0.45 + 0.9 * (wet / tot)))

# 本番が天気で成立しない被写体。何があれば撮れないかを、被写体ごとに決めておく。
#   'dry'   … 雨や雪では撮れない。焼けも雲海も、降っていれば出ない
#   'sky'   … 雨や雪に加えて、空がふさがっていれば撮れない（星・天の川）
# ここに無い被写体（滝・紅葉など）は、雨でも撮れる。雨のほうが良いものさえある。
# そちらは wx_weight で重みを下げるだけにとどめ、候補からは外さない。（2026-10-10）
_SUBJECT_NEEDS = {
    '朝焼け': 'dry',
    '夕焼け': 'dry',
    '雲海':   'dry',
    '星':     'sky',
    '天の川': 'sky',
}

# 星景写真が成立しないとみなす、厚い雲（下層＋中層）の覆い（％）。
#
# はじめ「曇りなら外す」としていたが、厳しすぎた。ここで撮るのは天体写真ではなく
# 星景写真、つまり星空を含めた風景写真である。適度な雲は邪魔にならず、
# むしろ画になることもある。邪魔になるのは、空がふさがって星が見えないときだけ。
#
# 次に雲量（空に占める雲の割合）で見たが、これも足りなかった。雲量は厚さを
# 表さないので、「薄曇りが全天を覆う（星は写る）」と「厚い雲が全天を覆う
# （写らない）」が、どちらも100％になってしまう。
#
# いまは高さ別の割合を使う。下層・中層の雲は厚くて星を隠し、高層（巻層雲）は
# 薄曇りで、星は減光しながらも写る。全天が高層雲でも外さないのはそのため。
# 逆に、厚い雲が8割を超えて広がっていれば、晴れ間に賭けるには分が悪い。
# 境目は程度の問題で確かなものではないので、数を画面に出して判断に委ねる。（2026-10-10）
_STAR_THICK_MAX = 80
_STAR_CLOUD_MAX = 90   # 高さ別が取れないときに、全体の雲量で代える境目


def shot_possible(s, span, subject=None):
    """その撮影地の本番が、その時間帯の空で成立するか。
    予報が無ければ分からないので成立とみなす（組んだうえで、現地の判断に委ねる）。"""
    need = _SUBJECT_NEEDS.get(spot_subject(s, subject))
    if not need or not span:
        return True
    if span['wet']:
        return False
    if need == 'dry':
        return True
    thick = span.get('cloud_thick')
    if thick is not None:                  # 厚い雲（下層＋中層）がどれだけ広がっているか
        return thick < _STAR_THICK_MAX
    cloud = span.get('cloud')
    if cloud is not None:                  # 高さ別が取れないときは、全体の雲量で代える
        return cloud < _STAR_CLOUD_MAX
    return span['sky'] != '曇り'           # それも無ければ、空模様の名前で代える


# 雨で足元が悪くなりやすい地形。撮影地の名前から分かる範囲だけを見る。
# ここに無い場所の地面の状態は、手元のデータからは分からないので言わない。
_WX_SOFT_GROUND = ('遊水地', '湿原', '湿地', '干潟', '河川敷', '砂丘',
                   '棚田', '水田', '田んぼ', '湿原')

def _soft_ground(s):
    """その撮影地が、雨でぬかるみやすい地形だと名前から分かるか。"""
    t = f"{s.get('place') or ''}{s.get('name') or ''}{s.get('area') or ''}"
    return any(w in t for w in _WX_SOFT_GROUND)

# ──────────────── 撮影計画の組み立て ────────────────
# 「今日(または指定の日)、どこへ何を撮りに行くか」の行程を、方角ちがいで3案作る。
# 案を分ける主軸は方角。同じ方角の中で、帰着時刻に収まる1本を組む。
#
# 座標は市区町村までしか分からない(誌面データのMapLinkに緯度経度が無いため)。
# 同じ市内の複数地点は同じ座標になるので、移動時間はあくまで見込みである。
_PLAN_STAY_MIN = 60        # 1か所あたりの滞在時間(分)
_WAIT_FREE_MIN = 60        # 本番のための待ちのうち、無駄と見ない分。下の説明を参照
# 待ちに上限は設けない。いちど「2か所目以降は3時間まで」としてみたところ、
# 夕方まで間が空く夕焼けの地点が丸ごと消えた。空いた時間は、ほかに寄れる場所が
# 無いというだけのこと。待ち時間は画面に出るので、長ければ利用者が判断できる。（2026-10-10）
_PLAN_MAX_STOPS = 4        # 1案に入れる撮影地の上限
_PLAN_MIN_WORKS = 2        # 実績が1件だけの地域は計画に載せない
_PLAN_EARLY_MIN = 60       # 撮られている時間帯より、これ以上早く着けば「早い」とする(分)
_PLAN_LATE_MIN = 90        # 同じく、これ以上遅れれば「遅い」とする(分)
_PLAN_MAX_LEG_MIN = 240    # 1区間の移動時間の上限(分)。これを超える地点は行程に入れない
_PLAN_NIGHT_MARGIN = 60    # 日の入り後・日の出前これだけ離れた時間帯を「夜の被写体」とする(分)

# ── 狙い時刻 ──
# 被写体によって、本番の時刻の決まり方が違う。
#
# 朝焼け・雲海・夕焼け・星は、太陽で決まる。実績の時刻（Hour列の最頻値）は
# 全期間をならした値なので、夏に撮られた4時台が11月の計画に混ざってしまう。
# その日・その場所の日の出入りから出すほうが正しい。撮影地ごとの座標があるので、
# 同じ県でも東西で10分ほど違う日の出入りまで反映できる。
#
# 到着は本番の1時間前。準備に30分、余裕に30分。
# 星だけは別で、日の入の1時間前に着く。暗くなってからでは足元も構図も分からないので、
# 明るいうちに風景を確認し、準備を整えておく。（2026-10-09）
#
#   被写体 : (基準, 本番のずれ(分), 到着の決め方)
_SUN_TIMING = {
    '朝焼け': ('rise', -30, 'lead'),
    '雲海':   ('rise', -30, 'lead'),
    '夕焼け': ('set',   10, 'lead'),
    '星':     ('set',   90, 'set-60'),
    '天の川': ('set',   90, 'set-60'),
}
_ARRIVE_LEAD = 60        # 太陽で決まる被写体は、本番の1時間前に着く
_ARRIVE_LEAD_PLAIN = 30  # そのほかは、これまでどおり30分前
_SHOOT_MIN = 60          # 本番そのものに見ておく時間(分)


def spot_subject(s, subject=None):
    """その撮影地を代表する被写体。指定があって実績もあれば、それを優先する。"""
    subs = s.get('subjects')
    if subject and subs and subject in subs:
        return subject
    return subs.most_common(1)[0][0] if subs else ''


def spot_timing(s, base_date, subject=None):
    """その撮影地の (本番の分, 着いていたい分, 太陽で決めたか) を返す。
    分は、その日の0時からの通算。決められなければ (None, None, False)。"""
    subj = spot_subject(s, subject)
    rule = _SUN_TIMING.get(subj)
    if rule and base_date:
        anchor_name, off, how = rule
        rise, sets = sun_times(s['lat'], s['lng'], base_date)
        anchor = rise if anchor_name == 'rise' else sets
        if anchor is not None:
            best = anchor + off
            if how == 'set-60' and sets is not None:
                arrive = sets - 60
            else:
                arrive = best - _ARRIVE_LEAD
            return best, arrive, True
    bh = s['hours'].most_common(1)[0][0] if s.get('hours') else None
    if bh is None:
        return None, None, False
    return bh * 60, bh * 60 - _ARRIVE_LEAD_PLAIN, False


def stay_needed(s, arrive, stay_min):
    """その地点にいる時間。太陽で決まる被写体は、着いてから本番まで待つぶん長くなる。
    朝焼けなら、日の出1時間半前に着いて、日の出30分前が本番。撮り終えるまで2時間。"""
    b = s.get('best_min')
    if s.get('sun_based') and b is not None:
        return max(stay_min, (b - arrive) + _SHOOT_MIN)
    return stay_min


def is_night_min(best_min, sun_rise, sun_set):
    """その本番時刻が、夜の撮影かどうか。
    夜明け前(雲海・朝霧・朝焼けなど)は夜ではなく昼の行程に入れる。早発ちの話であって、
    夜の撮影ではないため。ここで夜と呼ぶのは『日の入りのあと』と『深夜0時〜3時』。"""
    if best_min is None:
        return False
    t = best_min
    if t < 3 * 60:
        return True
    if sun_set is None:
        return t >= 19 * 60
    return t > sun_set + _PLAN_NIGHT_MARGIN

def _window_bins(base_date, expand=False):
    """その日の前後(およそ-7〜+13日)にあたる旬の番号の集まりを返す。"""
    offs = {'上旬': 0, '中旬': 1, '下旬': 2}
    return {(m - 1) * 3 + offs.get(j, 1) for m, j in half_month_window(base_date, expand)}

def short_area(area, pref=None):
    """『埼玉県秩父市』から『秩父市』のように、県名を落とした呼び名にする。"""
    a = str(area or '')
    p = str(pref or '')
    return a[len(p):] if p and a.startswith(p) else a

def plan_spots(base_date, subject=None, expand=False):
    """その日が撮り頃の撮影地を、地域(Area)ごとにまとめて返す。"""
    want = _window_bins(base_date, expand)
    try:
        excl_authors, blocked_areas = load_exclusions()
    except Exception:
        excl_authors, blocked_areas = set(), []
    spots = {}
    for row in get_peak_index():
        if len(row) < 11:                      # 索引が古い形のときは何もしない
            return []
        lat, lng, bi, subs, winner, pa, hour, weather, area, pref, place = row
        if bi not in want:
            continue
        if winner and winner in excl_authors:
            continue
        if blocked_areas and any(b and b in pa for b in blocked_areas):
            continue
        if subject and subject not in subs:
            continue
        s = spots.get(area)
        if s is None:
            s = spots[area] = {'area': area, 'pref': pref, 'lat': lat, 'lng': lng,
                               'n': 0, 'subjects': Counter(), 'hours': Counter(),
                               'weather': Counter(), 'places': Counter()}
        s['n'] += 1
        for canon in subs:
            s['subjects'][canon] += 1
        if hour is not None:
            s['hours'][hour] += 1
        if weather:
            s['weather'][weather] += 1
        if place:
            s['places'][place] += 1
    return [s for s in spots.values() if s['n'] >= _PLAN_MIN_WORKS]

def _spot_view(s, subject=None):
    """1つの撮影地を、表示に使う形に整える。"""
    hour = s['hours'].most_common(1)[0][0] if s['hours'] else None
    subj = (subject if subject and subject in s['subjects']
            else (s['subjects'].most_common(1)[0][0] if s['subjects'] else ''))
    wx = s['weather'].most_common(2)
    place = s['places'].most_common(1)[0][0] if s['places'] else ''
    # 代表作品。build_plans が時期に合わせて付けていればそれを使う。
    # 付いていない経路から呼ばれたときは、受賞順位がいちばん高いものを使う。
    works = s.get('works') or works_for(s['area'])
    work = s.get('work') or (works[0] if works else {})
    return {'area': s['area'], 'name': short_area(s['area'], s['pref']),
            'place': place, 'lat': s['lat'], 'lng': s['lng'],
            'subject': subj, 'n': s['n'], 'best_hour': hour,
            # 本番の時刻。太陽で決まる被写体はその日の日の出入りから、
            # そのほかは実績の時間帯から。build_plans が先に出しておく。
            'best_min': s.get('best_min'),
            'arrive_min': s.get('arrive_min'),
            'best_time': hhmm(s.get('best_min')) if s.get('best_min') is not None else '',
            'sun_based': bool(s.get('sun_based')),
            'subjects': [c for c, _ in s['subjects'].most_common(3)],
            'weather': [{'name': w, 'n': k} for w, k in wx],
            'title': work.get('title', ''), 'winner': work.get('winner', ''),
            'award': work.get('award', ''), 'period': work.get('period', ''),
            'img': work.get('img', ''),
            # その撮影地の受賞作を数点。季節のちがいが並ぶ。
            'works': works}

def _timing(arrive, best_min):
    """到着が、その地点の本番に対して早いか遅いかを言葉にする。
    本番は分で受け取る（太陽で決まる被写体は時刻が時間単位に収まらないため）。"""
    if best_min is None:
        return ''
    diff = arrive - best_min
    if diff < -_PLAN_EARLY_MIN:
        return '早い'
    if diff > _PLAN_LATE_MIN:
        return '遅い'
    return 'ちょうど'

# 行程の良し悪しを測る重み。実績の数に、時間帯の合い具合を掛けて足し、
# 走っている時間を引く。ちょうどの時間に着ける地点を厚く評価する。
_TIMING_WEIGHT = {'ちょうど': 1.0, '早い': 0.85, '遅い': 0.35, '': 0.7}

def _route_score(route):
    """行程の良し悪しを数にする。大きいほど良い。
    かかる時間はそのまま引き、走っている時間はさらに少し重く見る。
    同じ帰着時刻なら、現地で待つほうがハンドルを握り続けるより楽なため。"""
    got = sum(st['n'] * _TIMING_WEIGHT.get(st.get('timing', ''), 0.7)
              * st.get('wx_weight', 1.0)
              for st in route['stops'])
    return (got - route['total_min'] / 60.0
            - route.get('drive_total_min', 0) / 60.0 * 0.3)

def _attach_wx(v, s, arrive, stay_min):
    """その撮影地に、滞在する時間帯の予報と重みを添える。予報が無ければ何もしない。"""
    span = wx_span(s.get('wx'), arrive, arrive + stay_min)
    if not span:
        return
    v['wx'] = {'sky': span['sky'], 'pop': span['pop'], 'wet': span['wet'],
               'thunder': span['thunder']}
    v['wx_weight'] = round(wx_weight(s, span), 3)
    v['soft_ground'] = bool(span['wet'] and _soft_ground(v))

def _route(origin, spots, leave_min, return_min, subject=None,
           stay_min=_PLAN_STAY_MIN, max_stops=_PLAN_MAX_STOPS,
           sun_rise=None, sun_set=None, order='hour', drop_late=False,
           max_leg=_PLAN_MAX_LEG_MIN, must=None, stay_over=False):
    """撮影地の集まりから、時刻のついた行程を1本組む。
    必ず落とすのは『帰り着けない』『日が暮れている』地点だけ。
    撮られている時間帯からのずれは『早い・遅い』として添える。
    drop_late=True のときは、間に合わない地点を捨てた組み方を試す。
    stay_over=True は宿泊前提。帰りの移動を勘定に入れず、最後の撮影地で終える。"""
    def fits(s, cur, now):
        """その地点を次に入れられるか。入れられるなら (移動分, 到着時刻, 待ち分, 滞在分) を返す。
        着くのが早すぎるときは、着いていたい時刻まで待つ。
        夕景の場所に朝着いても仕方がないため。

        着いていたい時刻は build_plans が先に出している（arrive_min）。
        朝焼け・雲海・夕焼けは本番の1時間前、そのほかは実績の時間帯の30分前。"""
        move = drive_minutes(haversine(cur[0], cur[1], s['lat'], s['lng']))
        if move > max_leg and s.get('area') != must:   # 1区間が長すぎる
            return None
        arrive = now + move
        tgt = s.get('arrive_min')
        wait = 0
        if tgt is not None and arrive < tgt:
            wait = tgt - arrive
            arrive += wait
        stay = stay_needed(s, arrive, stay_min)
        # 宿泊するなら帰りの移動は要らない。その日の終わりは最後の撮影地。
        home = 0 if stay_over else drive_minutes(
            haversine(s['lat'], s['lng'], origin[0], origin[1]))
        if arrive + stay + home > return_min:          # 帰り着けない（終われない）
            return None
        if sun_set is not None and arrive > sun_set:   # 着いたときには日が暮れている
            return None
        return (move, arrive, wait, stay)

    now, cur = leave_min, origin
    stops, used, drove = [], 0, 0

    if order in ('greedy', 'value'):
        # 1か所ずつ選んでいく。時間帯順に並べるだけだと地理を無視した行き来が起きるため。
        #   greedy … 近くて、遅れず、待ちの少ない地点を順に採る
        #   value  … その地点を足す値打ちが、余計にかかる時間に見合うかで決める。
        #            帰り道が延びる分も数えるので、遠くまで行って戻る形を避けられる
        rest = list(spots)
        while rest and used < max_stops:
            pick = None
            home_now = drive_minutes(haversine(cur[0], cur[1], origin[0], origin[1]))
            for s in rest:
                f = fits(s, cur, now)
                if not f:
                    continue
                move, arrive, wait, stay = f
                bm = s.get('best_min')
                if order == 'value':
                    home_new = drive_minutes(haversine(s['lat'], s['lng'],
                                                       origin[0], origin[1]))
                    # 現地での待ちは、まるごと無駄ではない。
                    # 朝焼けなら本番の1時間前に着くが、それは準備のためにそうしている。
                    # 「撮るために要る時間」まで減点すると、狙い時刻を太陽で決めた
                    # 朝焼け・夕焼けの地点が軒並み『割に合わない』と判定されてしまう。
                    # 1時間までは数えず、それを超えた分だけを、走る時間の半分の重みで見る。
                    # 現地で待つほうが、ハンドルを握り続けるより楽なため。（2026-10-10）
                    idle = max(0, wait - _WAIT_FREE_MIN)
                    extra = move + idle * 0.5 + (home_new - home_now)   # 余計にかかる時間
                    gain = (s['n'] * _TIMING_WEIGHT.get(_timing(arrive, bm), 0.7)
                            * wx_weight(s, wx_span(s.get('wx'), arrive,
                                                   arrive + stay)))
                    # 走る時間は採点と同じ重み(1.3倍)で見る。ここだけ等倍にしていると、
                    # 採点では割に合わない寄り道を、選ぶ段階で拾ってしまう
                    worth = gain - extra / 60.0 * 1.3
                    if worth <= 0 and s.get('area') != must:   # 足しても割に合わない
                        continue
                    key = (-worth, move)
                else:
                    late = max(0, arrive - bm) if bm is not None else 0
                    key = (move + late + max(0, wait - _WAIT_FREE_MIN) * 0.5, -s['n'])
                if pick is None or key < pick[0]:
                    pick = (key, s, move, arrive, wait, stay)
            if pick is None:
                break
            _, s, move, arrive, wait, stay = pick
            v = _spot_view(s, subject)
            tm = _timing(arrive, v.get('best_min'))
            v.update({'arrive': hhmm(arrive), 'leave': hhmm(arrive + stay),
                      'drive_min': move, 'stay_min': stay,
                      'wait_min': wait, 'timing': tm})
            _attach_wx(v, s, arrive, stay)
            stops.append(v)
            now, cur, used, drove = arrive + stay, (s['lat'], s['lng']), used + 1, drove + move
            rest.remove(s)
    else:
        if order == 'works':
            ordered = sorted(spots, key=lambda s: -s['n'])
        else:
            ordered = sorted(spots, key=lambda s: (s.get('best_min')
                                                   if s.get('best_min') is not None
                                                   else 12 * 60, -s['n']))
        for s in ordered:
            if used >= max_stops:
                break
            f = fits(s, cur, now)
            if not f:
                continue
            move, arrive, wait, stay = f
            v = _spot_view(s, subject)
            tm = _timing(arrive, v.get('best_min'))
            if drop_late and tm == '遅い':
                continue
            v.update({'arrive': hhmm(arrive), 'leave': hhmm(arrive + stay),
                      'drive_min': move, 'stay_min': stay,
                      'wait_min': wait, 'timing': tm})
            _attach_wx(v, s, arrive, stay)
            stops.append(v)
            now, cur, used, drove = arrive + stay, (s['lat'], s['lng']), used + 1, drove + move

    if not stops:
        return None
    if must and not any(s['area'] == must for s in stops):
        return None                      # 必ず寄る地点が入らなかった組み方は捨てる
    home = 0 if stay_over else drive_minutes(
        haversine(cur[0], cur[1], origin[0], origin[1]))
    # 1か所目で待つことになるなら、その分だけ遅く出ればよい。
    # 出発してから現地で10時間待つ、という案は計画として意味をなさない。
    start = leave_min + stops[0].get('wait_min', 0)
    stops[0]['wait_min'] = 0
    out = {'stops': stops, 'back': hhmm(now + home), 'depart': hhmm(start),
           'total_min': (now + home) - start,
           'drive_total_min': drove + home,
           'stay_total_min': sum(st.get('stay_min', stay_min) for st in stops),
           'stay_over': bool(stay_over),
           'last': {'lat': cur[0], 'lng': cur[1]},
           'last_end': now}

    # 1か所目が『遅い』なら、何時に出れば間に合うかを添える。
    # ただし希望より4時間以上早い出発になる場合は、助言として現実的でないので言わない。
    # 朝が雨で確定しているときは、早発ちしても朝の光は無い。だから勧めない。
    first = stops[0]
    morning_wet = bool((first.get('wx') or {}).get('wet'))
    if first['timing'] == '遅い' and first.get('best_min') is not None and not morning_wet:
        # 本番に間に合う出発時刻。着いていたい時刻から移動分をさかのぼる。
        _tgt = first.get('arrive_min')
        if _tgt is None:
            _tgt = first['best_min']
        want = _tgt - first['drive_min']
        if 0 <= want < leave_min and (leave_min - want) <= 4 * 60:
            out['suggest_leave'] = hhmm(want)

    # 逆に、朝が雨で光が期待できないなら、遅く出ても同じ行程を回れる。
    # 帰着（宿泊なら撮影終了）までの余りの中で、2時間までずらせることを伝える。
    if morning_wet and first.get('best_min') is not None and first['best_min'] <= 9 * 60:
        slack = return_min - (now + home)
        shift = min(slack, 120)
        if shift >= 30:
            out['suggest_later'] = hhmm(start + shift)
            out['suggest_later_min'] = shift
    return out

def _best_route(origin, group, leave_min, return_min, subject,
                stay_min=_PLAN_STAY_MIN, max_stops=_PLAN_MAX_STOPS,
                sun_rise=None, sun_set=None,
                max_leg=_PLAN_MAX_LEG_MIN, must=None, stay_over=False):
    """同じ方角の中で、組み方を何通りか試して、いちばん良い行程を選ぶ。"""
    best = None
    for order, drop in (('value', False), ('greedy', False), ('hour', False),
                        ('hour', True), ('works', False)):
        r = _route(origin, group, leave_min, return_min, subject,
                   stay_min=stay_min, max_stops=max_stops,
                   sun_rise=sun_rise, sun_set=sun_set, order=order, drop_late=drop,
                   max_leg=max_leg, must=must, stay_over=stay_over)
        if r and (best is None or _route_score(r) > _route_score(best)):
            best = r
    return best

def _span(total_min):
    """分を『4時間30分』の形にする。"""
    h, m = divmod(int(total_min or 0), 60)
    return f"{h}時間{m}分" if m else f"{h}時間"

def _spot_label(s):
    """見出しに出す呼び名。撮影地の名前があればそれを、無ければ市区町村を使う。"""
    n = str(s.get('place') or '').strip()
    for suf in ('付近', '周辺'):
        if n.endswith(suf):
            n = n[:-len(suf)]
    n = n.strip() or str(s.get('name') or '').strip()
    return (n[:16] + '…') if len(n) > 17 else n     # 途中で切ると読みにくいので、よほど長いときだけ

def _how(total_min, stay_over=False):
    """見出しの末尾。宿泊前提のときは帰りを数えていないので『往復』とは言わない。"""
    return (f"現地泊 行程約{_span(total_min)}" if stay_over
            else f"往復約{_span(total_min)}")

def _label(direction, stops, total_min, stay_over=False):
    """『北へ — 渡良瀬遊水地〜光徳沼ほか2か所／往復約12時間52分』のような見出し。
    市区町村名より撮影地の名前のほうが、読む人の目を引くため。
    どこからどこまで回る日なのかが分かるよう、最初と最後の地点を出す。
    宿泊前提のときは帰りを勘定に入れていないので『往復』とは言わない。"""
    names, seen = [], set()
    for s in stops:
        n = _spot_label(s)
        if n and n not in seen:
            seen.add(n)
            names.append(n)
    if not names:
        where = ''
    elif len(names) == 1:
        where = names[0]
    elif len(names) == 2:
        where = f"{names[0]}〜{names[1]}"
    else:
        where = f"{names[0]}〜{names[-1]}ほか{len(names) - 2}か所"
    return f"{direction}へ — {where}／{_how(total_min, stay_over)}"

def _plan_cautions(r):
    """その行程に添える注意書き。予報と、撮影地の名前から分かることだけを言う。
    地面の状態や装備は現地の判断が優先で、ここでは一般に言えることに留める。
    手元のデータに無い場所ごとの事情は書かない。"""
    stops = r.get('stops') or []
    if not any((s.get('wx') or {}).get('wet') for s in stops):
        return []
    out = []
    th = [s for s in stops if (s.get('wx') or {}).get('thunder')]
    if th:
        out.append(f"{'・'.join(_spot_label(s) for s in th[:2])}で雷の予報が出ています。"
                   "開けた水辺や稜線は避け、車に戻れるようにしてください。")
    soft = [s for s in stops if s.get('soft_ground')]
    if soft:
        out.append(f"{'・'.join(_spot_label(s) for s in soft[:2])}は雨で足元がぬかるみます。"
                   "長靴は中に水や泥が入ると脱げにくく、かえって危ないことがあります。"
                   "防水の靴とスパッツのほうが安全で、動ける範囲もふだんより狭く見てください。")
    if r.get('suggest_later'):
        out.append(f"朝は雨の見込みで、朝の斜光は望めません。"
                   f"{r['suggest_later']}に出ても同じ行程を回れます。")
    last = stops[-1] if stops else None
    if last and (last.get('wx') or {}).get('wet'):
        out.append("夕方も雨の見込みです。暗くなるのが早いので、"
                   "無理に粘らず切り上げる判断も持っておいてください。")
    out.append("予報は変わります。現地での見きわめを優先してください。")
    return out

def build_plans(origin_latlng, origin_name, base_date, leave_min, return_min,
                subject=None, max_plans=3, must_latlng=None, must_name=None,
                easy=False, stay_over=False):
    """撮影計画を最大3案つくる。
    ふだんは方角ちがいの3案。行きたい撮影地(must_latlng)が指定されたときは、
    行き先が定まっているので方角では分けず、組み立て方を変えた3案にする。
    easy=True は『手軽に』(片道90分以内・寄るのは1〜2か所)。
    stay_over=True は『撮影地で行程を終える』(宿泊前提。帰りの移動を数えない)。"""
    origin = (float(origin_latlng[0]), float(origin_latlng[1]))
    max_leg = 90 if easy else _PLAN_MAX_LEG_MIN
    cap = 2 if easy else _PLAN_MAX_STOPS
    spots = plan_spots(base_date, subject)
    if not spots:
        spots = plan_spots(base_date, subject, expand=True)   # 時期を広げて拾い直す

    rise, sets = sun_times(origin[0], origin[1], base_date)

    # 行きたい撮影地が指定されていれば、いちばん近い撮影地をそれとみなす。
    # 座標は市区町村までなので、少し離れていても同じ場所として扱う。
    anchor = None
    if must_latlng:
        try:
            ml = (float(must_latlng[0]), float(must_latlng[1]))
            near = [(haversine(ml[0], ml[1], s['lat'], s['lng']), s) for s in spots]
            near = [x for x in near if x[0] <= 15]
            if near:
                anchor = min(near, key=lambda x: (x[0], -x[1]['n']))[1]
        except (TypeError, ValueError):
            anchor = None

    usable, night = [], []
    for s in spots:
        km = haversine(origin[0], origin[1], s['lat'], s['lng'])
        move = drive_minutes(km)
        # 狙い時刻はここで1回だけ出す。行程を組むときは候補を何度も見比べるので、
        # そのたびに日の出入りを計算し直すのは無駄。落とす候補より先に出しておくのは、
        # 行き先を名指しされた地点（anchor）が、ここから外れても使われるため。
        s['best_min'], s['arrive_min'], s['sun_based'] = spot_timing(s, base_date, subject)
        if move > max_leg and s is not anchor:         # 片道が遠すぎる
            continue
        # 往復と最低限の滞在が入らない。宿泊するなら帰りは数えない。
        need = move + 30 if stay_over else move * 2 + 30
        if leave_min + need > return_min:
            continue
        s['km'], s['drive'] = km, move
        s['dir'] = bearing_label(bearing(origin[0], origin[1], s['lat'], s['lng']))
        if is_night_min(s['best_min'], rise, sets) and s is not anchor:
            night.append(s)                            # 夜が本番の被写体は昼の行程に入れない
        else:
            usable.append(s)

    # 候補の撮影地ぶんの予報を、1回の呼び出しでまとめて取る。
    # 出発地1点では、行き先ごとの違い（午後から回復する方角がある）が見えないため。
    cand = usable + night

    # 行く時期に近い代表作品を、撮影地ごとに付けておく。予報と同じ考え方で、
    # 行程を組む前にここで済ませる。
    _tbin = bin_index(base_date.month, base_date.day)
    for s in cand:
        s['works'] = works_for(s['area'], _tbin)
        s['work'] = s['works'][0] if s['works'] else {}

    fc = forecast_for([(s['lat'], s['lng']) for s in cand], base_date)
    weather_dropped = []
    if fc:
        for s, f in zip(cand, fc):
            s['wx'] = f

        # その日の空では本番が成立しない撮影地を、候補から外す。
        # 朝焼けを狙う場所へ、朝が雨の日に案内しても仕方がない。
        # 名指しされた行き先（anchor）だけは外さない。本人が決めたことなので、
        # 天気を添えたうえで、行くかどうかは本人に委ねる。（2026-10-10）
        def _wx_ok(s):
            if not s.get('sun_based') or s is anchor:
                return True
            b0 = s.get('arrive_min')
            b1 = s.get('best_min')
            if b0 is None or b1 is None:
                return True
            # 見る時間帯。焼けや雲海は準備中の空も含めて見るが、
            # 星は本番の前後だけを見る。日の入前の雲で落としては意味がない。
            if _SUBJECT_NEEDS.get(spot_subject(s, subject)) == 'sky':
                w0, w1 = b1 - 60, b1 + _SHOOT_MIN
            else:
                w0, w1 = b0, b1 + _SHOOT_MIN
            if shot_possible(s, wx_span(s.get('wx'), w0, w1), subject):
                return True
            weather_dropped.append({'area': s['area'],
                                    'subject': spot_subject(s, subject)})
            return False

        usable = [s for s in usable if _wx_ok(s)]
        night = [s for s in night if _wx_ok(s)]
        if weather_dropped:
            print('[INFO] 天気で本番が成立しない撮影地を %d か所外しました'
                  % len(weather_dropped), flush=True)

    by_dir = defaultdict(list)
    for s in usable:
        by_dir[s['dir']].append(s)
    ranked = sorted(by_dir.items(), key=lambda kv: (-sum(x['n'] for x in kv[1]), kv[0]))

    def night_near(dname, last, after_min):
        """その方角にある『夜の部』の候補を、最後の撮影地からの移動つきで返す。"""
        out = []
        for s in sorted((x for x in night if x['dir'] == dname), key=lambda x: -x['n']):
            move = drive_minutes(haversine(last['lat'], last['lng'], s['lat'], s['lng']))
            if move > max_leg:
                continue
            v = _spot_view(s, subject)
            home = drive_minutes(haversine(s['lat'], s['lng'], origin[0], origin[1]))
            # 星は、明るいうちに着いて風景を確認し、準備を整えておく。
            # 着いていたい時刻は日の入の1時間前、本番はその2時間半後になる。
            best_t = s.get('best_min') if s.get('best_min') is not None else 20 * 60
            arr_t = s.get('arrive_min') if s.get('arrive_min') is not None else best_t
            arrive = max(after_min + move, arr_t)
            start = max(arrive, best_t)
            if arrive - (after_min + move) > 4 * 60:
                continue                  # 待ち時間が長すぎる。同じ日の続きとは言えない
            v.update({'drive_min': move, 'from_last': move,
                      'arrive': hhmm(arrive), 'start': hhmm(start),
                      'back': hhmm(start + 60 if stay_over else start + 60 + home)})
            # 本番前後の雲量。星景が成立するかは程度の問題なので、
            # こちらで決めきらず、数を見せて現地の判断に委ねる。（2026-10-10）
            _nsp = wx_span(s.get('wx'), best_t - 60, best_t + _SHOOT_MIN)
            if _nsp:
                if _nsp.get('cloud') is not None:
                    v['cloud'] = _nsp['cloud']
                if _nsp.get('cloud_thick') is not None:
                    v['cloud_thick'] = _nsp['cloud_thick']
            out.append(v)
            if len(out) >= 3:
                break
        return out

    plans = []

    def add(r, dname, kind, label):
        """組めた行程を、重複していなければ加える。"""
        if not r:
            return False
        seq = tuple(s['area'] for s in r['stops'])
        if any(tuple(s['area'] for s in p['stops']) == seq for p in plans):
            return False
        r.update({'direction': dname, 'kind': kind, 'label': label})
        r['night_options'] = night_near(dname, r['last'], r['last_end'])
        r['cautions'] = _plan_cautions(r)
        plans.append(r)
        return True

    if anchor is not None:
        # 行き先が定まっているので、方角ではなく組み立て方で分ける
        must = anchor['area']
        others = [s for s in usable if s is not anchor]
        base_leg = drive_minutes(haversine(origin[0], origin[1],
                                           anchor['lat'], anchor['lng']))
        onway = []
        for s in others:                      # 本命への道のりから大きく外れない地点
            a = drive_minutes(haversine(origin[0], origin[1], s['lat'], s['lng']))
            b = drive_minutes(haversine(s['lat'], s['lng'], anchor['lat'], anchor['lng']))
            if a + b - base_leg <= 45:
                onway.append(s)
        same_dir = [s for s in others if s['dir'] == anchor['dir']]
        aname = must_name or _spot_view(anchor, subject)['name']

        for stay in (240, 180, 120, _PLAN_STAY_MIN):
            r = _best_route(origin, [anchor], leave_min, return_min, subject,
                            stay_min=stay, max_stops=1, sun_rise=rise, sun_set=sets,
                            max_leg=max_leg, must=must, stay_over=stay_over)
            if r and add(r, anchor['dir'], 'じっくり',
                         f"{aname}をじっくり — 滞在{stay // 60}時間"
                         f"{'半' if stay % 60 else ''}／{_how(r['total_min'], stay_over)}"):
                break

        # 道中にも同じ方角にも寄れる場所が無いことはある(都心の一点を指定した場合など)。
        # そのときのために、方角を問わず入るものを足す組み方も試す。
        for kind, group in (('行きがけに寄る', [anchor] + onway),
                            ('前後に足す', [anchor] + same_dir),
                            ('ほかにも寄る', [anchor] + others)):
            if len(plans) >= max_plans:
                break
            r = _best_route(origin, group, leave_min, return_min, subject,
                            max_stops=cap if easy else 3, sun_rise=rise, sun_set=sets,
                            max_leg=max_leg, must=must, stay_over=stay_over)
            add(r, anchor['dir'], kind,
                f"{aname}を軸に — {kind}／{_how(r['total_min'], stay_over)}" if r else '')
    else:
        for dname, group in ranked:
            if len(plans) >= max_plans:
                break
            r = _best_route(origin, group, leave_min, return_min, subject,
                            max_stops=cap, sun_rise=rise, sun_set=sets, max_leg=max_leg,
                            stay_over=stay_over)
            if r:
                add(r, dname, '方角',
                    _label(dname, r['stops'], r['total_min'], stay_over))

        # 方角が3つ取れない日は、いちばん濃い方角の中で性格を変えた案で埋める
        if plans and len(plans) < max_plans and ranked:
            dname, group = ranked[0]
            for kind, stay, cap2 in (('滞在重視', 120, 2), ('地点数重視', 45, 4)):
                if len(plans) >= max_plans:
                    break
                r = _best_route(origin, group, leave_min, return_min, subject,
                                stay_min=stay, max_stops=min(cap2, cap),
                                sun_rise=rise, sun_set=sets, max_leg=max_leg,
                                stay_over=stay_over)
                if r:
                    add(r, dname, kind,
                        _label(dname, r['stops'], r['total_min'], stay_over)
                        + f"（{kind}）")

    plans.sort(key=_route_score, reverse=True)   # 良い行程から並べる
    for p in plans:                              # 組み立てにだけ使った値は返さない
        p.pop('last', None)
        p.pop('last_end', None)

    return {
        'date': base_date.isoformat(),
        'origin': {'name': origin_name or DEFAULT_ORIGIN_NAME,
                   'lat': origin[0], 'lng': origin[1]},
        'leave': hhmm(leave_min), 'return': hhmm(return_min),
        'subject': subject or '',
        'sun': {'rise': hhmm(rise), 'set': hhmm(sets)},
        'spots_considered': len(usable),
        'night_considered': len(night),
        # その日の空では本番が成立せず、候補から外した撮影地。
        # 「候補が少ない」理由を黙って飲み込まないために返す。
        'weather_dropped': len(weather_dropped),
        'weather_dropped_subjects': sorted({d['subject'] for d in weather_dropped if d['subject']}),
        'max_leg_min': max_leg,
        'easy': bool(easy),
        'stay_over': bool(stay_over),
        'weather_used': bool(fc),
        'must': ({'requested': True, 'found': anchor is not None,
                  'name': (must_name or (_spot_view(anchor, subject)['name']
                                         if anchor else '')),
                  'area': anchor['area'] if anchor else ''}
                 if must_latlng else {'requested': False}),
        'plans': plans,
        'notice': ('移動時間は直線距離の1.3倍を時速45kmで走った見込みです。'
                   '撮影地の座標は市区町村までのため、実際の道のりとは前後します。'
                   + (f'1区間の移動が{max_leg}分を超える撮影地は入れていません。'
                      if max_leg % 60 else
                      f'1区間の移動が{max_leg // 60}時間を超える撮影地は入れていません。')
                   + ('天候は撮影地ごとの予報を見て、雨のときは雨で撮られた実績のある'
                      '撮影地を厚く見ています。' if fc else
                      'この日は予報が届かないため、天候は見ていません。')
                   + ('宿泊するものとして、帰りの移動は数えていません。'
                      if stay_over else '')),
    }


@app.route("/api/michinoeki", methods=["GET", "OPTIONS"])
def api_michinoeki():
    """指定した地点の近くの道の駅を、近い順に返す。
    撮影ノート（リファレンス側 /planner）から呼ばれるのでCORSを許可する。

    lat, lng   中心の緯度経度（必須）
    radius     何km以内を探すか（既定50、上限300）
    limit      最大何件返すか（既定5、上限20）
    """
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = "https://reference.fukei-shashin.co.jp"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Max-Age"] = "86400"
        return resp

    try:
        lat = float(request.args.get("lat", ""))
        lng = float(request.args.get("lng", ""))
    except ValueError:
        return jsonify({"error": "lat/lng required"}), 400
    try:
        radius = float(request.args.get("radius", "50"))
    except ValueError:
        radius = 50.0
    radius = max(1.0, min(300.0, radius))
    try:
        limit = int(request.args.get("limit", "5"))
    except ValueError:
        limit = 5
    limit = max(1, min(20, limit))

    near = []
    for e in get_michinoeki():
        d = haversine(lat, lng, e['lat'], e['lng'])
        if d <= radius:
            near.append((d, e))
    near.sort(key=lambda x: x[0])

    stations = [{
        "name": e['name'], "pref": e['pref'], "city": e['city'],
        "lat": e['lat'], "lng": e['lng'], "site": e['site'],
        "distance_km": round(d, 1),
    } for d, e in near[:limit]]

    resp = jsonify({
        "stations": stations,
        "total_in_radius": len(near),
        "notice": "道の駅は施設により営業時間や利用のルールが異なります。"
                  "ご利用の際は事前に各施設のWEBサイトなどでご確認ください。",
        "source": "出典：国土交通省ウェブサイト「道の駅」一覧、Wikidata",
    })
    resp.headers["Access-Control-Allow-Origin"] = "https://reference.fukei-shashin.co.jp"
    return resp

# ──────────────── サービスエリア・パーキングエリア ────────────────
# 高速道路のSA・PA。道の駅と同じ扱いで、ルート沿いの立ち寄り先として使う。
#
# 道の駅と違い、国が座標つきの一覧を出していない。そこで OpenStreetMap から
# 一度だけ取り込んでFirestoreに置く（下の /_import-sapa）。以後は道の駅と同じで、
# 読み取りはメモリに載せて使い回すだけなので、呼び出しごとの費用は発生しない。
# 出典表記：© OpenStreetMap contributors（ODbL）。表示する画面に必ず添える。
_SAPA = None
_SAPA_AT = 0.0
_SAPA_TTL = 24 * 3600

def get_sapa():
    """SA・PAの一覧を返す。無ければ読む。期限が切れていれば読み直す。"""
    global _SAPA, _SAPA_AT
    now = time.time()
    if _SAPA is not None and (now - _SAPA_AT) < _SAPA_TTL:
        return _SAPA
    if not db:
        return _SAPA or []
    rows = []
    try:
        for doc in db.collection('sapa').stream():
            d = doc.to_dict() or {}
            try:
                rows.append({'name': d.get('name', ''), 'pref': d.get('pref', ''),
                             'city': d.get('city', ''), 'site': '',
                             'kind': d.get('kind', 'SA'),
                             'base': d.get('base', d.get('name', '')),
                             'direction': d.get('direction', ''),
                             'lat': float(d['lat']), 'lng': float(d['lng'])})
            except (KeyError, TypeError, ValueError):
                continue
    except Exception:
        import traceback
        print(f"[ERROR] get_sapa: {traceback.format_exc()}", flush=True)
        return _SAPA or []
    print(f"[INFO] sapa loaded: {len(rows)}件", flush=True)
    _SAPA, _SAPA_AT = rows, now
    return rows


def nearest_city(lat, lng):
    """いちばん近い市区町村を city_latlng.json から引いて (県, 市区町村) を返す。
    OpenStreetMap は所在地を持たないので、座標から当てる。表示に使うだけなので、
    役所の位置を基準にしたこの当て方で足りる。"""
    best, bd = None, None
    for full, (clat, clng) in CITY_LATLNG.items():
        d = (clat - lat) ** 2 + ((clng - lng) * 0.81) ** 2     # 比較だけなので平方のまま
        if bd is None or d < bd:
            bd, best = d, full
    if not best:
        return "", ""
    m = PREF_RE.match(best)
    pref = m.group(1) if m else ""
    return pref, best[len(pref):]


# ── 名前の読み取り ──
# OpenStreetMap の名前は付き方がまちまちで、「佐野SA (上り)」「佐野サービスエリア」
# 「池田PA」のように略称と正式名称、上下線の有無が入り混じっている。
# 種別は OpenStreetMap のタグ（services / rest_area）より名前のほうが当てになる。
# 実際、池田PA も日光口PA も services と付けられていた。
# 名前にSA・PAの別が無いもの（「宇奈月ダム駐車場」「一向一揆の里」など）は
# 高速道路の施設と言い切れないので取り込まない。道の駅が紛れているのもここで落ちる。
_DIR_RE = re.compile(r'[（(\[【]?\s*(上り線|下り線|上り|下り|上線|下線|のぼり|くだり)\s*[)）\]】]?')

def parse_sapa_name(raw):
    """名前から (表示名, 基の名前, 種別, 上下) を取り出す。SA・PAでなければ None。"""
    if not raw:
        return None
    s = unicodedata.normalize("NFKC", str(raw)).strip()
    m = _DIR_RE.search(s)
    direction = ""
    if m:
        d = m.group(1)
        direction = "上り" if d.startswith(("上", "のぼ")) else "下り"
        s = _DIR_RE.sub("", s).strip()
    low = s.upper()
    if "パーキングエリア" in s or re.search(r'(?<![A-Z])PA(?![A-Z])', low):
        kind = "PA"
    elif "サービスエリア" in s or re.search(r'(?<![A-Z])SA(?![A-Z])', low):
        kind = "SA"
    else:
        return None
    base = s
    for w in ("パーキングエリア", "サービスエリア"):
        base = base.replace(w, "")
    base = re.sub(r'(?<![A-Z])(PA|SA)(?![A-Z])', "", base, flags=re.I)
    base = base.strip(" \u3000・-−—()（）")
    if not base:
        return None
    return (f"{base}{kind}", base, kind, direction)


# 上下線集約型として知られているSA・PA（2026-10-04 石川さん調べ）。
# OpenStreetMap に上り・下りの両方が登録されていれば、そちらで集約型と判断できる。
# ここはその裏付けが取れないとき——片方しか登録が無いとき——の手がかりに使う。
# 裏付けのあるものと区別して「とされています」と控えめに出し、色も分ける。
# 同じ名前で集約型でない施設が別の高速道路にある場合（例：鈴鹿PAは新名神と東名阪の
# 両方にある）に取り違える余地があるため、断定はしない。
COMBINED_SAPA_BASES = {
    "岡崎", "NEOPASA岡崎", "清水", "NEOPASA清水", "浜名湖", "EXPASA浜名湖",
    "土山", "宝塚北", "鈴鹿", "錦秋湖", "南相馬鹿島", "菖蒲", "太田強戸",
    "来島海峡", "鳥の海", "高滝湖",
}

def side_of_route(path, idx, lat, lng):
    """進行方向から見て、その施設が左右どちらにあるかを返す（'L' か 'R'、不明なら ''）。
    日本は左側通行なので、走りながら入れるのは左側にある施設。
    上下線で別々に登録されているSA・PAを選り分けるのに使う。"""
    i0 = max(0, idx - 1)
    i1 = min(len(path) - 1, idx + 1)
    if i0 == i1:
        return ""
    course = bearing(path[i0][0], path[i0][1], path[i1][0], path[i1][1])
    to = bearing(path[idx][0], path[idx][1], lat, lng)
    rel = (to - course + 540) % 360 - 180
    return "L" if rel < 0 else "R"


@app.route("/api/_import/sapa", methods=["POST"])
def api_import_sapa():
    """SA・PAの一覧を受け取ってFirestoreに入れる。取り込み専用。
    CHECK_KEY を X-Check-Key ヘッダーで送れる人だけが使える。

    本文（JSON）
      items   [{name, lat, lng, kind}] の配列。1回あたり500件まで
    同じ場所を二度入れないよう、文書IDは名前と座標から作る。何度流し込んでも増えない。
    """
    if not _check_key_ok():
        abort(404)
    if not db:
        return jsonify({"ok": False, "error": "Firestoreにつながっていません"}), 500
    global _SAPA, _SAPA_AT
    body = request.get_json(silent=True) or {}

    # 入れ直すとき用。古いものを残したまま入れると、整理前の名前が混ざってしまう。
    if body.get("replace"):
        n = 0
        while True:
            docs = list(db.collection('sapa').limit(400).stream())
            if not docs:
                break
            b = db.batch()
            for d in docs:
                b.delete(d.reference)
            b.commit()
            n += len(docs)
            if n > 20000:
                break
        _SAPA, _SAPA_AT = None, 0.0
        return jsonify({"ok": True, "deleted": n})

    items = body.get("items")
    if not isinstance(items, list) or not items:
        return jsonify({"ok": False, "error": "items が空です"}), 400
    if len(items) > 500:
        return jsonify({"ok": False, "error": "1回500件までにしてください"}), 400

    saved, skipped = 0, 0
    batch = db.batch()
    n_in_batch = 0
    for it in items:
        try:
            raw = str(it.get("name", "")).strip()
            lat = float(it["lat"]); lng = float(it["lng"])
        except (KeyError, TypeError, ValueError):
            skipped += 1; continue
        if not (20 < lat < 50) or not (120 < lng < 150):
            skipped += 1; continue          # 日本の外は入れない
        parsed = parse_sapa_name(raw)
        if not parsed:
            skipped += 1; continue          # SA・PAと言い切れない名前は入れない
        name, base, kind, direction = parsed
        pref, city = nearest_city(lat, lng)
        # 同じ施設の上り・下りは別物として持つ。文書IDは名前と上下と概略の座標から作る。
        doc_id = re.sub(r'[^0-9A-Za-zぁ-んァ-ン一-龥]', '',
                        f"{base}{kind}{direction}{round(lat,2)}{round(lng,2)}")[:120] \
                 or f"{round(lat,4)}_{round(lng,4)}"
        batch.set(db.collection('sapa').document(doc_id), {
            "name": name, "base": base, "kind": kind, "direction": direction,
            "lat": lat, "lng": lng,
            "pref": pref, "city": city, "source": "OpenStreetMap", "raw": raw,
        })
        saved += 1; n_in_batch += 1
        if n_in_batch >= 400:
            batch.commit(); batch = db.batch(); n_in_batch = 0
    if n_in_batch:
        batch.commit()

    _SAPA, _SAPA_AT = None, 0.0        # 次の検索で読み直させる
    return jsonify({"ok": True, "saved": saved, "skipped": skipped})


@app.route("/api/_import/sapa/count", methods=["GET"])
def api_import_sapa_count():
    """いま何件入っているかを返す。取り込みの前後を見比べるため。"""
    if not _check_key_ok():
        abort(404)
    try:
        n = sum(1 for _ in db.collection('sapa').stream()) if db else 0
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "count": n})


_IMPORT_SAPA_PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SA・PAの取り込み</title>
<style>
 body{font-family:-apple-system,BlinkMacSystemFont,"Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif;
  max-width:780px;margin:0 auto;padding:22px 16px 90px;font-size:17px;line-height:1.75;
  color:#1b2a24;background:#faf9f5;-webkit-text-size-adjust:100%}
 h1{font-size:23px;margin:0 0 6px}
 p.lead{color:#5b6b64;margin:0 0 20px;font-size:16px}
 label{display:block;font-weight:600;margin:16px 0 6px;font-size:16px}
 input{width:100%;font-size:17px;padding:11px 12px;border:1px solid #cfd8d4;
  border-radius:8px;box-sizing:border-box;background:#fff}
 button{font-size:17px;padding:12px 20px;border-radius:8px;border:0;cursor:pointer;
  background:#143d2e;color:#fff;margin:14px 8px 0 0}
 button.sub{background:#fff;color:#143d2e;border:1px solid #9fb3aa}
 button:disabled{opacity:.45;cursor:default}
 .card{background:#fff;border:1px solid #e4e8e6;border-radius:10px;padding:16px 18px;margin:16px 0}
 #msg{margin:16px 0;padding:13px 15px;border-radius:8px;display:none;font-size:16px;
  background:#e8f0ec;color:#143d2e;white-space:pre-wrap}
 #msg.ng{background:#fdeaea;color:#9b2c2c}
 table{width:100%;border-collapse:collapse;margin-top:8px;font-size:15px}
 td,th{text-align:left;padding:6px 8px;border-bottom:1px solid #eceeed}
 th{font-size:14px;color:#5b6b64}
 .note{font-size:14px;color:#5b6b64}
</style></head><body>
<h1>SA・PAの取り込み</h1>
<p class="lead">高速道路のサービスエリア・パーキングエリアを OpenStreetMap から取り込みます。
一度行えば、以後は道の駅と同じようにサーバーの中だけで完結します。
<br>全国を13の範囲に分けて取りに行きます。5分ほどかかります。
<br><b>取れた範囲から順に登録します。</b>どこかで取れなくても、ほかの範囲の成果は残ります。
取れなかった範囲は、あとでもう一度押せば追加されます（消さずに足すので重複しません）。
名前にSA・PAの別が無いもの（道の駅や一般の駐車場）は取り込みません。</p>

<label for="key">CHECK_KEY</label>
<input id="key" type="password" autocomplete="off" placeholder="Render の環境変数に設定した値">
<div>
  <button id="count" class="sub">いま何件あるか見る</button>
  <button id="run">取り込む</button>
  <button id="clear" class="sub">全部消す</button>
</div>

<div id="msg"></div>
<pre id="log" style="display:none;background:#fff;border:1px solid #e4e8e6;border-radius:10px;
  padding:12px 14px;font-size:14px;line-height:1.7;max-height:220px;overflow:auto;
  white-space:pre-wrap;margin:14px 0"></pre>
<div id="out"></div>

<p class="note" style="margin-top:28px">
出典：© OpenStreetMap contributors（ODbL）。所在地（県・市区町村）は座標から
いちばん近い市区町村を当てたもので、OpenStreetMap の情報ではありません。
</p>

<script>
var $ = function (s) { return document.querySelector(s); };
function key() { return $("#key").value.trim(); }
function say(t, ng) { var m = $("#msg"); m.style.display = "block"; m.className = ng ? "ng" : ""; m.textContent = t; }
function log(t) { var o = $("#log"); o.style.display = "block"; o.textContent += t + "\\n"; o.scrollTop = o.scrollHeight; }

var OVERPASS = [
  "https://overpass-api.de/api/interpreter",
  "https://overpass.kumi.systems/api/interpreter",
  "https://overpass.osm.jp/api/interpreter"
];

/* 範囲が広いと時間切れ（504 や Query timed out）になる。細かく割って軽くする。
   少し重なっているが、同じ施設は文書IDが同じになるので重複しない。 */
var BOXES = [
  ["北海道（北）",     "43.0,139.2,46.0,146.2"],
  ["北海道（南）",     "41.0,139.2,43.1,146.0"],
  ["東北（北）",       "39.2,138.9,41.9,142.3"],
  ["東北（南）",       "36.6,138.9,39.3,142.0"],
  ["関東（東）",       "34.9,139.2,37.1,141.1"],
  ["関東（西）・甲信", "34.9,137.6,37.3,139.3"],
  ["東海",            "34.3,136.4,35.9,138.0"],
  ["北陸・信越",       "35.8,135.8,38.3,138.5"],
  ["近畿",            "33.4,134.4,36.0,136.6"],
  ["中国",            "33.6,130.9,36.0,134.6"],
  ["四国",            "32.6,131.9,34.7,135.0"],
  ["九州（北）",       "32.4,129.3,34.3,132.3"],
  ["九州（南）・沖縄", "23.9,122.7,32.6,132.2"]
];

/* relation は数が少ない割に重いので外す。SA・PAはほとんどが点か面で登録されている。 */
function query(bbox) {
  return '[out:json][timeout:90];('
    + 'node["highway"~"^(services|rest_area)$"](' + bbox + ');'
    + 'way["highway"~"^(services|rest_area)$"](' + bbox + ');'
    + ');out center tags;';
}

function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

function fetchBox(label, bbox) {
  var tries = [];
  for (var k = 0; k < 2; k++) {
    for (var i = 0; i < OVERPASS.length; i++) { tries.push(OVERPASS[i]); }
  }
  var n = 0;
  function go() {
    if (n >= tries.length) { return Promise.reject(new Error("取得できませんでした")); }
    var url = tries[n++];
    say("取得中… " + label + "（" + n + " / " + tries.length + " 回目）");
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: "data=" + encodeURIComponent(query(bbox))
    }).then(function (r) {
      return r.text().then(function (t) { return { status: r.status, text: t }; });
    }).then(function (res) {
      if (res.status !== 200) { throw new Error("HTTP " + res.status); }
      var j;
      try { j = JSON.parse(res.text); } catch (e) { throw new Error("返事を読み取れませんでした"); }
      /* 混んでいるとき、Overpass は 200 を返しながら中身を空で返すことがある。
         高速道路の無い範囲はひとつも無いので、0件は失敗とみなして試し直す。
         （2026-10-04 夜、関東（西）・甲信 が 0件のまま「取れた」扱いになった） */
      if (!j.elements || !j.elements.length) {
        throw new Error(j.remark ? String(j.remark).slice(0, 60) : "中身が空でした");
      }
      return j.elements;
    }).catch(function (e) {
      log("　" + label + "：" + e.message + " → 間を置いて試し直します");
      return wait(5000).then(go);
    });
  }
  return go();
}

function normalise(elements) {
  var out = [], seen = {};
  elements.forEach(function (el) {
    var t = el.tags || {};
    var name = t["name:ja"] || t.name || "";
    if (!name) { return; }
    var lat = el.lat, lon = el.lon;
    if (lat == null && el.center) { lat = el.center.lat; lon = el.center.lon; }
    if (lat == null || lon == null) { return; }
    var kind = (t.highway === "rest_area") ? "PA" : "SA";
    var k = name + "@" + lat.toFixed(3) + "," + lon.toFixed(3);
    if (seen[k]) { return; }
    seen[k] = 1;
    out.push({ name: name, lat: lat, lng: lon, kind: kind });
  });
  return out;
}

function post(body) {
  return fetch("/api/_import/sapa", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Check-Key": key() },
    body: JSON.stringify(body)
  }).then(function (r) {
    if (r.status === 404) { throw new Error("CHECK_KEY が違うか、Render の環境変数に設定されていません"); }
    return r.json();
  });
}

function sendItems(items) {
  var chunks = [];
  for (var i = 0; i < items.length; i += 400) { chunks.push(items.slice(i, i + 400)); }
  var saved = 0, skipped = 0;
  function next() {
    if (!chunks.length) { return Promise.resolve({ saved: saved, skipped: skipped }); }
    return post({ items: chunks.shift() }).then(function (r) {
      if (r.ok === false) { throw new Error(r.error || "登録に失敗しました"); }
      saved += r.saved || 0; skipped += r.skipped || 0;
      return next();
    });
  }
  return next();
}

function showCount() {
  if (!key()) { say("CHECK_KEY を入れてください", true); return; }
  fetch("/api/_import/sapa/count", { headers: { "X-Check-Key": key() } })
    .then(function (r) {
      if (r.status === 404) { throw new Error("CHECK_KEY が違うか、設定されていません"); }
      return r.json();
    })
    .then(function (j) { say("いま登録されているSA・PA：" + j.count + "件"); })
    .catch(function (e) { say(e.message, true); });
}

function clearAll() {
  if (!key()) { say("CHECK_KEY を入れてください", true); return; }
  if (!confirm("登録されているSA・PAをすべて消します。よろしいですか？")) { return; }
  post({ replace: true })
    .then(function (j) { say((j.deleted || 0) + "件を消しました。"); })
    .catch(function (e) { say(e.message, true); });
}

/* 地方ごとに、取れたそばから登録する。
   1つの地方が取れなくても、ほかの地方の成果は残る。
   （以前は1地方の失敗で全部を捨てていた。2026-10-04 改め） */
function run() {
  if (!key()) { say("CHECK_KEY を入れてください", true); return; }
  $("#run").disabled = true; $("#count").disabled = true; $("#clear").disabled = true;
  $("#log").textContent = "";
  log("取得を始めます（" + BOXES.length + "の範囲に分けて聞きます）");

  var okList = [], total = 0;
  var remain = BOXES.slice();      // まだ取れていない範囲
  var pass = 0, MAX_PASS = 3;

  /* 取れなかった範囲は、ひと回りしたあとで間を置いて試し直す。
     混雑は波があるので、同じ範囲を続けて叩くより、ほかを回ってから
     戻ってきたほうが通りやすい。（2026-10-05 追加） */
  function onePass() {
    pass += 1;
    var queue = remain.slice();
    var failed = [];
    if (pass > 1) {
      log("取れなかった " + queue.length + "の範囲を、もう一度回ります（" + pass + "周目）");
    }

    function nextBox() {
      if (!queue.length) { return Promise.resolve(); }
      var b = queue.shift();
      return fetchBox(b[0], b[1]).then(function (els) {
        var items = normalise(els);
        log("　" + b[0] + "：取得 " + items.length + "件 → 登録しています");
        if (!items.length) {
          okList.push(b[0] + " 0件");
          log("　" + b[0] + "：名前の付いたものがありませんでした");
          return;
        }
        return sendItems(items).then(function (r) {
          total += r.saved;
          okList.push(b[0] + " " + r.saved + "件");
          log("　" + b[0] + "：登録 " + r.saved + "件／見送り " + r.skipped + "件");
        });
      }).catch(function (e) {
        failed.push(b);
        log("　" + b[0] + "：✕ " + e.message + "（この範囲は後回しにします）");
      }).then(function () {
        return wait(2000);
      }).then(nextBox);
    }

    return nextBox().then(function () {
      remain = failed;
      if (!remain.length || pass >= MAX_PASS) { return; }
      log("　少し待ってから、取れなかった範囲を試し直します");
      return wait(15000).then(onePass);
    });
  }

  onePass().then(function () {
    var msg = "終わりました。登録 " + total + "件。\\n"
      + "取れた範囲：" + (okList.join("、") || "なし");
    if (remain.length) {
      msg += "\\n取れなかった範囲：" + remain.map(function (b) { return b[0]; }).join("、")
        + "\\nこの範囲は、あとでもう一度押せば追加されます（消さずに足すので重複しません）。";
    }
    say(msg, remain.length > 0);
  }).catch(function (e) {
    say(e.message, true);
  }).then(function () {
    $("#run").disabled = false; $("#count").disabled = false; $("#clear").disabled = false;
  });
}

$("#run").addEventListener("click", run);
$("#count").addEventListener("click", showCount);
$("#clear").addEventListener("click", clearAll);
try { var s = sessionStorage.getItem("rmkey"); if (s) { $("#key").value = s; } } catch (e) {}
$("#key").addEventListener("change", function () {
  try { sessionStorage.setItem("rmkey", key()); } catch (e) {}
});
</script>
</body></html>
"""


@app.route("/_import-sapa", methods=["GET"])
def page_import_sapa():
    """ブラウザで開く取り込み画面。OpenStreetMapへの問い合わせはこの画面（＝利用者の
    ブラウザ）が行う。サーバー側からは外部に出られないため。"""
    if not os.environ.get("CHECK_KEY", ""):
        abort(404)
    resp = make_response(_IMPORT_SAPA_PAGE)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


# ──────────────── 撮影地の座標（Place単位） ────────────────
# これまで撮影地の座標は Area（市区町村）の文字列からしか引いていなかった。
# そのため「群馬県前橋市｜覚満淵」は前橋市役所の位置になり、赤城山の上にある
# 実際の覚満淵とは直線23km・標高差1,300m離れていた。市区町村を引けない Area
# （誤記や合併で消えた旧町村名）は県の重心まで落ちていて、作品14,704件のうち
# 2,191件（14.9%）がそうだった。行程の移動時間はこの座標で測っているので、
# 計画そのものが地理的に成り立っていなかった。
#
# ここでは Area と Place をつないだ文字列をそのまま地図に問い合わせ、
# 撮影地ごとの座標を Firestore に持つ。一度取れば以後は読むだけ。
# （2026-10-05）

_PLACEGEO_COL = 'PlaceGeo'
_PLACEGEO = None
_PLACEGEO_AT = 0.0
_PLACEGEO_TTL = 6 * 3600

def placegeo_id(area, place):
    """Area と Place の組から、Firestoreの文書IDを作る。
    地名には / や . が入りうるので、そのままIDには使えない。"""
    raw = (str(area or '').strip() + '|' + str(place or '').strip())
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:24]

def get_placegeo():
    """撮影地ごとの座標表を返す。{(area, place): (lat, lng)}
    使えないと判断したもの（status='ng'）は入れない。"""
    global _PLACEGEO, _PLACEGEO_AT
    now = time.time()
    if _PLACEGEO is not None and (now - _PLACEGEO_AT) < _PLACEGEO_TTL:
        return _PLACEGEO
    if not db:
        return _PLACEGEO if _PLACEGEO is not None else {}
    out = {}
    try:
        for doc in db.collection(_PLACEGEO_COL).stream():
            d = doc.to_dict() or {}
            if d.get('status') == 'ng':
                continue
            try:
                out[(d.get('area', ''), d.get('place', ''))] = (float(d['lat']), float(d['lng']))
            except (KeyError, TypeError, ValueError):
                continue
    except Exception as e:
        print('[WARN] PlaceGeo read failed: %s' % e)
        return _PLACEGEO if _PLACEGEO is not None else {}
    _PLACEGEO, _PLACEGEO_AT = out, now
    print('[INFO] PlaceGeo: %d places' % len(out))
    return out

def place_latlng(area, place):
    """撮影地そのものの座標。無ければ None（呼び出し側が市区町村へ落とす）。"""
    if not place:
        return None
    return get_placegeo().get((str(area or '').strip(), str(place or '').strip()))


def spot_key(area, place):
    """同じ撮影地かどうかを判める鍵。候補を並べるとき、同じ場所を二度出さないために使う。

    これまでは市区町村（Area）を鍵にしていた。日光市の作品はどれも「日光市」なので、
    中禅寺湖も戦場ヶ原も霧降高原もひとまとめに扱われ、1件しか出せなかった。
    1,523の市区町村に 4,022 の撮影地が埋もれていたことになる。

    いまは撮影地ごとの座標（PlaceGeo）があるので、まず座標で見る。
    小数第3位（およそ100m四方）に丸めるので、「覚満淵」「おぼろ沼（覚満淵）」のような
    表記ゆれも同じ場所としてまとまる。座標が無いものは Place の文字、
    それも無いものは市区町村に落とす。（2026-10-09）"""
    a = str(area or '').strip()
    p = str(place or '').strip()
    ll = place_latlng(a, p)
    if ll:
        return ('g', round(ll[0], 3), round(ll[1], 3))
    if p:
        return ('p', a, p)
    return ('a', a)

# ── 地図への問い合わせ ──

def geocode_detail(query):
    """住所文字列から座標と確からしさを取る。
    戻り値 {'lat','lng','type','partial','pref','formatted'}。
    見つからなければ None。問い合わせ自体が断られたら例外を投げる
    （呼び出し側で打ち切るため。残りを空振りさせても仕方がない）。"""
    if not GEOCODING_API_KEY:
        raise RuntimeError('GOOGLE_GEOCODING_API_KEY が設定されていません')
    url = ('https://maps.googleapis.com/maps/api/geocode/json?address='
           + urllib.parse.quote(query) + '&language=ja&region=jp&key=' + GEOCODING_API_KEY)
    with urllib.request.urlopen(url, timeout=10) as res:
        data = json.loads(res.read())
    st = data.get('status', '')
    if st in ('OVER_QUERY_LIMIT', 'REQUEST_DENIED', 'INVALID_REQUEST', 'UNKNOWN_ERROR'):
        # Google は断った理由を error_message に書いてくる。
        # これを捨てると「断られた」としか分からず、原因にたどり着けない。
        detail = str(data.get('error_message') or '').strip()
        raise RuntimeError('地図からの返事：%s%s' % (st, ('／' + detail) if detail else ''))
    if st != 'OK' or not data.get('results'):
        return None
    r0 = data['results'][0]
    loc = r0['geometry']['location']
    pref = ''
    for c in r0.get('address_components', []):
        if 'administrative_area_level_1' in (c.get('types') or []):
            pref = c.get('long_name', '')
            break
    return {'lat': float(loc['lat']), 'lng': float(loc['lng']),
            'type': r0['geometry'].get('location_type', ''),
            'partial': bool(r0.get('partial_match')),
            'pref': pref,
            'formatted': r0.get('formatted_address', '')}

def _strip_pref_suffix(s):
    """『長野県』→『長野』。ただし削ると1文字になるものは削らない。
    『京都』から「都」を落とすと『京』になり、『京都府』と別物になってしまう。"""
    t = re.sub(r'[都道府県]$', '', s)
    return t if len(t) >= 2 else s

def _pref_match(a, b):
    """県名が同じかどうか。『長野県』と『長野』は同じものとみなす。
    地図はときどき県名を英語（Nagano など）で返してくる。
    その場合は突き合わせようがないので、ここでは判断せず隔たりで見る。"""
    a = str(a or '').strip()
    b = str(b or '').strip()
    if not a or not b:
        return True
    if re.fullmatch(r'[A-Za-z \-\.]+', b):
        return True
    return _strip_pref_suffix(a) == _strip_pref_suffix(b)

def judge_place_geo(area, pref, got):
    """取れた座標を使ってよいか決める。
       ok    … そのまま使う
       check … 使うが、目で確かめたほうがよい
       ng    … 使わない（市区町村の座標のままにする）
    戻り値 (status, reason, km)。km は市区町村の中心からの隔たり。

    partial_match（地名が完全には一致しない）は見ない。
    4,988か所を集めて確かめたところ、partial_match が付いたものと付かないものとで
    精度の内訳も市区町村中心からの隔たりもほとんど変わらなかった。
    「問い合わせ文字列に余計な語が入っていた」というだけで、場所が違うことを
    意味していなかった。これで要確認が2,375件から数十件に減る。（2026-10-05）"""
    if not got:
        return 'ng', '見つかりませんでした', None
    city = work_latlng(area, pref)
    km = (haversine(city[0], city[1], got['lat'], got['lng'])
          if city else None)
    if not _pref_match(pref, got.get('pref')):
        # 県境の撮影地は、隣の県として返ってくる。渋峠は長野県側から引いても
        # 群馬県中之条町が返る。市区町村の中心から近ければ、同じ場所とみなす。
        if km is None or km > 30:
            return 'ng', '別の県が返ってきました（%s）' % got.get('pref', ''), km
        return 'ok', '県境のため隣の県として返っています（%s）' % got.get('pref', ''), km
    if km is not None and km > 60:
        return 'ng', '市区町村の中心から%.0fkm離れています' % km, km
    if km is not None and km < 0.2:
        return 'check', '市区町村の中心と同じ場所です（地名が見つかっていない可能性）', km
    return 'ok', '', km

_PLACE_SEP = re.compile(r'[・／/、,･]')
_GEO_RANK = {'ROOFTOP': 3, 'RANGE_INTERPOLATED': 2, 'GEOMETRIC_CENTER': 2, 'APPROXIMATE': 1}

def geocode_place_best(area, place):
    """Area と Place をつないで問い合わせる。戻り値 (結果, 使った文字列)。

    『赤城山・覚満淵』のように区切り記号でつないだ地名は、地図が前半だけを拾って
    大まかな位置を返すことがある。実際、覚満淵は4通りの表記のうち3つが
    「赤城山」に落ちていた。区切りの後ろでも問い合わせ、細かいほうを採る。"""
    tries = [(area + ' ' + place).strip()]
    if _PLACE_SEP.search(place):
        tail = _PLACE_SEP.split(place)[-1].strip()
        if tail and tail != place:
            tries.append((area + ' ' + tail).strip())
    best, best_q = None, tries[0]
    for q in tries:
        got = geocode_detail(q)
        if not got:
            continue
        if best is None or _GEO_RANK.get(got['type'], 0) > _GEO_RANK.get(best['type'], 0):
            best, best_q = got, q
    return best, best_q

# ── 取り込み ──

_PLACE_PAIRS = None
_PLACE_PAIRS_AT = 0.0

def place_pairs():
    """作品データから (Area, Place, 件数) を、件数の多い順に並べて返す。
    件数の多い撮影地から先に片付けたほうが、途中で止めても効き目が大きい。"""
    global _PLACE_PAIRS, _PLACE_PAIRS_AT
    now = time.time()
    if _PLACE_PAIRS is not None and (now - _PLACE_PAIRS_AT) < 3600:
        return _PLACE_PAIRS
    cnt = Counter()
    for d in get_photos():
        a = (d.get('Area') or '').strip()
        p = (d.get('Place') or '').strip()
        if a and p:
            cnt[(a, p)] += 1
    _PLACE_PAIRS = [(a, p, n) for (a, p), n in cnt.most_common()]
    _PLACE_PAIRS_AT = now
    return _PLACE_PAIRS

@app.route("/api/_geocode/places/run", methods=["POST"])
def api_geocode_places_run():
    """(Area, Place) の組をいくつか地図に問い合わせて、座標を書き足す。
    1回の呼び出しを短く保つため、少しずつ進める。続きは next から。"""
    if not _check_key_ok():
        abort(404)
    if not db:
        return jsonify({"ok": False, "error": "Firestoreに繋がっていません"}), 500
    body = request.get_json(silent=True) or {}
    try:
        offset = max(0, int(body.get('offset', 0)))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = max(1, min(30, int(body.get('limit', 15))))
    except (TypeError, ValueError):
        limit = 15

    pairs = place_pairs()
    col = db.collection(_PLACEGEO_COL)
    batch = db.batch()
    asked, writes, skipped = 0, 0, 0
    tally = {'ok': 0, 'check': 0, 'ng': 0}
    rows = []
    i = offset
    scan_cap = i + limit * 40        # 済みばかり続いても、1回の呼び出しが延びすぎないように
    err = ''
    while i < len(pairs) and asked < limit and i < scan_cap:
        area, place, n = pairs[i]
        i += 1
        ref = col.document(placegeo_id(area, place))
        try:
            if ref.get().exists:
                skipped += 1
                continue
        except Exception as e:
            err = '読み取りに失敗しました：%s' % e
            break
        pref = extract_pref(area)
        query = (area + ' ' + place).strip()
        try:
            got, query = geocode_place_best(area, place)
        except RuntimeError as e:
            err = str(e)
            break
        except Exception as e:
            got, err = None, '問い合わせに失敗しました：%s' % e
        asked += 1
        status, reason, km = judge_place_geo(area, pref, got)
        tally[status] = tally.get(status, 0) + 1
        row = {'area': area, 'place': place, 'pref': pref, 'works': n,
               'query': query, 'status': status, 'reason': reason,
               'km_from_city': round(km, 2) if km is not None else None,
               'at': firestore.SERVER_TIMESTAMP}
        if got:
            row.update({'lat': got['lat'], 'lng': got['lng'],
                        'type': got['type'], 'partial': got['partial'],
                        'got_pref': got['pref'], 'formatted': got['formatted']})
        batch.set(ref, row)
        writes += 1
        rows.append({'area': area, 'place': place, 'status': status,
                     'reason': reason, 'km': row['km_from_city']})
        if err:
            break
    if writes:
        try:
            batch.commit()
        except Exception as e:
            return jsonify({"ok": False, "error": "書き込みに失敗しました：%s" % e}), 500
    return jsonify({"ok": True, "next": i, "total": len(pairs),
                    "asked": asked, "saved": writes, "skipped": skipped,
                    "tally": tally, "rows": rows, "error": err})

@app.route("/api/_geocode/places/count", methods=["GET"])
def api_geocode_places_count():
    """いくつ片付いたかを数える。"""
    if not _check_key_ok():
        abort(404)
    if not db:
        return jsonify({"ok": False, "error": "Firestoreに繋がっていません"}), 500
    tally = {'ok': 0, 'check': 0, 'ng': 0}
    total = 0
    try:
        for doc in db.collection(_PLACEGEO_COL).stream():
            d = doc.to_dict() or {}
            s = d.get('status', '')
            tally[s] = tally.get(s, 0) + 1
            total += 1
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "done": total, "pairs": len(place_pairs()), "tally": tally})

# 文字化けした作品データの直し方。鍵は壊れている (Area, Place)、値は正しい (Area, Place)。
# 元のCSVには壊れた行が1つも無く、Firestoreに取り込んだあとで壊れていた。
# UTF-8の文字列をShift_JISとして読んだときの壊れ方で、逆の手順で戻したうえ、
# 元のCSVと突き合わせて47件すべて正しい名前を確かめてある。（2026-10-05）
_MOJIBAKE_FIX = {
    ('蜈オ蠎ォ逵御ク臥伐蟶�', '鮟呈サ�'):
        ('兵庫県三田市', '黒滝'),
    ('蜿ー貉セ譁ー蛹怜ク�', '譫怜��?譛ィ譽芽干驕�'):
        ('台湾新北市', '林初?木棉花道'),
    ('螂郁憶逵悟ョ�髯蟶よヲ帛次蛹コ', '鮴埼式貂楢ーキ'):
        ('奈良県宇陀市榛原区', '龍鎮渓谷'),
    ('螂郁憶逵悟・郁憶蟶�', '蜀�謌仙ッコ'):
        ('奈良県奈良市', '円成寺'),
    ('螂郁憶逵梧。應コ募ク�', '螟ァ隘ソ蝨ー蛹コ'):
        ('奈良県桜井市', '大西地区'),
    ('螂郁憶逵梧擲蜷蛾大正譚�', '謚慕浹縺ョ貊�'):
        ('奈良県東吉野村', '投石の滝'),
    ('螟ァ蛻�逵檎罰蟶�蟶�', '逕ア蟶�蟾晄ク楢ーキ'):
        ('大分県', '由布川渓谷'),
    ('螻ア蜿」逵檎セ守・「蟶�', '遘句翠蜿ー'):
        ('山口県美祢市', '秋吉台'),
    ('螻ア蜿」逵碁亟蠎懷ク�', '螟ァ蟷ウ螻ア繝ュ繝シ繝励え繧ァ繧、螻ア鬆るァ�蜻ィ霎コ'):
        ('山口県防府市', '大平山ロープウェイ山頂駅周辺'),
    ('螻ア蠖「逵碁」ッ雎顔伴', '逋ス蟾昴ム繝\uf8f0'):
        ('山形県飯豊町', '白川ダム'),
    ('螻ア譴ィ逵悟漉繧「繝ォ繝励せ蟶�', '荳ュ逋ス蟲ー螻ア'):
        ('山梨県南アルプス市', '中白峰山'),
    ('蟯宣�懃恁豬キ豢・逕コ', '豢・螻句キ�'):
        ('岐阜県海津町', '津屋川'),
    ('蟯宣�懃恁鄒取ソ�蜉\uf8f0闌ょク�', '遞イ闡画ア\uf8f0蜈ャ蝨�'):
        ('岐阜県美濃加茂市', '稲葉池公園'),
    ('諢帷衍逵梧眠蝓主ク�', '蟾エ蟾�'):
        ('愛知県新城市', '巴川'),
    ('諢帷衍逵瑚ア顔伐蟶ょクょ\uf8f0エ逕コ', '逾櫁カ頑ク楢ーキ'):
        ('愛知県豊田市市場町', '神越渓谷'),
    ('譁ー貎溽恁譁ー貎溷クょ圏蛹コ遖丞ウカ貎�', '遖丞ウカ貎�'):
        ('新潟県新潟市北区福島潟', '福島潟'),
    ('譁ー貎溽恁譚台ク雁ク�', '轢ャ豕「豬キ蟯ク'):
        ('新潟県村上市', '瀬波海岸'),
    ('譁ー貎溽恁譚台ク雁ク�', '荳倶クュ蟲カ'):
        ('新潟県村上市', '下中島'),
    ('譚ア莠ャ驛ス譁ー螳ソ蛹コ', '譁ー螳ソ蠕。闍�'):
        ('東京都新宿区', '新宿御苑'),
    ('貊玖ウ逵碁聞豬懷ク�', '貉門イク驕楢キッ'):
        ('滋賀県長浜市', '湖岸道路'),
    ('逾槫・亥キ晉恁譚セ逕ー逕コ', '譛譏主ッコ蜿イ霍。蜈ャ蝨�'):
        ('神奈川県松田町', '最明寺史跡公園'),
    ('逾槫・亥キ晉恁遘ヲ驥主ク�', '蝪斐ヮ蟯ウ螻ア鬆�'):
        ('神奈川県秦野市', '塔ノ岳山頂'),
    ('遖丈コ慕恁豎\uf8f0逕ー逕コ', '縺九★繧画ゥ�'):
        ('福井県池田町', 'かずら橋'),
    ('遖丞イ。逵悟万螟壽婿蟶�', '諱倶ココ蝮ょ捉霎コ'):
        ('福岡県喜多方市', '恋人坂周辺'),
    ('遖丞ウカ逵御シ壽エ・闍・譚セ蟶�', '蠕。螻ア縺ョ譟ソ逡�'):
        ('福島県会津若松市', '御山の柿畑'),
    ('遖丞ウカ逵檎ヲ丞ウカ蟶�', '縺、縺ー縺上m隹キ'):
        ('福島県福島市', 'つばくろ谷'),
    ('遖丞ウカ逵�', '荳顔ケ∝イ。'):
        ('福島県', '上繁岡'),
    ('遖丞ウカ逵�', '蝟懷、壽婿蟶�'):
        ('福島県', '喜多方市'),
    ('鄒、鬥ャ逵碁ォ伜エ主ク�', '隕ウ髻ウ螻ア'):
        ('群馬県高崎市', '観音山'),
    ('闌ィ蝓守恁隨\uf8f0髢灘ク�', '菴千區螻ア鮗灘�ャ蝨�'):
        ('茨城県笠間市', '佐白山麓公園'),
    ('髟キ驥守恁荳玖ォ剰ィェ逕コ', '蜈ォ蟲カ繧ア蜴滓ケソ蜴�'):
        ('長野県下諏訪町', '八島ケ原湿原'),
    ('髟キ驥守恁荳顔伐蟶�', '遶懊Ω豐「繝繝\uf8f0'):
        ('長野県上田市', '竜ヶ沢ダム'),
    ('髟キ驥守恁譚セ譛ャ蟶ゆケ鈴檮', '荵鈴檮鬮伜次 蝟�莠秘ヮ縺ョ貊�'):
        ('長野県松本市乗鞍', '乗鞍高原 善五郎の滝'),
    ('髟キ驥守恁譚セ譛ャ蟶ゆケ鈴檮', '荳企ォ伜慍'):
        ('長野県松本市乗鞍', '上高地小梨平'),
    ('髟キ驥守恁遶狗ァ醍伴', '螂ウ逾樊ケ�'):
        ('長野県立科町', '女神湖'),
    ('髟キ驥守恁邇区サ晄搗', '貊晁カ企寔關ス'):
        ('長野県王滝村', '滝越集落'),
    ('髟キ驥守恁鬟ッ逕ー蟶ゆク頑搗', '鮗サ邵セ縺ョ驥�'):
        ('長野県飯田市上村', '麻績の里'),
    ('髟キ驥守恁鬟ッ逕ー蟶ゆク頑搗', '蠎ァ蜈牙ッコ鮗サ邵セ縺ョ驥後遏ウ蝪壽。�'):
        ('長野県飯田市上村', '座光寺麻績の里\u3000石塚桜'),
    ('髟キ驥守恁鬧偵Ω譬ケ蟶�', '螟ゥ遶懷キ晏\uf8f0、髦イ'):
        ('長野県駒ヶ根市', '天竜川堤防'),
    ('髟キ驥守恁鬧偵Ω譬ケ蟶�', '蜈牙燕蟇コ'):
        ('長野県駒ヶ根市', '光前寺'),
    ('髟キ驥守恁鬧偵Ω譬ケ蟶�', '闖�繝主床 蜿、蝓守匳螻ア蜿」'):
        ('長野県駒ヶ根市', '菅ノ台 古城登山口'),
    ('髟キ驥守恁鬧偵Ω譬ケ蟶�', '縺ゅ°縺、縺阪�ョ蝪�'):
        ('長野県駒ヶ根市', 'あかつきの塔'),
    ('髟キ驥守恁鬧偵Ω譬ケ蟶�', '譴ィ繝取惠'):
        ('長野県駒ヶ根市', '梨ノ木'),
    ('髟キ驥守恁鮗サ邵セ譚�', '閨夜ォ伜次'):
        ('長野県麻績村', '聖高原'),
    ('鬥吝キ晉恁荳芽ア雁クりゥォ髢鍋伴', '邏ォ髮イ蜃コ螻ア'):
        ('香川県三豊市詫間町', '紫雲出山'),
    ('鬥吝キ晉恁隕ウ髻ウ蟇コ蟶ょ、ァ驥主次逕コ', '莠暮未豎\uf8f0'):
        ('香川県観音寺市大野原町', '井関池'),
    ('鬥吝キ晉恁隕ウ髻ウ蟇コ蟶�', '螟ァ驥主次逕コ莠暮未豎\uf8f0'):
        ('香川県観音寺市', '大野原町井関池'),
}

@app.route("/api/_fix/mojibake", methods=["GET", "POST"])
def api_fix_mojibake():
    """Master_Photos の文字化けした Area・Place を、正しい名前に書き戻す。
    GET は何件当てはまるかを数えるだけ。POST で実際に書き換える。
    元の値は FixedFrom に残すので、あとから何を変えたか辿れる。"""
    if not _check_key_ok():
        abort(404)
    if not db:
        return jsonify({"ok": False, "error": "Firestoreに繋がっていません"}), 500
    apply = (request.method == "POST")
    found, done, rows = 0, 0, []
    try:
        batch, n = db.batch(), 0
        for doc in db.collection('Master_Photos').stream():
            d = doc.to_dict() or {}
            key = (d.get('Area', ''), d.get('Place', ''))
            fix = _MOJIBAKE_FIX.get(key)
            if not fix:
                continue
            found += 1
            if len(rows) < 60:
                rows.append('%s｜%s　→　%s｜%s' % (key[0][:14], key[1][:12], fix[0], fix[1]))
            if not apply:
                continue
            batch.set(doc.reference, {'Area': fix[0], 'Place': fix[1],
                                      'FixedFrom': '%s｜%s' % key}, merge=True)
            # 壊れた名前で集めた座標は用済み。消しておけば「集める」で入り直す。
            try:
                db.collection(_PLACEGEO_COL).document(placegeo_id(key[0], key[1])).delete()
            except Exception:
                pass
            done += 1
            n += 1
            if n >= 300:
                batch.commit()
                batch, n = db.batch(), 0
        if apply and n:
            batch.commit()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    if apply and done:
        # 作品データを読み直させる。索引も作り直す。
        global _PHOTOS, _PHOTOS_AT, _PEAK_INDEX, _PEAK_INDEX_AT, _PLACE_PAIRS, _PLACE_PAIRS_AT
        _PHOTOS, _PHOTOS_AT = None, 0.0
        _PEAK_INDEX, _PEAK_INDEX_AT = None, 0.0
        _PLACE_PAIRS, _PLACE_PAIRS_AT = None, 0.0
        # 保存してある索引も消す。残っていると、起き抜けに古い（壊れたままの）
        # 索引が復元されて、直したことが表に出てこない。
        try:
            for ref in db.collection(_SNAP_COLL).list_documents():
                ref.delete()
        except Exception as e:
            print('[WARN] 索引の消去に失敗: %s' % e, flush=True)
    return jsonify({"ok": True, "table": len(_MOJIBAKE_FIX), "found": found,
                    "fixed": done, "applied": apply, "rows": rows})


# ──────────────── Area（市区町村）の名前ちがいを直す ────────────────
# 誌面データの Area 欄に、実在しない市区町村が入っているものがある。
# 県を取り違えたもの（福岡県喜多方市＝喜多方市は福島県）、字を間違えたもの
# （三重県松坂市＝正しくは松阪市）など。
#
# 撮影地の候補を出すとき、Area は見出しにそのまま出る。座標も引けないので、
# 距離も狂う。文字化けと同じで、直せば効きがはっきり出る。
#
# ここに並べたのは、**いまの値が市区町村として実在せず、直し先は実在する**と
# 機械で確かめたものだけ。どちらに直すか迷うものは入れていない。
# Place は見ない。その Area を持つ作品はすべて同じ誤りなので、まとめて直せる。
#                                                          （2026-10-10）
_AREA_FIX = {
    # ── 県の取り違え ──
    '福岡県喜多方市': '福島県喜多方市',      # 喜多方市は福島県。9通り・17件が同じ誤り
    '岐阜県米原市': '滋賀県米原市',          # 米原市は滋賀県（醒井渓谷）
    '栃木県古河市': '茨城県古河市',          # 古河市は茨城県
    '高知県内子町': '愛媛県内子町',          # 内子町は愛媛県
    '秋田県八幡平市': '岩手県八幡平市',      # 八幡平市は岩手県
    '栃木県小谷村': '長野県小谷村',          # 小谷村は長野県（鎌池）
    # 室堂は立山にある。一覧の「東京都立川市」案は誤り。
    # 富山県のつもりで市区町村名だけ間違えたものなので、県は動かさない。
    '富山県立川市': '富山県立山町',
    # ── 市区町村名の誤記 ──
    '静岡県伊豆天城市': '静岡県伊豆市',      # 伊豆天城市は無い。旧天城湯ヶ島町は伊豆市
    '群馬県板倉市': '群馬県板倉町',          # 板倉は町
    '北海道中富野良町': '北海道中富良野町',  # 「野良」が逆
    '三重県松坂市': '三重県松阪市',          # 「坂」ではなく「阪」
    '神奈川県南足利市': '神奈川県南足柄市',  # 夕日の滝は南足柄市
}


@app.route("/api/_fix/area", methods=["GET", "POST"])
def api_fix_area():
    """Master_Photos の Area を、実在する市区町村名に書き戻す。
    GET は何件当てはまるかを数えるだけ。POST で実際に書き換える。
    元の値は FixedFrom に残すので、あとから何を変えたか辿れる。"""
    if not _check_key_ok():
        abort(404)
    if not db:
        return jsonify({"ok": False, "error": "Firestoreに繋がっていません"}), 500
    apply = (request.method == "POST")
    found, done, rows = 0, 0, []
    hit = Counter()
    try:
        batch, n = db.batch(), 0
        for doc in db.collection('Master_Photos').stream():
            d = doc.to_dict() or {}
            old = d.get('Area', '')
            new = _AREA_FIX.get(old)
            if not new:
                continue
            found += 1
            hit[old] += 1
            place = d.get('Place', '') or ''
            if len(rows) < 60:
                rows.append('%s｜%s　→　%s' % (old, place[:14], new))
            if not apply:
                continue
            batch.set(doc.reference, {'Area': new,
                                      'FixedFrom': '%s｜%s' % (old, place)}, merge=True)
            # 誤った名前で集めた座標は用済み。消しておけば「集める」で入り直す。
            try:
                db.collection(_PLACEGEO_COL).document(placegeo_id(old, place)).delete()
            except Exception:
                pass
            done += 1
            n += 1
            if n >= 300:
                batch.commit()
                batch, n = db.batch(), 0
        if apply and n:
            batch.commit()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    if apply and done:
        # 作品データを読み直させる。索引も作り直す。
        global _PHOTOS, _PHOTOS_AT, _PEAK_INDEX, _PEAK_INDEX_AT, _PLACE_PAIRS, _PLACE_PAIRS_AT
        _PHOTOS, _PHOTOS_AT = None, 0.0
        _PEAK_INDEX, _PEAK_INDEX_AT = None, 0.0
        _PLACE_PAIRS, _PLACE_PAIRS_AT = None, 0.0
        try:
            for ref in db.collection(_SNAP_COLL).list_documents():
                ref.delete()
        except Exception as e:
            print('[WARN] 索引の消去に失敗: %s' % e, flush=True)

    return jsonify({"ok": True, "table": len(_AREA_FIX), "found": found,
                    "fixed": done, "applied": apply,
                    "by_area": dict(hit), "rows": rows})


@app.route("/api/_geocode/places/rejudge", methods=["POST"])
def api_geocode_places_rejudge():
    """すでに集めてある座標を、地図に問い合わせ直さずに判定だけやり直す。
    判定の決まりを変えたときに使う。問い合わせないので費用も時間もかからない。"""
    if not _check_key_ok():
        abort(404)
    if not db:
        return jsonify({"ok": False, "error": "Firestoreに繋がっていません"}), 500
    body = request.get_json(silent=True) or {}
    after = str(body.get('after') or '')
    col = db.collection(_PLACEGEO_COL)
    q = col.order_by('__name__').limit(300)
    if after:
        snap = col.document(after).get()
        if snap.exists:
            q = q.start_after(snap)
    docs = list(q.stream())
    batch = db.batch()
    changed, last = 0, ''
    tally = {'ok': 0, 'check': 0, 'ng': 0}
    moved = []
    for doc in docs:
        last = doc.id
        d = doc.to_dict() or {}
        got = None
        if d.get('lat') is not None and d.get('lng') is not None:
            got = {'lat': d['lat'], 'lng': d['lng'], 'type': d.get('type', ''),
                   'partial': d.get('partial'), 'pref': d.get('got_pref', ''),
                   'formatted': d.get('formatted', '')}
        status, reason, km = judge_place_geo(d.get('area', ''), d.get('pref', ''), got)
        tally[status] = tally.get(status, 0) + 1
        if status != d.get('status') or reason != d.get('reason'):
            batch.set(doc.reference, {'status': status, 'reason': reason}, merge=True)
            changed += 1
            if d.get('status') != status and len(moved) < 20:
                moved.append('%s｜%s　%s→%s' % (d.get('area', ''), d.get('place', ''),
                                               d.get('status', ''), status))
    if changed:
        try:
            batch.commit()
        except Exception as e:
            return jsonify({"ok": False, "error": "書き込みに失敗しました：%s" % e}), 500
    global _PLACEGEO, _PLACEGEO_AT
    _PLACEGEO, _PLACEGEO_AT = None, 0.0
    return jsonify({"ok": True, "seen": len(docs), "changed": changed,
                    "tally": tally, "moved": moved,
                    "after": last, "done": len(docs) < 300})

@app.route("/api/_geocode/places/reset-bad", methods=["POST"])
def api_geocode_places_reset_bad():
    """取り直したほうがよいものだけを消す。消したぶんは「集める」で入り直す。
      ・見つからなかったもの（元データの文字化けなどを直したあと）
      ・区切り記号でつないだ地名で、大まかな位置しか返っていないもの"""
    if not _check_key_ok():
        abort(404)
    if not db:
        return jsonify({"ok": False, "error": "Firestoreに繋がっていません"}), 500
    deleted, kinds = 0, {'見つからなかった': 0, '区切り記号つき': 0}
    try:
        batch, n = db.batch(), 0
        for doc in db.collection(_PLACEGEO_COL).stream():
            d = doc.to_dict() or {}
            why = ''
            if d.get('status') == 'ng' and str(d.get('reason', '')).startswith('見つかりません'):
                why = '見つからなかった'
            elif _PLACE_SEP.search(str(d.get('place', ''))) and d.get('type') == 'APPROXIMATE':
                why = '区切り記号つき'
            if not why:
                continue
            kinds[why] += 1
            batch.delete(doc.reference)
            deleted += 1
            n += 1
            if n >= 400:
                batch.commit()
                batch, n = db.batch(), 0
        if n:
            batch.commit()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    global _PLACEGEO, _PLACEGEO_AT
    _PLACEGEO, _PLACEGEO_AT = None, 0.0
    return jsonify({"ok": True, "deleted": deleted, "kinds": kinds})

@app.route("/api/_geocode/places/export", methods=["GET"])
def api_geocode_places_export():
    """集めた座標を一覧で書き出す。Excelで開いて目で確かめるため。"""
    if not _check_key_ok():
        abort(404)
    if not db:
        abort(500)
    import csv as _csv
    from io import StringIO
    buf = StringIO()
    w = _csv.writer(buf)
    w.writerow(['Area', 'Place', '作品数', '判定', '理由', '緯度', '経度',
                '市区町村中心からkm', '精度', '部分一致', '返ってきた県', '地図の住所'])
    rows = []
    try:
        for doc in db.collection(_PLACEGEO_COL).stream():
            d = doc.to_dict() or {}
            rows.append(d)
    except Exception as e:
        abort(500)
    order = {'ng': 0, 'check': 1, 'ok': 2}
    rows.sort(key=lambda d: (order.get(d.get('status', ''), 9), -(d.get('works') or 0)))
    for d in rows:
        w.writerow([d.get('area', ''), d.get('place', ''), d.get('works', ''),
                    d.get('status', ''), d.get('reason', ''),
                    d.get('lat', ''), d.get('lng', ''), d.get('km_from_city', ''),
                    d.get('type', ''), 'はい' if d.get('partial') else '',
                    d.get('got_pref', ''), d.get('formatted', '')])
    resp = make_response('﻿' + buf.getvalue())      # Excelで開けるようBOMを付ける
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = 'attachment; filename="place_geo.csv"'
    return resp

@app.route("/api/_geocode/places/clear", methods=["POST"])
def api_geocode_places_clear():
    """集めた座標をすべて消す。取り直したいときだけ使う。"""
    if not _check_key_ok():
        abort(404)
    if not db:
        return jsonify({"ok": False, "error": "Firestoreに繋がっていません"}), 500
    deleted = 0
    try:
        while True:
            docs = list(db.collection(_PLACEGEO_COL).limit(400).stream())
            if not docs:
                break
            b = db.batch()
            for doc in docs:
                b.delete(doc.reference)
            b.commit()
            deleted += len(docs)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    global _PLACEGEO, _PLACEGEO_AT
    _PLACEGEO, _PLACEGEO_AT = None, 0.0
    return jsonify({"ok": True, "deleted": deleted})

_GEOCODE_PLACES_PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>撮影地の座標を集める</title>
<style>
 body{font-family:system-ui,-apple-system,"Hiragino Kaku Gothic ProN",sans-serif;
      margin:0;padding:24px 16px;background:#faf9f7;color:#1c1917;line-height:1.7}
 .wrap{max-width:760px;margin:0 auto}
 h1{font-size:22px;margin:0 0 12px}
 p{margin:0 0 12px;font-size:15px}
 label{display:block;font-weight:700;font-size:14px;margin:18px 0 6px}
 input[type=password]{width:100%;box-sizing:border-box;padding:12px;font-size:15px;
      border:1px solid #d6d3d1;border-radius:8px}
 .btns{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}
 button{padding:12px 20px;font-size:15px;font-weight:700;border-radius:8px;
      border:1px solid #d6d3d1;background:#fff;cursor:pointer}
 button.go{background:#064e3b;border-color:#064e3b;color:#fff}
 button:disabled{opacity:.45;cursor:not-allowed}
 #msg{display:none;padding:14px;border-radius:8px;background:#ecfdf5;
      white-space:pre-wrap;font-size:15px}
 #msg.ng{background:#fef2f2}
 #bar{display:none;height:10px;border-radius:5px;background:#e7e5e4;margin:14px 0;overflow:hidden}
 #bar > i{display:block;height:100%;width:0;background:#059669;transition:width .3s}
 #log{display:none;margin-top:14px;padding:12px;background:#fff;border:1px solid #e7e5e4;
      border-radius:8px;font-size:13px;max-height:320px;overflow:auto;white-space:pre-wrap;
      font-family:ui-monospace,monospace}
 .note{color:#78716c;font-size:13px}
 a{color:#065f46}
</style></head><body><div class="wrap">
<h1>撮影地の座標を集める</h1>
<p>作品データの Area と Place をつないだ文字列を地図に問い合わせ、撮影地ごとの座標を集めます。
これまでは市区町村の座標しか無く、たとえば「前橋市｜覚満淵」は前橋市役所の位置になっていました。
<b>一度集めれば以後は読むだけです。</b>
途中で閉じても、次に開いて押せば続きから進みます。同じ撮影地を二度問い合わせることはありません。</p>

<label for="key">CHECK_KEY</label>
<input id="key" type="password" autocomplete="off" placeholder="Renderの環境変数に入れた値">

<div class="btns">
  <button id="count">いま何件あるか見る</button>
  <button id="run" class="go">集める</button>
  <button id="stop" disabled>止める</button>
  <button id="csv">一覧を書き出す</button>
</div>
<div class="btns">
  <button id="rejudge">判定し直す</button>
  <button id="resetbad">取り直しが要るものを消す</button>
  <button id="moji">文字化けを直す</button>
  <button id="areafix">市区町村名を直す</button>
</div>

<div id="bar"><i></i></div>
<div id="msg"></div>
<div id="log"></div>

<p class="note" style="margin-top:20px">判定の意味。
<b>ok</b>＝そのまま使います。
<b>check</b>＝使いますが、目で確かめたほうがよいもの（市区町村の中心と同じ場所が返ってきた＝地名が見つかっていない可能性）。
<b>ng</b>＝使いません（見つからなかった、別の県が30km以上離れて返ってきた、市区町村の中心から60km以上離れていた）。市区町村の座標のままになります。</p>
<p class="note"><b>判定し直す</b>＝集めた座標はそのままに、判定の決まりだけを当て直します。地図には問い合わせません。
<b>取り直しが要るものを消す</b>＝見つからなかったものと、区切り記号でつないだ地名で大まかな位置しか返っていないものを消します。そのあと「集める」を押すと、入り直します。</p>
<p class="note">出典：地図データ © Google</p>
</div>
<script>
var $ = function (s) { return document.querySelector(s); };
function key() { return $("#key").value.trim(); }
function say(t, ng) { var m = $("#msg"); m.style.display = "block"; m.className = ng ? "ng" : ""; m.textContent = t; }
function log(t) { var o = $("#log"); o.style.display = "block"; o.textContent += t + "\\n"; o.scrollTop = o.scrollHeight; }
function bar(p) { $("#bar").style.display = "block"; $("#bar > i").style.width = Math.max(0, Math.min(100, p)) + "%"; }

var stopped = false;

function post(path, body) {
  return fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Check-Key": key() },
    body: JSON.stringify(body || {})
  }).then(function (r) {
    if (r.status === 404) { throw new Error("CHECK_KEY が違うか、Render の環境変数に設定されていません"); }
    return r.json();
  });
}

function showCount() {
  if (!key()) { say("CHECK_KEY を入れてください", true); return; }
  fetch("/api/_geocode/places/count", { headers: { "X-Check-Key": key() } })
    .then(function (r) {
      if (r.status === 404) { throw new Error("CHECK_KEY が違うか、設定されていません"); }
      return r.json();
    })
    .then(function (j) {
      if (!j.ok) { throw new Error(j.error || "数えられませんでした"); }
      var t = j.tally || {};
      say("撮影地 " + j.pairs + "か所のうち、" + j.done + "か所ぶんの座標があります。\\n"
        + "ok " + (t.ok || 0) + "／check " + (t.check || 0) + "／ng " + (t.ng || 0));
      bar(j.pairs ? j.done / j.pairs * 100 : 0);
    })
    .catch(function (e) { say(e.message, true); });
}

/* 1回の呼び出しを短く保ち、続きは next から。
   途中で閉じても、すでに書けたぶんは残る。 */
function run() {
  if (!key()) { say("CHECK_KEY を入れてください", true); return; }
  stopped = false;
  $("#run").disabled = true; $("#count").disabled = true; $("#csv").disabled = true;
  $("#stop").disabled = false;
  $("#log").textContent = "";
  log("集め始めます");

  var asked = 0, saved = 0, total = 0;
  var sum = { ok: 0, check: 0, ng: 0 };

  function step(offset) {
    if (stopped) { return Promise.resolve({ stopped: true, next: offset }); }
    return post("/api/_geocode/places/run", { offset: offset, limit: 15 }).then(function (j) {
      if (!j.ok) { throw new Error(j.error || "失敗しました"); }
      total = j.total;
      asked += j.asked || 0; saved += j.saved || 0;
      var t = j.tally || {};
      sum.ok += t.ok || 0; sum.check += t.check || 0; sum.ng += t.ng || 0;
      (j.rows || []).forEach(function (r) {
        if (r.status !== "ok") {
          log("　" + r.status + "　" + r.area + "｜" + r.place
            + (r.reason ? "　" + r.reason : ""));
        }
      });
      bar(total ? j.next / total * 100 : 0);
      say("集めています… " + j.next + " / " + total + "か所まで進みました\\n"
        + "このひと続きで問い合わせたのは " + asked + "か所"
        + "（ok " + sum.ok + "／check " + sum.check + "／ng " + sum.ng + "）");
      if (j.error) { throw new Error(j.error); }
      if (j.next >= total) { return { done: true, next: j.next }; }
      return step(j.next);
    });
  }

  step(0).then(function (r) {
    if (r && r.stopped) {
      say("止めました。" + r.next + "か所まで進んでいます。\\nもう一度「集める」を押すと続きから進みます。");
    } else {
      say("集め終わりました。\\n問い合わせ " + asked + "か所"
        + "（ok " + sum.ok + "／check " + sum.check + "／ng " + sum.ng + "）\\n"
        + "「一覧を書き出す」で中身を確かめられます。");
    }
  }).catch(function (e) {
    say(e.message + "\\n（ここまでに書けたぶんは残っています。もう一度押せば続きから進みます）", true);
  }).then(function () {
    $("#run").disabled = false; $("#count").disabled = false; $("#csv").disabled = false;
    $("#stop").disabled = true;
  });
}

/* 集めた座標はそのままに、判定だけ当て直す。地図には問い合わせない。 */
function rejudge() {
  if (!key()) { say("CHECK_KEY を入れてください", true); return; }
  $("#rejudge").disabled = true; $("#run").disabled = true;
  $("#log").textContent = "";
  log("判定し直します（地図には問い合わせません）");
  var seen = 0, changed = 0, sum = { ok: 0, check: 0, ng: 0 };
  function step(after) {
    return post("/api/_geocode/places/rejudge", { after: after }).then(function (j) {
      if (!j.ok) { throw new Error(j.error || "失敗しました"); }
      seen += j.seen || 0; changed += j.changed || 0;
      var t = j.tally || {};
      sum.ok += t.ok || 0; sum.check += t.check || 0; sum.ng += t.ng || 0;
      (j.moved || []).forEach(function (m) { log("　" + m); });
      say("判定し直しています… " + seen + "か所");
      if (j.done) { return; }
      return step(j.after);
    });
  }
  step("").then(function () {
    say("判定し直しました。\\n見た数 " + seen + "／変わった数 " + changed + "\\n"
      + "ok " + sum.ok + "／check " + sum.check + "／ng " + sum.ng);
  }).catch(function (e) {
    say(e.message, true);
  }).then(function () {
    $("#rejudge").disabled = false; $("#run").disabled = false;
  });
}

function resetBad() {
  if (!key()) { say("CHECK_KEY を入れてください", true); return; }
  if (!confirm("取り直しが要るものを消します。消したぶんは「集める」で入り直します。よろしいですか？")) { return; }
  $("#resetbad").disabled = true;
  post("/api/_geocode/places/reset-bad", {}).then(function (j) {
    if (!j.ok) { throw new Error(j.error || "失敗しました"); }
    var k = j.kinds || {};
    say((j.deleted || 0) + "か所を消しました。\\n"
      + "　見つからなかったもの " + (k["見つからなかった"] || 0) + "／"
      + "区切り記号つき " + (k["区切り記号つき"] || 0) + "\\n"
      + "「集める」を押すと、この分だけ入り直します。");
  }).catch(function (e) {
    say(e.message, true);
  }).then(function () { $("#resetbad").disabled = false; });
}

$("#run").addEventListener("click", run);
$("#count").addEventListener("click", showCount);

/* 作品データの文字化けを直す。壊れている (Area, Place) が対応表に載っているものだけ書き換える。 */
function fixMoji() {
  if (!key()) { say("CHECK_KEY を入れてください", true); return; }
  $("#moji").disabled = true;
  $("#log").textContent = "";
  fetch("/api/_fix/mojibake", { headers: { "X-Check-Key": key() } })
    .then(function (r) { if (r.status === 404) { throw new Error("CHECK_KEY が違います"); } return r.json(); })
    .then(function (j) {
      if (!j.ok) { throw new Error(j.error || "数えられませんでした"); }
      (j.rows || []).forEach(function (s) { log("　" + s); });
      if (!j.found) { say("直す行はありませんでした（対応表 " + j.table + "件）。"); return null; }
      if (!confirm("作品データ " + j.found + "件の地名を直します。元の値は FixedFrom に残します。よろしいですか？")) { return null; }
      say("直しています…");
      return post("/api/_fix/mojibake", {}).then(function (k) {
        if (!k.ok) { throw new Error(k.error || "書き換えに失敗しました"); }
        say(k.fixed + "件を直しました。\\n続けて「集める」を押すと、直した地名で座標を取り直します。");
      });
    })
    .catch(function (e) { say(e.message, true); })
    .then(function () { $("#moji").disabled = false; });
}

/* 実在しない市区町村名（福岡県喜多方市、三重県松坂市 など）を直す。
   対応表に載っている Area を持つ作品だけを書き換える。 */
function fixArea() {
  if (!key()) { say("CHECK_KEY を入れてください", true); return; }
  $("#areafix").disabled = true;
  $("#log").textContent = "";
  fetch("/api/_fix/area", { headers: { "X-Check-Key": key() } })
    .then(function (r) { if (r.status === 404) { throw new Error("CHECK_KEY が違います"); } return r.json(); })
    .then(function (j) {
      if (!j.ok) { throw new Error(j.error || "数えられませんでした"); }
      (j.rows || []).forEach(function (s) { log("　" + s); });
      if (!j.found) { say("直す行はありませんでした（対応表 " + j.table + "件）。"); return null; }
      if (!confirm("作品データ " + j.found + "件の市区町村名を直します。元の値は FixedFrom に残します。よろしいですか？")) { return null; }
      say("直しています…");
      return post("/api/_fix/area", {}).then(function (k) {
        if (!k.ok) { throw new Error(k.error || "書き換えに失敗しました"); }
        say(k.fixed + "件を直しました。\\n続けて「集める」を押すと、直した地名で座標を取り直します。");
      });
    })
    .catch(function (e) { say(e.message, true); })
    .then(function () { $("#areafix").disabled = false; });
}

$("#moji").addEventListener("click", fixMoji);
$("#areafix").addEventListener("click", fixArea);
$("#rejudge").addEventListener("click", rejudge);
$("#resetbad").addEventListener("click", resetBad);
$("#stop").addEventListener("click", function () { stopped = true; $("#stop").disabled = true; });
$("#csv").addEventListener("click", function () {
  if (!key()) { say("CHECK_KEY を入れてください", true); return; }
  fetch("/api/_geocode/places/export", { headers: { "X-Check-Key": key() } })
    .then(function (r) {
      if (r.status === 404) { throw new Error("CHECK_KEY が違うか、設定されていません"); }
      return r.blob();
    })
    .then(function (b) {
      var u = URL.createObjectURL(b);
      var a = document.createElement("a");
      a.href = u; a.download = "place_geo.csv"; a.click();
      setTimeout(function () { URL.revokeObjectURL(u); }, 5000);
    })
    .catch(function (e) { say(e.message, true); });
});
try { var s = sessionStorage.getItem("rmkey"); if (s) { $("#key").value = s; } } catch (e) {}
$("#key").addEventListener("change", function () {
  try { sessionStorage.setItem("rmkey", key()); } catch (e) {}
});
</script></body></html>
"""

@app.route("/_geocode-places", methods=["GET"])
def page_geocode_places():
    """ブラウザで開く、撮影地の座標を集める画面。"""
    if not os.environ.get("CHECK_KEY", ""):
        abort(404)
    resp = make_response(_GEOCODE_PLACES_PAGE)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


# ──────────────── ルート沿いの道の駅 ────────────────
# 「どこに道の駅があるか」ではなく「行き帰りの道すがら、どこに寄れるか」を返す。
# 立ち寄り地を決めるとき、名前を知らないと探せないのが不便だったため。
#
# 受け取るのは Google ルート API が返す符号化された経路（encodedPolyline）。
# それを座標の列に戻し、一定間隔で間引いた点から各道の駅までの距離を測る。
# 経路のどのあたりかも返すので、出発地に近い順に並べられる。

def decode_polyline(encoded):
    """Google の符号化された経路を、(緯度, 経度) の列に戻す。
    方式は Encoded Polyline Algorithm Format。外部のライブラリは使わない。"""
    points = []
    index = lat = lng = 0
    length = len(encoded)
    while index < length:
        for is_lat in (True, False):
            shift = result = 0
            while True:
                if index >= length:
                    return points
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1f) << shift
                shift += 5
                if b < 0x20:
                    break
            d = ~(result >> 1) if (result & 1) else (result >> 1)
            if is_lat:
                lat += d
            else:
                lng += d
        points.append((lat * 1e-5, lng * 1e-5))
    return points


def thin_path(points, step_km=2.0):
    """経路の点を間引く。曲がり角ごとの細かい点をすべて使うと計算が増えるだけで、
    道の駅が近いかどうかの判定は粗い間隔で足りる。
    進んだ距離も一緒に返すので、出発地からどのあたりかが分かる。"""
    if not points:
        return []
    out = [(points[0][0], points[0][1], 0.0)]
    acc = 0.0           # 経路に沿って進んだ距離
    since = 0.0         # 最後に点を採ってから進んだ距離
    for i in range(1, len(points)):
        d = haversine(points[i - 1][0], points[i - 1][1], points[i][0], points[i][1])
        acc += d
        since += d
        if since >= step_km:
            out.append((points[i][0], points[i][1], acc))
            since = 0.0
    last = points[-1]
    if out[-1][0] != last[0] or out[-1][1] != last[1]:
        out.append((last[0], last[1], acc))
    return out


@app.route("/api/michinoeki/route", methods=["POST", "OPTIONS"])
def api_michinoeki_route():
    """経路沿いの道の駅を、出発地に近い順に返す。
    撮影ノート（リファレンス側 /planner）から呼ばれるのでCORSを許可する。

    本文（JSON）
      polyline   Google ルート API の encodedPolyline（必須）
      radius     経路から何km以内を拾うか（既定5、上限30）
      limit      最大何件返すか（既定12、上限40）
    """
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = "https://reference.fukei-shashin.co.jp"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Max-Age"] = "86400"
        return resp

    body = request.get_json(silent=True) or {}
    encoded = body.get("polyline") or ""
    if not isinstance(encoded, str) or len(encoded) < 10:
        return jsonify({"error": "polyline required"}), 400
    if len(encoded) > 200000:
        return jsonify({"error": "polyline too long"}), 400
    try:
        radius = float(body.get("radius", 5))
    except (TypeError, ValueError):
        radius = 5.0
    radius = max(0.5, min(30.0, radius))
    try:
        limit = int(body.get("limit", 12))
    except (TypeError, ValueError):
        limit = 12
    limit = max(1, min(40, limit))

    try:
        path = thin_path(decode_polyline(encoded))
    except Exception:
        return jsonify({"error": "polyline decode failed"}), 400
    if len(path) < 2:
        return jsonify({"error": "polyline too short"}), 400

    # 経路から大きく離れた道の駅は、距離を測る前に外す。
    # 全国の道の駅すべてに対して経路の全点を測ると無駄が多いため、
    # まず経路を囲む四角から外れるものを落とす。
    lats = [p[0] for p in path]
    lngs = [p[1] for p in path]
    pad = radius / 111.0 + 0.05
    lat_lo, lat_hi = min(lats) - pad, max(lats) + pad
    lng_lo, lng_hi = min(lngs) - pad / 0.8, max(lngs) + pad / 0.8

    def gather(places, group):
        """経路の近くにあるものを拾う。道の駅もSA・PAも同じ測り方でよい。
        あとで上下線を選り分けるため、いちばん近かった経路上の位置も控えておく。"""
        out = []
        for e in places:
            if not (lat_lo <= e['lat'] <= lat_hi and lng_lo <= e['lng'] <= lng_hi):
                continue
            best_d, best_i = None, 0
            for i, (plat, plng, _along) in enumerate(path):
                d = haversine(plat, plng, e['lat'], e['lng'])
                if best_d is None or d < best_d:
                    best_d, best_i = d, i
                    if d < 0.3:    # 経路上とみなせるほど近い。これ以上測る必要はない
                        break
            if best_d is not None and best_d <= radius:
                out.append({"along": path[best_i][2], "dist": best_d, "e": e,
                            "group": group, "idx": best_i})
        return out

    found = gather(get_michinoeki(), "michinoeki") + gather(get_sapa(), "sapa")

    # ── 上下線の選り分け ──
    # SA・PAは上り線と下り線に別々にあることが多い。両方を並べて見せると、
    # 走っている側ではないほうを待ち合わせ場所に選んでしまい、行程が壊れる。
    #
    # 日本は左側通行なので、走りながら入れるのは進行方向の左側にある施設。
    # 同じ施設が左右の両方にあるときだけ、左側のものを残す。
    # 片側にしか無いときは判断材料が無いので残し、上り／下りの別を添えて
    # 利用者に委ねる（経路から離れた一般道沿いの施設もここに入る）。
    by_base = {}
    for f in found:
        e = f["e"]
        if f["group"] != "sapa":
            continue
        f["sideLR"] = side_of_route(path, f["idx"], e['lat'], e['lng'])
        by_base.setdefault((e.get('base', e['name']), e.get('kind', '')), []).append(f)

    def keep_only(group, keeper):
        """groupのうちkeeperだけを残し、ほかは落とす。"""
        for g in group:
            if g is not keeper:
                drop.add(id(g))

    drop = set()
    for _key, group in by_base.items():
        group.sort(key=lambda g: g["dist"])

        # まず、集約型として知られている施設かどうかを見る。
        # OpenStreetMap の登録のしかたに関わらず、これが分かっていれば
        # 反対車線の心配は要らない。
        base = group[0]["e"].get('base', '')
        if base in COMBINED_SAPA_BASES or group[0]["e"].get('name', '') in COMBINED_SAPA_BASES:
            group[0]["side"] = "both_listed"
            group[0]["combined"] = True
            keep_only(group, group[0])
            continue

        if len(group) >= 2:
            dirs = {g["e"].get('direction') for g in group if g["e"].get('direction')}
            if dirs == {"上り", "下り"}:
                # 上りと下りの両方が登録されている。
                # 日本は左側通行なので、走りながら入れるのは進行方向の左にあるほう。
                # 左右に分かれているなら、それで確実に選り分けられる。
                #
                # 近さでは決められない。上下線が別々の施設でも、道をはさんで
                # 向かい合っているので百数十メートルしか離れていない。
                # 以前は400m以内なら集約型とみなしていたが、それだと
                # 佐野SA・羽生PA・大谷PAなど、ごく普通の上下別施設まで
                # 「どちら向きからでも入れます」と出てしまっていた。
                # 反対車線の施設を待ち合わせ場所に選ばせかねないので改めた。
                # （2026-10-04）
                spread = max(
                    haversine(a["e"]['lat'], a["e"]['lng'], b["e"]['lat'], b["e"]['lng'])
                    for a in group for b in group
                )
                if spread <= 0.06:
                    # 60m以内。道をはさんで向かい合う上下別施設では、
                    # 車線の幅と建物の奥行きだけで百数十メートルは離れる。
                    # これだけ近いのは同じ建物＝上下線集約型。
                    # 宝塚北SA・浜名湖SAなど、どちらから来ても同じ施設に入れる。
                    group[0]["side"] = "both"
                    group[0]["combined"] = True    # 上り／下りは言わない。どちらでも入れる
                    keep_only(group, group[0])
                    continue
                lefts = [g for g in group if g.get("sideLR") == "L"]
                rights = [g for g in group if g.get("sideLR") == "R"]
                if lefts and rights:
                    lefts[0]["side"] = "same"
                    keep_only(group, lefts[0])
                    continue
                # 離れているのに左右を分けられない。経路が施設からかなり遠いときに
                # こうなる（遠くから見れば上り線も下り線も同じ方角にある）。
                # ここで片方を選ぶと反対車線を案内しかねないので、分からないと伝える。
                group[0]["side"] = ""
                group[0]["ambiguous"] = True       # 上り／下りも伏せる
                keep_only(group, group[0])
                continue

            sides = {g.get("sideLR") for g in group if g.get("sideLR")}
            if len(sides) >= 2:
                # 左右に分かれている＝上下線が別の施設。走っている側だけ残す。
                lefts = [g for g in group if g.get("sideLR") == "L"]
                if lefts:
                    lefts[0]["side"] = "same"
                    keep_only(group, lefts[0])
                    continue
                keep_only(group, group[0])
                group = group[:1]
            else:
                # それ以外は表記ゆれの重複（「佐野SA (下り)」と「佐野サービスエリア」など）。
                # 上下の別が付いているほうを残す。そのほうが走っている側を判断できる。
                group.sort(key=lambda g: (0 if g["e"].get('direction') else 1, g["dist"]))
                keep_only(group, group[0])
                group = group[:1]

        # 1件だけ。上り／下りの別が付いているなら、走っている側かどうかは判断できる。
        g = group[0]
        if g["e"].get('direction'):
            g["side"] = "same" if g.get("sideLR") == "L" else "opposite"

    found = [f for f in found if id(f) not in drop]
    found.sort(key=lambda f: f["along"])      # 出発地に近い順

    stations = []
    for f in found[:limit]:
        e = f["e"]
        stations.append({
            "name": e['name'], "pref": e['pref'], "city": e['city'],
            "lat": e['lat'], "lng": e['lng'], "site": e.get('site', ''),
            # 道の駅は「道の駅」、SA・PAは「SA」か「PA」。画面で見分けるために返す。
            "kind": "道の駅" if f["group"] == "michinoeki" else e.get('kind', 'SA'),
            # 上り／下り。集約型はどちらからでも入れるので、あえて言わない。
            "direction": "" if (f.get("combined") or f.get("ambiguous")) else e.get('direction', ''),
            "side": f.get("side", ""),               # same＝進行方向側と判断できたもの
            "off_route_km": round(f["dist"], 1),     # 経路からの隔たり
            "along_km": round(f["along"], 1),        # 出発地から経路に沿って進んだ距離
        })

    resp = jsonify({
        "stations": stations,
        "total_near_route": len(found),
        "route_km": round(path[-1][2], 1),
        "radius_km": radius,
        "notice": "施設により営業時間や利用のルールが異なります。"
                  "ご利用の際は事前に各施設のWEBサイトなどでご確認ください。",
        "source": "出典：道の駅＝国土交通省ウェブサイト「道の駅」一覧、Wikidata／"
                  "SA・PA＝© OpenStreetMap contributors",
    })
    resp.headers["Access-Control-Allow-Origin"] = "https://reference.fukei-shashin.co.jp"
    return resp


@app.route("/api/peak-subjects", methods=["GET", "OPTIONS"])
def api_peak_subjects():
    """撮り頃の被写体を返す。風景撮ろうよ！（/enjoy）から呼ばれる。
    別ドメイン（reference.fukei-shashin.co.jp）からの呼び出しなのでCORSを許可する。"""
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = "https://reference.fukei-shashin.co.jp"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Max-Age"] = "86400"
        return resp

    try:
        lat = float(request.args.get("lat", ""))
        lng = float(request.args.get("lng", ""))
    except ValueError:
        return jsonify({"error": "lat/lng required"}), 400

    try:
        radius = int(request.args.get("radius", "150"))
    except ValueError:
        radius = 150
    radius = max(10, min(500, radius))

    base = None
    ds = request.args.get("date", "")
    if ds:
        try:
            y, m, d = [int(x) for x in ds.split("-")]
            base = date(y, m, d)
        except Exception:
            base = None

    try:
        rows = subjects_in_peak_near((lat, lng), radius, base_date=base)
    except Exception:
        import traceback
        print(f"[ERROR] api_peak_subjects: {traceback.format_exc()}", flush=True)
        rows = []

    subjects = [
        {"subject": r[0], "peak": r[1], "count": r[2]}
        for r in rows[:12]
    ]

    resp = jsonify({"subjects": subjects})
    resp.headers["Access-Control-Allow-Origin"] = "https://reference.fukei-shashin.co.jp"
    return resp



def _cors(resp):
    """リファレンス側（別ドメイン）から呼ばれる返事に、許可の印をつける。"""
    resp.headers["Access-Control-Allow-Origin"] = "https://reference.fukei-shashin.co.jp"
    return resp


def _hhmm_to_min(s, default):
    """『5:30』や『530』『5』を、0時からの分にする。読めなければ default。"""
    t = str(s or '').strip()
    if not t:
        return default
    m = re.match(r'^(\d{1,2})\s*[:：]\s*(\d{1,2})$', t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
    elif t.isdigit() and len(t) in (3, 4):
        h, mi = int(t[:-2]), int(t[-2:])
    elif t.isdigit():
        h, mi = int(t), 0
    else:
        return default
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return default
    return h * 60 + mi


@app.route("/api/plan", methods=["GET", "OPTIONS"])
def api_plan():
    """撮影計画を方角ちがいで最大3案返す。プランナー(リファレンス)から呼ばれる。"""
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = "https://reference.fukei-shashin.co.jp"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Max-Age"] = "86400"
        return resp

    try:
        lat = float(request.args.get("lat", ""))
        lng = float(request.args.get("lng", ""))
    except ValueError:
        return jsonify({"error": "lat/lng required"}), 400

    base = date.today()
    ds = request.args.get("date", "")
    if ds:
        try:
            y, m, d = [int(x) for x in ds.split("-")]
            base = date(y, m, d)
        except Exception:
            pass

    leave = _hhmm_to_min(request.args.get("leave"), 5 * 60)
    back = _hhmm_to_min(request.args.get("return"), 20 * 60)
    if back <= leave:
        back = leave + 60                      # 逆転していたら最低1時間は確保する

    subject = (request.args.get("subject") or "").strip() or None
    if subject and subject not in KEYWORD_NORMALIZE:
        subject = None                         # 知らない被写体なら指定なし扱い

    must = None
    try:
        must = (float(request.args.get("must_lat")), float(request.args.get("must_lng")))
    except (TypeError, ValueError):
        must = None
    easy = request.args.get("easy", "") in ("1", "true", "yes")
    stay_over = request.args.get("stay_over", "") in ("1", "true", "yes")

    try:
        out = build_plans((lat, lng), request.args.get("origin_name") or None,
                          base, leave, back, subject=subject,
                          must_latlng=must,
                          must_name=(request.args.get("must_name") or "").strip() or None,
                          easy=easy, stay_over=stay_over)
    except Exception:
        import traceback
        print(f"[ERROR] api_plan: {traceback.format_exc()}", flush=True)
        out = {"plans": [], "error": "計画を組み立てられませんでした"}

    resp = jsonify(out)
    resp.headers["Access-Control-Allow-Origin"] = "https://reference.fukei-shashin.co.jp"
    return resp



# ──────────────── 実際の所要時間で組み直す ────────────────
# 行程を組むときの移動時間は見込み（直線距離の1.3倍を時速45km）である。
# 山道と高速道路が同じ速さで計算されるので、実際とは開く。
#
# 「この案で行く」と決まった1案だけ、地図の経路案内で実測した所要時間を
# もらって組み直す。呼ぶたびに料金がかかるので、押されたときだけ行う。
#
# 休憩もここで足す。見込みの段階では入れていなかったので、
# 長い移動のある案ほど、実際には帰りが遅くなっていた。（2026-10-10）

_BREAK_PER_MIN = 120   # これだけ続けて走ったら
_BREAK_MIN = 15        # これだけ休む


def break_for(drive_min):
    """その区間に足す休憩（分）。2時間ごとに15分。"""
    try:
        return (int(drive_min) // _BREAK_PER_MIN) * _BREAK_MIN
    except (TypeError, ValueError):
        return 0


@app.route("/api/plan/retime", methods=["POST", "OPTIONS"])
def api_plan_retime():
    """実測の移動時間で、行程の時刻を組み直す。

    本文（JSON）
      leave / return   希望の出発・帰着（"5:00" の形。省略時 5:00 / 20:00）
      stay_over        宿泊するなら true。帰りの移動を数えない
      stops            [{name, place, best_min, arrive_min, sun_based, stay_min}]
      legs             [分]。出発地→1か所目、1→2、… の実測。stops と同じ数
      home             最後の撮影地→出発地の実測（分）。stay_over なら無視

    狙い時刻の考え方は行程を組むときと同じ。着いていたい時刻（arrive_min）まで
    待ち、太陽で決まる被写体は本番が終わるまで滞在する。
    """
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = "https://reference.fukei-shashin.co.jp"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Max-Age"] = "86400"
        return resp

    body = request.get_json(silent=True) or {}
    stops = body.get("stops") or []
    legs = body.get("legs") or []
    if not isinstance(stops, list) or not stops:
        return jsonify({"error": "stops required"}), 400
    if len(stops) > 8:
        return jsonify({"error": "too many stops"}), 400
    if not isinstance(legs, list) or len(legs) < len(stops):
        return jsonify({"error": "legs must cover every stop"}), 400

    leave_min = _hhmm_to_min(body.get("leave"), 5 * 60)
    return_min = _hhmm_to_min(body.get("return"), 20 * 60)
    stay_over = bool(body.get("stay_over"))

    def _num(v, default=0):
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            return default

    try:
        out_stops = []
        now = leave_min
        drive_total = 0
        break_total = 0

        for i, st in enumerate(stops):
            move = max(0, _num(legs[i]))
            brk = break_for(move)
            arrive = now + move + brk
            wait = 0
            tgt = st.get("arrive_min")
            if tgt is not None:
                tgt = _num(tgt, None) if tgt is not None else None
            if tgt is not None and arrive < tgt:
                wait = tgt - arrive
                arrive += wait

            best = st.get("best_min")
            best = _num(best, None) if best is not None else None
            stay = max(1, _num(st.get("stay_min"), _PLAN_STAY_MIN))
            if st.get("sun_based") and best is not None:
                stay = max(stay, (best - arrive) + _SHOOT_MIN)

            out_stops.append({
                "name": st.get("name", ""),
                "place": st.get("place", ""),
                "drive_min": move,
                "break_min": brk,
                "arrive": hhmm(arrive),
                "leave": hhmm(arrive + stay),
                "stay_min": stay,
                "wait_min": wait,
                "timing": _timing(arrive, best),
                "best_time": hhmm(best) if best is not None else "",
            })
            drive_total += move
            break_total += brk
            now = arrive + stay

        home = 0 if stay_over else max(0, _num(body.get("home")))
        home_break = 0 if stay_over else break_for(home)
        back = now + home + home_break
        drive_total += home
        break_total += home_break

        # 1か所目で待つことになるなら、そのぶん遅く出ればよい。行程を組むときと同じ考え方。
        depart = leave_min + (out_stops[0]["wait_min"] if out_stops else 0)
        if out_stops:
            out_stops[0]["wait_min"] = 0

        warnings = []
        if not stay_over and back > return_min:
            warnings.append("帰着が希望より%d分遅くなります。" % (back - return_min))
        late = [s["place"] or s["name"] for s in out_stops if s["timing"] == "遅い"]
        if late:
            warnings.append("%s は本番に間に合いません。" % "・".join(late[:2]))
        if break_total:
            warnings.append("%d分の休憩を含めています（2時間走るごとに15分）。" % break_total)

        return _cors(jsonify({
            "depart": hhmm(depart),
            "back": hhmm(back),
            "total_min": back - depart,
            "drive_total_min": drive_total,
            "break_total_min": break_total,
            "stay_total_min": sum(s["stay_min"] for s in out_stops),
            "stops": out_stops,
            "warnings": warnings,
            "over_min": max(0, back - return_min) if not stay_over else 0,
        }))
    except Exception:
        import traceback
        print("[ERROR] api_plan_retime: %s" % traceback.format_exc(), flush=True)
        return _cors(jsonify({"error": "組み直せませんでした"})), 500



# ──────────────── コンシェルジュ（Web側から呼ぶ入口） ────────────────
# LINEの handle_message が持っていた「言葉を読み取って撮影地を選ぶ」部分を、
# 送る文面の組み立てから切り離したもの。中身の判断は handle_message と同じ道具
# （parse_period / parse_target_area / detect_subject_longest / search_by_place /
# select_three_points）を使う。つまりLINEとWebで答えがずれない。
#
# 違うのは状態の持ち方だけ。LINEは「いま問い返しの途中かどうか」をサーバー側に
# 覚えさせていた（AMBIGUOUS_PENDING など）。こちらは覚えない。聞き返したいときは
# 聞く中身を choices に入れて返し、答えは次の呼び出しで pref / subject として
# 受け取る。画面を持つ側が状態を持つほうが、戻る・やり直すが素直に書ける。
#                                                              （2026-10-08）

_REF_SITE = "https://reference.fukei-shashin.co.jp"


def _conc_spot(label, it):
    """1件の作品を、画面がそのまま使える形にする。
    座標は撮影地そのもの（PlaceGeo）を先に見て、無ければ市区町村へ落とす。
    どちらを使ったかは latlng_from で分かるようにしておく。"""
    from urllib.parse import quote
    area = str(it.get('area', '') or '')
    place = str(it.get('place', '') or '')

    ll = place_latlng(area, place)
    src = 'place'
    if not ll:
        ll = work_latlng(area)
        src = 'city' if ll else ''

    params = []
    for k, v in (('area', area), ('place', place),
                 ('title', it.get('title', '')), ('period', it.get('period', '')),
                 ('pub', it.get('pub', '')), ('img', it.get('url', '')),
                 ('winner', it.get('winner', '')), ('award', it.get('award', ''))):
        if v:
            params.append("%s=%s" % (k, quote(str(v))))

    ref_loc = place or area
    map_q = (place + " " + area).strip() if (place or area) else ""
    return {
        "label": label,
        "area": area,
        "place": place,
        "title": str(it.get('title', '') or ''),
        "winner": str(it.get('winner', '') or ''),
        "award": str(it.get('award', '') or ''),
        "period": str(it.get('period', '') or ''),
        "pub": str(it.get('pub', '') or ''),
        "img": str(it.get('url', '') or ''),
        "pic": str(it.get('pic', '') or ''),
        "dnumb": str(it.get('dnumb', '') or ''),
        "dist_km": round(float(it.get('dist', 0) or 0), 1),
        "lat": ll[0] if ll else None,
        "lng": ll[1] if ll else None,
        "latlng_from": src,
        "maps": ("https://maps.google.com/maps?q=" + quote(map_q)) if map_q else "",
        "reference": (_REF_SITE + "/reference?location=" + quote(ref_loc)) if ref_loc else (_REF_SITE + "/reference"),
        "planner": (_REF_SITE + "/planner?" + "&".join(params)) if params else (_REF_SITE + "/planner"),
    }


def _conc_pack(results):
    return [_conc_spot(lbl, it) for _emoji, lbl, it in (results or [])]


def concierge_search(text, origin_latlng=None, origin_name=None, base_date=None,
                     pref=None, subject=None, radius_km=None,
                     expand_time=False, wide=False):
    """言葉から撮影地を選ぶ。

    text        「どこ行く？」に書かれた言葉（地名・被写体・時期が混ざっていてよい）
    origin_*     「どこから？」の起点。距離を測るためだけに使う。
    base_date   「いつ行く？」の日。text に時期が書かれていればそちらが優先。
    pref        同名地名の聞き返しへの答え（県名）
    subject     被写体の聞き返しへの答え
    expand_time 期間を広げる（「広げて探す」を押したとき）
    wide        地域を広げる（同上）

    戻り値の status
      ok        … 候補が出た
      few       … 出たが少ない（広げ方を choices で返す）
      ask_pref  … 同じ地名が複数の県にある
      ask_subject … 「花」のような大きな括りで来た
      ask_city  … 北海道のように広すぎる
      author    … 地名でも被写体でもなく、作者名だった
      info      … 伝えることはあるが候補は出せない
      none      … 見つからなかった
    """
    out = {"status": "none", "message": "", "note": "", "choices": [],
           "peaks": [], "peaks_text": "", "count": 0, "spots": [], "read": {}}

    t = str(text or "").strip()
    pp = parse_period(t, today=base_date)
    if not pp['specified'] and base_date:
        pp = {'date': base_date, 'specified': True, 'granularity': 'day'}
    target_date = pp['date']
    ol = tuple(origin_latlng) if origin_latlng else None
    on = origin_name or DEFAULT_ORIGIN_NAME

    def _read(area_name=None, area_display=None, subj=None, center=None, rad=None):
        out["read"] = {
            "date": target_date.isoformat(),
            "date_label": period_phrase(pp),
            "date_specified": bool(pp['specified']),
            "pref": area_name if area_name not in (None, 'AMBIGUOUS') else None,
            "area": area_display or None,
            "subject": subj or None,
            "center": list(center) if center else None,
            "radius_km": rad,
            "origin": list(ol) if ol else None,
            "origin_name": on,
        }

    if not t and not subject:
        out["status"] = "info"
        out["message"] = "地名（栃木県、美瑛）や被写体（滝、桜）を入れてください。"
        _read()
        return out

    # ── 1. 地域を読む ──
    area_name, area_latlng, area_display = parse_target_area(t)

    # 同名地名の聞き返しに答えが返ってきていれば、ここで確定させる。
    if pref and area_name == "AMBIGUOUS" and area_display:
        _city = area_display
        area_latlng = (CITY_TO_LATLNG.get(_city)
                       or geocode("%s%s" % (pref, _city))
                       or PREF_LATLNG.get(pref))
        area_name, area_display = pref, _city
    elif pref and not area_name and pref in PREF_LATLNG:
        area_name, area_latlng, area_display = pref, PREF_LATLNG[pref], pref

    # ── 2. 被写体を読む ──
    # 地名の部分一致に被写体を取られないよう、見つかった地名を伏せてから探す。
    # （「茨城」の城、「川越」の川、「海老名」の海を被写体と読まないため）
    _msg_for_subj = t
    for _rm in (area_name, area_display):
        if isinstance(_rm, str) and _rm not in ('', 'AMBIGUOUS', '現在地'):
            _msg_for_subj = _msg_for_subj.replace(_rm, " ")
    if area_name in PREF_NEIGHBORS:
        _short = area_name if area_name == "北海道" else re.sub(r'[都府県]$', '', area_name)
        _msg_for_subj = _msg_for_subj.replace(_short, " ")
    _subj = detect_subject_longest(_msg_for_subj)

    if subject and subject in KEYWORD_NORMALIZE:
        _subj = subject          # 聞き返しへの答えが最優先

    # 被写体が決まったら、その語を落としてから地名を取り直す。
    if _subj:
        _msg_wo_subj = t
        for v in KEYWORD_NORMALIZE.get(_subj, []):
            _msg_wo_subj = _msg_wo_subj.replace(v, ' ')
        _msg_wo_subj = re.sub(r'[、,。.・/／｜|\s　]+', ' ', _msg_wo_subj).strip()
        if len(_msg_wo_subj) >= 2:
            _a2, _l2, _d2 = parse_target_area(_msg_wo_subj)
            if _a2 or not pref:
                area_name, area_latlng, area_display = _a2, _l2, _d2

    search_keyword = _subj
    if not search_keyword and not (area_name and area_name != 'AMBIGUOUS'):
        search_keyword = detect_subject_longest(t)

    # ── 3. 「花」のような大きな括りで来たとき ──
    if not _subj and not subject:
        _msg_for_cat = re.sub(
            r'\d{1,2}月(?:\d{1,2}日)?|\d+日後|上旬|中旬|下旬|明日|あした|明後日|あさって|今日|本日|来週末|今週末|来週|今週|週末',
            ' ', t)
        _cat = detect_category(_msg_for_cat)
        if _cat:
            _ccent = ol or SHINJUKU
            _cnear = on if ol else "東京"
            RADIUS_CAT = 300
            _members = SUBJECT_CATEGORIES.get(_cat, [])
            _read(area_name, area_display, None, _ccent, RADIUS_CAT)
            _inpeak = category_members_in_peak(_members, _ccent, RADIUS_CAT, target_date)
            if _inpeak:
                out["status"] = "ask_subject"
                out["message"] = ("「%s」で探します。%sから半径%dkm圏内で、いま撮り頃なのはこちらです。"
                                  % (_cat, _cnear, RADIUS_CAT))
                out["choices"] = [{"kind": "subject", "value": s, "label": s,
                                   "note": "撮り頃 %s・%d件" % (pk, n)}
                                  for s, pk, n in _inpeak[:8]]
                return out
            _nexts = category_next_peaks(_members, _ccent, RADIUS_CAT, target_date)
            if _nexts:
                out["status"] = "ask_subject"
                out["message"] = ("%sの周辺では、いま撮り頃の%sは見つかりませんでした。次に近い撮り頃はこちらです。"
                                  % (_cnear, _cat))
                out["choices"] = [{"kind": "subject", "value": s, "label": s,
                                   "note": "%sごろ" % lbl}
                                  for s, lbl, _d in _nexts[:3]]
                return out
            out["status"] = "none"
            out["message"] = ("%sの周辺では、%sの作品が見つかりませんでした。"
                              "「桜」「ひまわり」のように具体的な名前でもお試しください。" % (_cnear, _cat))
            return out

    # ── 4. 地域＋被写体 / 被写体のみ ──
    if _subj:
        txt = t
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
        place_terms = list(dict.fromkeys(place_terms))

        if place_terms and not wide:
            place_disp = "・".join(place_terms)
            _read(area_name, place_disp, _subj, None, None)
            pr = search_by_place(place_terms, base_date=target_date,
                                 origin_latlng=ol, origin_name=on, subject=_subj,
                                 expand_time=expand_time)
            speaks = pr.get('peaks', [])
            out["peaks"] = speaks
            out["peaks_text"] = peaks_text(speaks) if speaks else ""
            out["note"] = famous_spots_note(subject=_subj, region_text=place_disp,
                                            origin_latlng=ol, base_date=target_date) or ""
            if pr['status'] in ('not_found', 'off_season'):
                out["status"] = "none"
                if pr['status'] == 'off_season':
                    hint = (peak_reason_text("ちなみに「%s」" % place_disp, _subj, speaks)
                            if (_subj in SEASONAL_SUBJECTS and speaks)
                            else "期間を広げると作品が見つかります。")
                    out["message"] = ("%sに「%s」で撮影された%sの作品は見つかりませんでした。%s"
                                      % (period_phrase(pp), place_disp, _subj, hint))
                    out["choices"] = _conc_widen(peaks=speaks, base_date=target_date)
                else:
                    out["message"] = ("%sに「%s」で撮影された%sの作品は見つかりませんでした。"
                                      % (period_phrase(pp), place_disp, _subj))
                    out["choices"] = _conc_widen()
                return out
            out["spots"] = _conc_pack(pr['results'])
            out["count"] = len(out["spots"])
            _sfx = ("（撮り頃は%sごろ）" % peaks_text(speaks)) if (_subj in SEASONAL_SUBJECTS and speaks) else ""
            if pr.get('region'):
                _km = int(pr.get('region_radius_km') or 10)
                if pr.get('region_found'):
                    out["message"] = ("「%s」という地名の%sの作品は%d件でしたので、"
                                      "その周り%dkm以内まで広げて探しました%s。"
                                      % (pr['region'], _subj, pr['region_found'], _km, _sfx))
                else:
                    out["message"] = ("「%s」という地名の作品は見つかりませんでしたが、"
                                      "その周り%dkm以内で撮影された%sの作品はこちらです%s。"
                                      % (pr['region'], _km, _subj, _sfx))
            else:
                out["message"] = ("%sに「%s」で撮影された%sの作品はこちらです%s。"
                                  % (period_phrase(pp), place_disp, _subj, _sfx))
            if out["count"] <= 3:
                out["status"] = "few"
                out["choices"] = _conc_widen(peaks=(speaks if _subj in SEASONAL_SUBJECTS else None), base_date=target_date)
            else:
                out["status"] = "ok"
            return out

        # 地名なし・被写体のみ → 起点（無ければ新宿）から半径150km。
        # 「地域を広げる」を押されたときも、地名の縛りを外してここへ来る。
        # いまは県→全国と一気に広がる。LINEの市→県→隣県→全国のような
        # 段階は付けていない。（2026-10-08）
        center = ol or SHINJUKU
        # 「地域を広げる」を押されたら、半径の縛りを外して全国から近い順に見る。
        rad = None if wide else (float(radius_km) if radius_km else 150.0)
        near_name = on if ol else "東京"
        # 文中の「どこを見たか」。半径を外したときは圏内と言えないので言い分ける。
        _scope = ("全国で" if rad is None
                  else "%sから半径%dkm圏内で" % (near_name, int(rad)))
        _scope_in = "全国" if rad is None else "この圏内"
        _read(None, None, _subj, (None if wide else center), rad)
        prn = search_by_place([], base_date=target_date, origin_latlng=ol, origin_name=on,
                              subject=_subj, center_latlng=(None if wide else center),
                              radius_km=rad, expand_time=expand_time)
        speaks = prn.get('peaks', [])
        out["peaks"] = speaks
        out["peaks_text"] = peaks_text(speaks) if speaks else ""
        out["note"] = famous_spots_note(subject=_subj, origin_latlng=ol, base_date=target_date) or ""
        if prn['status'] == 'in_season':
            out["spots"] = _conc_pack(prn['results'])
            out["count"] = len(out["spots"])
            _sfx = ("（撮り頃は%sごろ）" % peaks_text(speaks)) if (_subj in SEASONAL_SUBJECTS and speaks) else ""
            out["message"] = ("%sに%s撮影された%sの作品はこちらです%s。"
                              % (period_phrase(pp), _scope, _subj, _sfx))
            out["status"] = "few" if out["count"] <= 3 else "ok"
            if out["status"] == "few":
                out["choices"] = _conc_widen(peaks=(speaks if _subj in SEASONAL_SUBJECTS else None), base_date=target_date)
            return out
        out["status"] = "none"
        if prn['status'] == 'off_season':
            hint = (peak_reason_text(_scope_in, _subj, speaks)
                    if (_subj in SEASONAL_SUBJECTS and speaks)
                    else "期間を広げると作品が見つかります。")
            out["message"] = ("%sに%s撮影された%sの作品は見つかりませんでした。%s"
                              % (period_phrase(pp), _scope, _subj, hint))
            out["choices"] = _conc_widen(peaks=speaks, base_date=target_date)
        else:
            out["message"] = ("%sに%s撮影された%sの作品は見つかりませんでした。"
                              % (period_phrase(pp), _scope, _subj))
            out["choices"] = _conc_widen()
        return out

    # ── 5. 同じ地名が複数の県にあるとき ──
    if area_name == "AMBIGUOUS":
        prefs = ambiguous_city_prefs(area_display)
        keyword_variants = {'朝日': ('朝焼け', '朝日（風景・被写体）'),
                            '桜': ('桜', '桜（花）')}
        kw_option = (keyword_variants.get(area_display)
                     or keyword_variants.get(re.sub(r'[市区町村郡]', '', area_display or '').strip()))
        _read(None, area_display, None, None, None)
        out["status"] = "ask_pref"
        out["message"] = "%sは複数の地域にあります。どちらでしょう。" % area_display
        out["choices"] = [{"kind": "pref", "value": p, "label": "%s%s" % (p, area_display)}
                          for p in prefs]
        if kw_option:
            out["choices"].append({"kind": "subject", "value": kw_option[0], "label": kw_option[1]})
        return out

    city_specified = any(c in t for c in ["市", "町", "村", "区", "郡"])

    # ── 6. 地域にも被写体にもならない語 → 地点名として探し、だめなら作者名 ──
    if not area_name and not search_keyword and not city_specified:
        residual = t
        for w in ['明日', 'あした', '明後日', 'あさって', '今日', '本日', '今週末', '来週末', '来週', '今週', '週末']:
            residual = residual.replace(w, '')
        residual = re.sub(r'\d+日後', '', residual)
        residual = re.sub(r'\d{1,2}月\d{1,2}日', '', residual)
        residual = re.sub(r'\d{1,2}月(?:上旬|中旬|下旬)?', '', residual)
        residual = re.sub(r'上旬|中旬|下旬', '', residual)
        for w in FILLER_WORDS:
            residual = residual.replace(w, '')
        residual = re.sub(r'[、,。.・/／｜|\s　]+', '', residual).strip()
        if len(residual) >= 2:
            _read(None, residual, None, None, None)
            pr = search_by_place(residual, base_date=target_date,
                                 origin_latlng=ol, origin_name=on,
                                 expand_time=expand_time)
            out["note"] = famous_spots_note(region_text=residual, origin_latlng=ol,
                                            base_date=target_date) or ""
            if pr['status'] == 'not_found':
                _per = search_by_person(residual, origin_latlng=ol, origin_name=on)
                if _per['status'] == 'author':
                    _n = _per['total']
                    _more = "（本誌掲載は全%d点）" % _n if _n > len(_per['results']) else ""
                    out["status"] = "author"
                    out["message"] = ("%sさんの入選作をご紹介します。%s それぞれの撮影地もあわせてご覧ください。"
                                      % (_per['display'], _more))
                    out["spots"] = _conc_pack(_per['results'])
                    out["count"] = len(out["spots"])
                    return out
                if _per['status'] in ('judge', 'listed_only'):
                    out["status"] = "info"
                    if _per['status'] == 'judge':
                        out["message"] = ("%sさんは本誌フォトコンテストの審査員としてご登場の方です。"
                                          "ご案内しているのは応募作品の撮影地ですので、審査員やプロの方の作品は対象にしておりません。"
                                          % _per['display'])
                    else:
                        out["message"] = ("%sさんの作品は本誌に掲載がありますが、撮影地のご案内の対象にはしておりません。"
                                          % _per['display'])
                    return out
                out["status"] = "none"
                out["message"] = ("「%s」に合う撮影地は見つかりませんでした。"
                                  "地域名（県名・市町村名）や被写体（滝・桜・紅葉・星空など）でもお試しください。" % residual)
                return out
            out["spots"] = _conc_pack(pr['results'])
            out["count"] = len(out["spots"])
            out["peaks"] = pr.get('peaks', [])
            # 文字で引けず、地図で場所を引いて周りを集めたとき。
            # 黙って別の探し方に切り替わると、なぜその顔ぶれなのか分からない。
            if pr.get('region'):
                out["status"] = "ok"
                _km = int(pr.get('region_radius_km') or 10)
                if pr.get('region_found'):
                    out["message"] = ("「%s」という地名の作品は%d件でしたので、"
                                      "その周り%dkm以内まで広げて探しました。"
                                      % (pr['region'], pr['region_found'], _km))
                else:
                    out["message"] = ("「%s」という地名の作品は見つかりませんでしたが、"
                                      "その周り%dkm以内で撮影された作品はこちらです。"
                                      % (pr['region'], _km))
                return out
            if pr['status'] == 'in_season':
                out["status"] = "ok"
                out["message"] = "%sに「%s」で撮影された作品はこちらです。" % (period_phrase(pp), residual)
            else:
                out["status"] = "few"
                peaks = [c for c in pr.get('peaks', []) if (c // 3 + 1) != target_date.month]
                if peaks:
                    out["peaks_text"] = peaks_text(peaks)
                    out["message"] = ("「%s」は%sの作品が少ないようです。撮り頃は%sあたり。"
                                      "参考にこれまでの作品をご紹介します。"
                                      % (residual, period_phrase(pp), peaks_text(peaks)))
                else:
                    out["message"] = ("「%s」は%sの作品が見つかりませんでしたが、これまでの作品をご紹介します。"
                                      % (residual, period_phrase(pp)))
            return out

    # ── 7. 広すぎる県 ──
    city_from_dict = any(city in t or re.sub(r'[市区町村郡]', '', city) in t for city in CITY_TO_PREF)
    if area_name and area_name in WIDE_PREFS and not city_specified and not city_from_dict:
        _read(area_name, area_display, search_keyword, None, None)
        out["status"] = "ask_city"
        out["message"] = ("%sですか。それは楽しみですね。どのあたりに行かれますか。市町村名や地域名を教えてください。"
                          % (area_name if area_name == "北海道" else area_name[:-1]))
        return out

    # ── 8. 地域で探す ──
    _radius = 150 if (city_specified or city_from_dict) else (300 if search_keyword else None)
    if area_latlng is None and ol:
        area_latlng = ol
        if not area_display:
            area_display = "現在地"
    _is_bare_pref = (area_name in PREF_NEIGHBORS) and (area_display == area_name)
    target_city = None if _is_bare_pref else (area_display if (city_specified or city_from_dict) else None)
    _allowed = {area_name} if (area_name in PREF_NEIGHBORS and not target_city) else None
    _read(area_name, area_display, search_keyword, area_latlng, _radius)

    results = select_three_points(base_date=target_date, base_latlng=area_latlng,
                                  radius=(None if wide else _radius), place_name=area_display,
                                  keyword=search_keyword, expand_time=expand_time,
                                  target_city=(None if wide else target_city),
                                  origin_latlng=ol, origin_name=on,
                                  allowed_prefs=(None if wide else _allowed))

    if isinstance(results, tuple) and results and results[0] == 'CITY':
        _, city_base, city_count, results = results
        if not results:
            out["status"] = "none"
            out["message"] = ("%sの前後で%sとその周辺を調べましたが、該当する作品が見つかりませんでした。"
                              % (period_phrase(pp), city_base))
            return out
        out["spots"] = _conc_pack(results)
        out["count"] = len(out["spots"])
        if city_count == 0:
            out["status"] = "few"
            out["message"] = ("%sの前後で%sを調べましたが該当はありませんでした。%s周辺の候補をご紹介します。"
                              % (period_phrase(pp), city_base, city_base))
        elif city_count <= 3:
            out["status"] = "few"
            out["message"] = ("%sの前後で%sを調べたところ該当は%d件でした。周辺の候補も合わせてご紹介します。"
                              % (period_phrase(pp), city_base, city_count))
        else:
            out["status"] = "ok"
            out["message"] = "%sに「%s」で撮影された作品はこちらです。" % (period_phrase(pp), city_base)
        return out

    if isinstance(results, tuple) and results and results[0] == 'TOO_FEW':
        _, found_pref, count, few_results = results
        _disp = area_display or found_pref
        out["spots"] = _conc_pack(few_results)
        out["count"] = len(out["spots"])
        out["status"] = "none" if not few_results else "few"
        out["choices"] = _conc_widen()
        if count == 0 or not few_results:
            out["message"] = ("%sに「%s」で撮影された作品は見つかりませんでした。"
                              % (period_phrase(pp), _disp))
        else:
            out["message"] = ("%sの「%s」の作品は%d件でした。もっと広げて探せます。"
                              % (period_phrase(pp), _disp, count))
        return out

    results = results or []
    if len(results) < 2:
        out["status"] = "none"
        out["message"] = ("今の時期にぴったりの作品が見つかりませんでした。"
                          "地域名や被写体（滝・桜・紅葉など）を変えてもう一度お試しください。")
        return out

    out["status"] = "ok"
    out["spots"] = _conc_pack(results)
    out["count"] = len(out["spots"])
    out["message"] = build_greeting(target_date, area_display, date_specified=pp['specified'])
    out["note"] = famous_spots_note(subject=search_keyword,
                                    region_text=(area_display or area_name or ''),
                                    origin_latlng=ol, base_date=target_date) or ""
    return out


def _conc_widen(peaks=None, base_date=None):
    """候補が足りないときの、次の手。LINEの「もっと広げますか？」にあたる。

    params は、そのまま /api/concierge に足して呼び直すためのもの。
    押しても何も起きない選択肢を返さないよう、受け口のあるものだけを並べる。"""
    opts = [
        {"kind": "widen", "value": "area", "label": "地域を広げて探す",
         "params": {"wide": "1"}},
        {"kind": "widen", "value": "time", "label": "期間を広げて探す",
         "params": {"expand": "1"}},
        {"kind": "widen", "value": "both", "label": "地域と期間の両方を広げる",
         "params": {"wide": "1", "expand": "1"}},
    ]
    if peaks:
        _d, _lbl = next_peak_date(peaks, today=base_date)
        if _d:
            opts.append({"kind": "widen", "value": "peak",
                         "label": "撮り頃（%s）で探す" % _lbl,
                         "params": {"date": _d.isoformat()}})
    return opts


@app.route("/api/concierge", methods=["GET", "OPTIONS"])
def api_concierge():
    """「風景撮ろうよ！」の〈どこ行く？〉から呼ばれる入口。
    別ドメイン（reference.fukei-shashin.co.jp）からの呼び出しなのでCORSを許可する。"""
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = "https://reference.fukei-shashin.co.jp"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Max-Age"] = "86400"
        return resp

    q = (request.args.get("q") or "").strip()

    base = None
    ds = (request.args.get("date") or "").strip()
    if ds:
        try:
            y, m, d = [int(x) for x in ds.split("-")]
            base = date(y, m, d)
        except Exception:
            base = None

    origin = None
    try:
        origin = (float(request.args.get("lat")), float(request.args.get("lng")))
    except (TypeError, ValueError):
        origin = None

    try:
        rad = float(request.args.get("radius")) if request.args.get("radius") else None
    except ValueError:
        rad = None

    try:
        out = concierge_search(
            q,
            origin_latlng=origin,
            origin_name=(request.args.get("origin_name") or "").strip() or None,
            base_date=base,
            pref=(request.args.get("pref") or "").strip() or None,
            subject=(request.args.get("subject") or "").strip() or None,
            radius_km=rad,
            expand_time=(request.args.get("expand", "") in ("1", "true", "yes")),
            wide=(request.args.get("wide", "") in ("1", "true", "yes")),
        )
        out["query"] = q
    except Exception:
        import traceback
        print("[ERROR] api_concierge: %s" % traceback.format_exc(), flush=True)
        out = {"status": "none", "query": q, "spots": [], "count": 0, "choices": [],
               "message": "うまく探せませんでした。言葉を変えてもう一度お試しください。"}

    resp = jsonify(out)
    resp.headers["Access-Control-Allow-Origin"] = "https://reference.fukei-shashin.co.jp"
    return resp



# ──────────────── 改修前後の答え合わせ用（確認専用） ────────────────
# 検索の内部を作り直すとき、答えが変わっていないことを1件ずつ突き合わせるための入口。
# 読むだけで、何も書き換えない。
#
# Renderの環境変数 CHECK_KEY を設定したときだけ有効になる。設定していなければ
# 404を返し、存在しないのと同じ扱いになる。用が済んだら環境変数を消せば閉じる。

def _check_items(results):
    """カルーセルに渡る中身を、比較しやすい形に並べ直す。"""
    out = []
    for emoji, label, it in results:
        out.append({
            "dnumb": it.get("dnumb", ""),
            "pic": it.get("pic", ""),
            "title": it.get("title", ""),
            "area": it.get("area", ""),
            "place": it.get("place", ""),
            "winner": it.get("winner", ""),
            "award": it.get("award", ""),
            "period": it.get("period", ""),
            "dist": round(float(it.get("dist", 0) or 0), 1),
            "label": label,
        })
    return out


def _check_latlng(a, b):
    try:
        return (float(request.args.get(a)), float(request.args.get(b)))
    except (TypeError, ValueError):
        return None


def _check_key_ok():
    """確認用の入口を開けてよいかを判める。
    鍵は X-Check-Key ヘッダーで受け取る。URLに載せるとRenderのアクセスログに
    平文で残ってしまうため、問い合わせ文字列では受け付けない。"""
    key = os.environ.get("CHECK_KEY", "")
    if not key:
        return False
    given = request.headers.get("X-Check-Key", "")
    return bool(given) and given == key


@app.route("/api/_check", methods=["GET"])
def api_check():
    if not _check_key_ok():
        abort(404)

    mode = request.args.get("mode", "place")

    base = None
    ds = request.args.get("date", "")
    if ds:
        try:
            y, m, d = [int(x) for x in ds.split("-")]
            base = date(y, m, d)
        except Exception:
            base = None

    origin = _check_latlng("lat", "lng")
    center = _check_latlng("clat", "clng")
    home = _check_latlng("hlat", "hlng")
    origin_name = request.args.get("origin_name") or DEFAULT_ORIGIN_NAME
    subject = request.args.get("subject") or None
    expand = request.args.get("expand", "") in ("1", "true", "yes")
    try:
        radius = float(request.args.get("radius")) if request.args.get("radius") else None
    except ValueError:
        radius = None
    terms = [t for t in (request.args.get("place") or "").split(",") if t.strip()]
    terms = [t.strip() for t in terms]

    try:
        if mode == "place":
            r = search_by_place(terms, base_date=base, origin_latlng=origin,
                                origin_name=origin_name, subject=subject,
                                center_latlng=center, radius_km=radius,
                                home_latlng=home, expand_time=expand)
            return jsonify({"mode": mode, "status": r.get("status"),
                            "peaks": r.get("peaks", []),
                            "count": len(r.get("results", [])),
                            "items": _check_items(r.get("results", []))})

        if mode == "person":
            r = search_by_person(request.args.get("q", ""),
                                 origin_latlng=origin, origin_name=origin_name)
            return jsonify({"mode": mode, "status": r.get("status"),
                            "display": r.get("display", ""),
                            "total": r.get("total", 0),
                            "count": len(r.get("results", [])),
                            "items": _check_items(r.get("results", []))})

        if mode == "three":
            r = select_three_points(base_date=base, base_latlng=center or origin,
                                    radius=radius, place_name=request.args.get("place_name") or None,
                                    keyword=subject, expand_time=expand,
                                    target_city=request.args.get("city") or None,
                                    origin_latlng=origin, origin_name=origin_name)
            if not r or isinstance(r, tuple):
                return jsonify({"mode": mode, "status": "none",
                                "raw": str(r)[:200], "count": 0, "items": []})
            return jsonify({"mode": mode, "status": "ok",
                            "count": len(r), "items": _check_items(r)})

        if mode == "catpeaks":
            canon = [c for c in (request.args.get("subjects") or "").split(",") if c.strip()]
            rows = category_next_peaks([c.strip() for c in canon],
                                       center or origin, radius or 150, base_date=base)
            return jsonify({"mode": mode, "rows": rows})

        if mode == "peaks":
            rows = subjects_in_peak_near(center or origin, radius or 150, base_date=base)
            return jsonify({"mode": mode, "rows": rows})

        if mode == "snapshot":
            # 保存してある索引の状態だけを見る(全件読みは起こさない)
            snap = load_photo_snapshot()
            if not snap:
                return jsonify({"mode": mode, "exists": False})
            age = (time.time() - snap["built_at"]) / 3600
            return jsonify({"mode": mode, "exists": True,
                            "count": len(snap["rows"]), "reads": snap["reads"],
                            "age_hours": round(age, 2),
                            "fresh": (age * 3600) < _SNAP_TTL})

        return jsonify({"error": "unknown mode"}), 400

    except Exception:
        import traceback
        return jsonify({"error": "exception", "trace": traceback.format_exc()[-1500:]}), 500


@app.route("/api/_reindex", methods=["GET"])
def api_reindex():
    """誌面データを入れ替えたあとに、索引をすぐ作り直すための入口。
    CHECK_KEY を X-Check-Key ヘッダーで送れる人だけが使える。
    ここだけは全件読みが起きる。"""
    if not _check_key_ok():
        abort(404)
    global _PHOTOS, _PHOTOS_AT, _PEAK_INDEX, _PEAK_INDEX_AT
    t0 = time.time()
    built = build_photo_cache()
    if built is None:
        return jsonify({"ok": False, "reason": "Master_Photos が読めませんでした"}), 500
    _PHOTOS, _PHOTOS_AT = built, time.time()
    _PEAK_INDEX, _PEAK_INDEX_AT = None, 0.0      # 撮り頃索引も作り直させる
    saved = save_photo_snapshot(built)
    return jsonify({"ok": True, "read": len(built),
                    "seconds": round(time.time() - t0, 1), "snapshot": saved})


# ──────────────── リッチメニューの確認と解除（確認専用） ────────────────
# 公式アカウントマネージャーで設定したリッチメニューより、Messaging APIで
# 設定したメニューが優先される。しかもAPIで設定したものはマネージャーの一覧に
# 出てこないため、古いメニューが残っていても画面の上では気づけない。
# ここで中身を見て、外す。
#
# 優先順位（上が強い）
#   1. 利用者ごとに結びつけたメニュー
#   2. APIの既定メニュー            ← ここに古いものが残っていると画面では分からない
#   3. 公式アカウントマネージャーで設定したメニュー
#
# 環境変数 CHECK_KEY を設定したときだけ開く。設定していなければ404を返し、
# 存在しないのと同じ扱いになる。鍵は X-Check-Key ヘッダーで受け取る。
# URLに載せるとRenderのアクセスログに平文で残ってしまうため、
# 問い合わせ文字列では受け付けない。LINEのユーザーIDも同じ理由でPOSTの本文で受け取る。

def _richmenu_brief(rm):
    """リッチメニュー1件を、古い・新しいを見比べられる形に整える。"""
    areas = []
    try:
        for a in (getattr(rm, "areas", None) or []):
            act = getattr(a, "action", None)
            areas.append({
                "type": getattr(act, "type", "") or "",
                "label": getattr(act, "label", "") or "",
                "uri": getattr(act, "uri", "") or "",
                "text": getattr(act, "text", "") or "",
                "data": getattr(act, "data", "") or "",
            })
    except Exception:
        areas = []
    size = getattr(rm, "size", None)
    return {
        "richMenuId": getattr(rm, "rich_menu_id", "") or "",
        "name": getattr(rm, "name", "") or "",
        "chatBarText": getattr(rm, "chat_bar_text", "") or "",
        "width": getattr(size, "width", 0) or 0,
        "height": getattr(size, "height", 0) or 0,
        "areas": areas,
    }


@app.route("/api/_richmenu", methods=["POST"])
def api_richmenu():
    """いま何が設定されているかを読むだけ。何も書き換えない。"""
    if not _check_key_ok():
        abort(404)

    body = request.get_json(silent=True) or {}
    out = {"default": None, "list": [], "user": None, "notes": []}

    # 1. APIの既定メニュー
    try:
        out["default"] = line_bot_api.get_default_rich_menu() or None
    except Exception as e:
        if "404" in str(e):
            out["default"] = None          # 設定なし。異常ではない
        else:
            out["notes"].append("既定メニューの取得に失敗しました：%s" % e)

    # 2. APIに登録されているメニューの一覧
    try:
        for rm in (line_bot_api.get_rich_menu_list() or []):
            out["list"].append(_richmenu_brief(rm))
    except Exception as e:
        out["notes"].append("一覧の取得に失敗しました：%s" % e)

    # 3. 利用者ごとの結びつけ（ユーザーIDが分かる場合のみ）
    uid = (body.get("userId") or "").strip()
    if uid:
        try:
            out["user"] = {"userId": uid,
                           "richMenuId": line_bot_api.get_rich_menu_id_of_user(uid) or None}
        except Exception as e:
            note = "結びつけはありません" if "404" in str(e) else str(e)
            out["user"] = {"userId": uid, "richMenuId": None, "note": note}

    return jsonify(out)


@app.route("/api/_richmenu/clear-default", methods=["POST"])
def api_richmenu_clear_default():
    """APIの既定メニューを外す。外すとマネージャーの設定がそのまま使われる。
    メニュー自体は消えないので、やり直しがきく。"""
    if not _check_key_ok():
        abort(404)
    try:
        line_bot_api.cancel_default_rich_menu()
        return jsonify({"ok": True, "did": "APIの既定メニューを外しました"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/_richmenu/unlink-user", methods=["POST"])
def api_richmenu_unlink_user():
    """利用者ひとりに結びついたメニューを外す。"""
    if not _check_key_ok():
        abort(404)
    uid = ((request.get_json(silent=True) or {}).get("userId") or "").strip()
    if not uid:
        return jsonify({"ok": False, "error": "ユーザーIDが空です"}), 400
    try:
        line_bot_api.unlink_rich_menu_from_user(uid)
        return jsonify({"ok": True, "did": "この利用者の結びつけを外しました"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/_richmenu/delete", methods=["POST"])
def api_richmenu_delete():
    """メニューそのものを消す。元に戻せないので、使うのは中身を確かめたあと。"""
    if not _check_key_ok():
        abort(404)
    rid = ((request.get_json(silent=True) or {}).get("richMenuId") or "").strip()
    if not rid:
        return jsonify({"ok": False, "error": "リッチメニューIDが空です"}), 400
    try:
        line_bot_api.delete_rich_menu(rid)
        return jsonify({"ok": True, "did": "メニューを削除しました"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


_RICHMENU_PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>リッチメニューの確認</title>
<style>
 body{font-family:-apple-system,BlinkMacSystemFont,"Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif;
  max-width:760px;margin:0 auto;padding:22px 16px 90px;font-size:17px;line-height:1.75;
  color:#1b2a24;background:#faf9f5;-webkit-text-size-adjust:100%}
 h1{font-size:23px;margin:0 0 6px}
 p.lead{color:#5b6b64;margin:0 0 22px;font-size:16px}
 label{display:block;font-weight:600;margin:18px 0 6px;font-size:16px}
 input{width:100%;font-size:17px;padding:11px 12px;border:1px solid #cfd8d4;
  border-radius:8px;box-sizing:border-box;background:#fff}
 button{font-size:17px;padding:12px 20px;border-radius:8px;border:0;cursor:pointer;
  background:#143d2e;color:#fff;margin:10px 8px 0 0}
 button.sub{background:#fff;color:#143d2e;border:1px solid #9fb3aa}
 button.danger{background:#9b2c2c}
 .card{background:#fff;border:1px solid #e4e8e6;border-radius:10px;padding:16px 18px;margin:16px 0}
 .card .card{background:#faf9f5;margin:12px 0 0}
 .card h2{font-size:18px;margin:0 0 8px}
 .id{font-family:ui-monospace,Menlo,monospace;font-size:14px;word-break:break-all;
  color:#3c4a44;background:#f1f4f2;padding:6px 8px;border-radius:6px}
 .tag{display:inline-block;font-size:14px;padding:3px 10px;border-radius:999px;
  background:#143d2e;color:#fff;margin-left:8px;vertical-align:2px}
 ul{margin:8px 0 0;padding-left:1.3em}
 li{font-size:16px}
 .note{font-size:15px;color:#5b6b64;margin:8px 0 0}
 #msg{margin:16px 0;padding:13px 15px;border-radius:8px;display:none;font-size:16px}
 #msg.ok{display:block;background:#e8f0ec;color:#143d2e}
 #msg.ng{display:block;background:#fdeaea;color:#9b2c2c}
</style></head><body>
<h1>リッチメニューの確認</h1>
<p class="lead">Messaging API で設定したリッチメニューは、公式アカウントマネージャーの一覧には出てきません。
古いメニューがここに残っていると、マネージャーで新しく設定しても画面には反映されません。</p>

<label for="key">CHECK_KEY</label>
<input id="key" type="password" autocomplete="off" placeholder="Render の環境変数に設定した値">
<label for="uid">LINE ユーザーID（分かる場合だけ。空でよい）</label>
<input id="uid" type="text" autocomplete="off" placeholder="U で始まる文字列">
<div><button id="load">いまの設定を見る</button></div>

<div id="msg"></div>
<div id="out"></div>

<script>
var $ = function (s) { return document.querySelector(s); };
function key() { return $("#key").value.trim(); }
function show(ok, t) { var m = $("#msg"); m.className = ok ? "ok" : "ng"; m.textContent = t; }
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function call(path, body) {
  return fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Check-Key": key() },
    body: JSON.stringify(body || {})
  }).then(function (r) {
    if (r.status === 404) {
      throw new Error("CHECK_KEY が違うか、Render の環境変数に設定されていません");
    }
    return r.json().catch(function () { return {}; }).then(function (j) {
      if (!r.ok || j.ok === false) { throw new Error(j.error || ("エラー " + r.status)); }
      return j;
    });
  });
}
function load() {
  if (!key()) { show(false, "CHECK_KEY を入れてください"); return; }
  show(true, "読み込んでいます…");
  var uid = $("#uid").value.trim();
  call("/api/_richmenu", uid ? { userId: uid } : {}).then(function (d) {
    try { sessionStorage.setItem("rmkey", key()); } catch (e) {}
    show(true, "読み込みました");
    render(d);
  }).catch(function (e) { show(false, e.message); $("#out").innerHTML = ""; });
}
function render(d) {
  var h = "";

  h += '<div class="card"><h2>API の既定メニュー</h2>';
  if (d.default) {
    h += '<div class="id">' + esc(d.default) + "</div>";
    h += '<p class="note">これがマネージャーの設定より優先されます。'
       + "下の一覧で中身を確かめて、古いメニューなら外してください。</p>";
    h += '<button class="danger" onclick="clearDefault()">API の既定メニューを外す</button>';
    h += '<p class="note">外してもメニュー自体は消えません。やり直しがききます。</p>';
  } else {
    h += "<p>設定されていません。マネージャーの設定がそのまま使われます。</p>";
  }
  h += "</div>";

  if (d.user) {
    h += '<div class="card"><h2>この利用者に結びついたメニュー</h2>';
    h += '<div class="id">' + esc(d.user.userId) + "</div>";
    if (d.user.richMenuId) {
      h += '<div class="id">' + esc(d.user.richMenuId) + "</div>";
      h += '<p class="note">既定メニューよりさらに優先されます。</p>';
      h += '<button class="danger" onclick="unlinkUser()">この結びつけを外す</button>';
    } else {
      h += "<p>" + esc(d.user.note || "結びつけはありません") + "</p>";
    }
    h += "</div>";
  }

  h += '<div class="card"><h2>API に登録されているメニュー（' + d.list.length + "件）</h2>";
  if (!d.list.length) {
    h += "<p>ありません。</p>";
  }
  d.list.forEach(function (m) {
    h += '<div class="card"><h2>' + esc(m.name || "(名前なし)")
       + (m.richMenuId === d.default ? '<span class="tag">いま既定</span>' : "") + "</h2>";
    h += '<div class="id">' + esc(m.richMenuId) + "</div>";
    h += '<p class="note">メニューバー：' + esc(m.chatBarText)
       + "　／　" + m.width + "×" + m.height + "</p>";
    if (m.areas.length) {
      h += "<ul>";
      m.areas.forEach(function (a) {
        h += "<li>" + esc(a.label || a.type) + "：" + esc(a.uri || a.text || a.data) + "</li>";
      });
      h += "</ul>";
    }
    h += '<button class="sub" onclick="del(\\'' + esc(m.richMenuId) + '\\')">このメニューを削除する</button>';
    h += "</div>";
  });
  h += "</div>";

  if (d.notes && d.notes.length) {
    h += '<div class="card"><h2>気づいたこと</h2><ul>';
    d.notes.forEach(function (n) { h += "<li>" + esc(n) + "</li>"; });
    h += "</ul></div>";
  }

  $("#out").innerHTML = h;
}
function clearDefault() {
  call("/api/_richmenu/clear-default").then(function (j) {
    show(true, j.did + "　LINEアプリを完全に終了してから開き直すと切り替わります。");
    load();
  }).catch(function (e) { show(false, e.message); });
}
function unlinkUser() {
  var uid = $("#uid").value.trim();
  call("/api/_richmenu/unlink-user", { userId: uid }).then(function (j) {
    show(true, j.did);
    load();
  }).catch(function (e) { show(false, e.message); });
}
function del(rid) {
  if (!confirm("このメニューを削除します。元には戻せません。よろしいですか？")) { return; }
  call("/api/_richmenu/delete", { richMenuId: rid }).then(function (j) {
    show(true, j.did);
    load();
  }).catch(function (e) { show(false, e.message); });
}
$("#load").addEventListener("click", load);
$("#key").addEventListener("keydown", function (e) { if (e.key === "Enter") { load(); } });
try {
  var saved = sessionStorage.getItem("rmkey");
  if (saved) { $("#key").value = saved; }
} catch (e) {}
</script>
</body></html>
"""


@app.route("/_richmenu", methods=["GET"])
def page_richmenu():
    """ブラウザで開く確認画面。鍵はこの画面の入力欄で受け取り、
    ヘッダーに載せて送る。URLには載せない。"""
    if not os.environ.get("CHECK_KEY", ""):
        abort(404)
    resp = make_response(_RICHMENU_PAGE)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


# ──────────────── 全国一括点検（確認専用） ────────────────
# これまでの確認が東京起点に偏っていたため、47都道府県の代表地点から
# 同じ検索を一度に走らせて、結果を並べて見るための画面。
#
# 検索そのものは既存の /api/_check を呼ぶだけで、ここで新しい検索は書かない。
# 同じ入口を使うので、本番の利用者がたどる道とずれない。
#
# 1件ずつブラウザから呼び、届いたそばから表に足していく。
# まとめて1回のリクエストにすると、47地点ぶんの検索が終わる前に
# Render側で時間切れになるため。同時に走らせるのは2件まで。
#
# 環境変数 CHECK_KEY を設定したときだけ開く。鍵は X-Check-Key ヘッダーで受け取る。

_SWEEP_PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>全国一括点検</title>
<style>
 body{font-family:-apple-system,BlinkMacSystemFont,"Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif;
  max-width:980px;margin:0 auto;padding:22px 16px 90px;font-size:17px;line-height:1.7;
  color:#1b2a24;background:#faf9f5;-webkit-text-size-adjust:100%}
 h1{font-size:23px;margin:0 0 6px}
 p.lead{color:#5b6b64;margin:0 0 20px;font-size:16px}
 label{display:block;font-weight:600;margin:16px 0 6px;font-size:16px}
 input[type=text],input[type=password],input[type=number]{width:100%;font-size:17px;padding:11px 12px;
  border:1px solid #cfd8d4;border-radius:8px;box-sizing:border-box;background:#fff}
 .checks{margin:14px 0 0}
 .checks label{display:block;font-weight:400;margin:8px 0;font-size:16px;cursor:pointer}
 .checks input{margin-right:8px;transform:scale(1.3)}
 button{font-size:17px;padding:12px 20px;border-radius:8px;border:0;cursor:pointer;
  background:#143d2e;color:#fff;margin:14px 8px 0 0}
 button.sub{background:#fff;color:#143d2e;border:1px solid #9fb3aa}
 button:disabled{opacity:.45;cursor:default}
 .card{background:#fff;border:1px solid #e4e8e6;border-radius:10px;padding:16px 18px;margin:16px 0}
 #status{margin:16px 0;padding:13px 15px;border-radius:8px;display:none;font-size:16px;
  background:#e8f0ec;color:#143d2e}
 #status.ng{background:#fdeaea;color:#9b2c2c}
 table{width:100%;border-collapse:collapse;margin-top:10px;font-size:15px}
 th,td{text-align:left;padding:7px 8px;border-bottom:1px solid #eceeed;vertical-align:top}
 th{font-size:14px;color:#5b6b64;font-weight:600;position:sticky;top:0;background:#faf9f5}
 td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
 tr.warn td{background:#fdf4f4}
 tr.warn td:first-child::before{content:"● ";color:#9b2c2c}
 .sum{font-size:16px;margin:0 0 4px}
 .sum b{font-size:19px}
 .hint{font-size:14px;color:#5b6b64;margin-top:10px}
</style></head><body>
<h1>全国一括点検</h1>
<p class="lead">47都道府県の代表地点から同じ検索を走らせて、結果を並べます。
0件になる地域や、エラーになる地域を見つけるためのものです。
検索は本番と同じ入口（<code>/api/_check</code>）を通ります。</p>

<label for="key">CHECK_KEY</label>
<input id="key" type="password" autocomplete="off" placeholder="Render の環境変数に設定した値">

<label>何を調べるか</label>
<div class="checks">
  <label><input type="checkbox" id="m_peaks" checked>撮り頃の被写体（その地点の周りで、いま撮り頃のもの）</label>
  <label><input type="checkbox" id="m_place" checked>地域＋被写体（県名と被写体を指定した検索）</label>
  <label><input type="checkbox" id="m_three">3地点の選定（AI撮影プランナーの下敷きになる処理）</label>
</div>

<label for="subjects">被写体（読点か空白で区切る。地域＋被写体で使う）</label>
<input id="subjects" type="text" value="紅葉　コスモス　滝">

<label for="radius">半径（km）</label>
<input id="radius" type="number" value="150" min="10" max="500">

<div>
  <button id="run">点検を始める</button>
  <button id="stop" class="sub" disabled>中止</button>
  <button id="copy" class="sub" disabled>結果をコピー</button>
</div>

<div id="status"></div>
<div id="out"></div>

<script>
var PREFS = __PREFS__;
var $ = function (s) { return document.querySelector(s); };
var rows = [], stopped = false, running = false;

function key() { return $("#key").value.trim(); }
function say(t, ng) { var s = $("#status"); s.style.display = "block"; s.className = ng ? "ng" : ""; s.textContent = t; }
function esc(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function check(params) {
  var q = new URLSearchParams(params).toString();
  var t0 = Date.now();
  return fetch("/api/_check?" + q, { headers: { "X-Check-Key": key() } }).then(function (r) {
    if (r.status === 404) { throw new Error("CHECK_KEY が違うか、Render の環境変数に設定されていません"); }
    return r.json().catch(function () { return { error: "返事を読めませんでした" }; })
      .then(function (j) { j.__ms = Date.now() - t0; return j; });
  });
}

/* 1地点ぶんの仕事を並べる。被写体ごとに1件ずつ。 */
function jobsFor(p) {
  var out = [], subs = $("#subjects").value.split(/[,、\s　]+/).filter(Boolean);
  var r = $("#radius").value || "150";
  if ($("#m_peaks").checked) {
    out.push({ pref: p.name, what: "撮り頃", params: { mode: "peaks", clat: p.lat, clng: p.lng, radius: r } });
  }
  if ($("#m_place").checked) {
    subs.forEach(function (s) {
      out.push({
        pref: p.name, what: "地域＋" + s,
        params: { mode: "place", place: p.name, subject: s, lat: p.lat, lng: p.lng, origin_name: p.name, radius: r }
      });
    });
  }
  if ($("#m_three").checked) {
    out.push({ pref: p.name, what: "3地点", params: { mode: "three", clat: p.lat, clng: p.lng, radius: r, origin_name: p.name } });
  }
  return out;
}

/* 返事を見て、気にすべきものかどうかを決める */
function judge(what, j) {
  if (j.error) return { n: "-", s: "エラー: " + (j.error === "exception" ? "例外" : j.error), warn: true };
  if (what === "撮り頃") {
    var n = (j.rows || []).length;
    return { n: n, s: n ? "撮り頃 " + n + "件" : "0件", warn: n === 0 };
  }
  if (what === "3地点") {
    var n = j.count || 0;
    return { n: n, s: j.status === "none" ? "選べず" : n + "地点", warn: n < 3 };
  }
  var c = j.count || 0;
  return { n: c, s: (j.status || "?") + " / " + c + "件", warn: (c === 0) };
}

function render() {
  var warn = rows.filter(function (r) { return r.warn; }).length;
  var h = '<div class="card">';
  h += '<p class="sum">調べた項目 <b>' + rows.length + '</b> 件　／　気になるもの <b>' + warn + '</b> 件</p>';
  h += "<table><tr><th>地点</th><th>項目</th><th>結果</th><th>件数</th><th>秒</th></tr>";
  rows.forEach(function (r) {
    h += '<tr class="' + (r.warn ? "warn" : "") + '"><td>' + esc(r.pref) + "</td><td>" + esc(r.what)
       + "</td><td>" + esc(r.s) + '</td><td class="n">' + esc(r.n) + '</td><td class="n">'
       + (r.ms / 1000).toFixed(1) + "</td></tr>";
  });
  h += "</table>";
  h += '<p class="hint">「気になるもの」は、0件・3地点に満たない・エラー、のいずれかです。'
     + "0件が必ず不具合とは限りません（その県にその被写体の入賞作品が無いだけのこともあります）。"
     + "まわりの県と見比べて、そこだけ極端なら疑ってください。</p>";
  h += "</div>";
  $("#out").innerHTML = h;
}

function runAll() {
  if (!key()) { say("CHECK_KEY を入れてください", true); return; }
  var jobs = [];
  PREFS.forEach(function (p) { jobs = jobs.concat(jobsFor(p)); });
  if (!jobs.length) { say("調べる項目を1つ以上選んでください", true); return; }
  rows = []; stopped = false; running = true;
  $("#run").disabled = true; $("#stop").disabled = false; $("#copy").disabled = true;
  var i = 0, done = 0, failedHard = null;

  function next() {
    if (stopped || i >= jobs.length) { return Promise.resolve(); }
    var job = jobs[i++];
    return check(job.params).then(function (j) {
      var v = judge(job.what, j);
      rows.push({ pref: job.pref, what: job.what, s: v.s, n: v.n, warn: v.warn, ms: j.__ms });
    }).catch(function (e) {
      failedHard = e.message;
      rows.push({ pref: job.pref, what: job.what, s: "エラー: " + e.message, n: "-", warn: true, ms: 0 });
      if (/CHECK_KEY/.test(e.message)) { stopped = true; }
    }).then(function () {
      done++;
      say("点検中… " + done + " / " + jobs.length + "（" + rows[rows.length - 1].pref + "）");
      render();
      return next();
    });
  }

  var lanes = [next(), next()];          // 同時に2件まで。Renderを詰まらせないため
  Promise.all(lanes).then(function () {
    running = false;
    $("#run").disabled = false; $("#stop").disabled = true; $("#copy").disabled = false;
    var warn = rows.filter(function (r) { return r.warn; }).length;
    if (failedHard && /CHECK_KEY/.test(failedHard)) { say(failedHard, true); }
    else if (stopped) { say("中止しました（" + rows.length + "件まで）"); }
    else { say("終わりました。" + rows.length + "件を調べ、気になるものが " + warn + "件。", warn > 0); }
    render();
  });
}

/* ブラウザによっては navigator.clipboard が使えない。そのときのために、
   選択済みの入力欄に結果を出しておき、そのままコピーできるようにする。 */
function copyAll() {
  var t = "地点\\t項目\\t結果\\t件数\\t秒\\n";
  rows.forEach(function (r) {
    t += [r.pref, r.what, r.s, r.n, (r.ms / 1000).toFixed(1)].join("\\t") + "\\n";
  });
  var ta = document.getElementById("dump");
  if (!ta) {
    ta = document.createElement("textarea");
    ta.id = "dump";
    ta.readOnly = true;
    ta.style.cssText = "width:100%;height:220px;margin-top:14px;font-size:14px;padding:10px;"
      + "border:1px solid #cfd8d4;border-radius:8px;font-family:ui-monospace,Menlo,monospace";
    document.getElementById("out").parentNode.appendChild(ta);
  }
  ta.value = t;
  ta.focus();
  ta.setSelectionRange(0, t.length);
  var done = false;
  try { done = document.execCommand("copy"); } catch (e) { done = false; }
  if (done) {
    say("結果をコピーしました。そのまま貼り付けられます。");
    return;
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(t).then(
      function () { say("結果をコピーしました。そのまま貼り付けられます。"); },
      function () { say("下の欄に結果を出して全選択しました。⌘C（WindowsはCtrl+C）でコピーしてください。", true); });
    return;
  }
  say("下の欄に結果を出して全選択しました。⌘C（WindowsはCtrl+C）でコピーしてください。", true);
}

$("#run").addEventListener("click", runAll);
$("#stop").addEventListener("click", function () { stopped = true; say("中止しています…"); });
$("#copy").addEventListener("click", copyAll);
try {
  var saved = sessionStorage.getItem("rmkey");
  if (saved) { $("#key").value = saved; }
} catch (e) {}
$("#key").addEventListener("change", function () {
  try { sessionStorage.setItem("rmkey", key()); } catch (e) {}
});
</script>
</body></html>
"""


@app.route("/_sweep", methods=["GET"])
def page_sweep():
    """ブラウザで開く全国一括点検の画面。鍵はこの画面の入力欄で受け取り、
    ヘッダーに載せて送る。URLには載せない。"""
    if not os.environ.get("CHECK_KEY", ""):
        abort(404)
    prefs = [{"name": _p, "lat": _ll[0], "lng": _ll[1]} for _p, _ll in PREF_LATLNG.items()]
    html = _SWEEP_PAGE.replace("__PREFS__", json.dumps(prefs, ensure_ascii=False))
    resp = make_response(html)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


if __name__ == "__main__":
    # 手元で動かすときの入口。本番（Render）はこれを使わず、gunicorn から
    # app を読み込んで動かす。開発用サーバーは同時アクセスを1件ずつしか
    # 捌けないので、本番で使ってはいけない。
    #   Start Command: gunicorn app:app --workers 1 --threads 8 --timeout 300
    # --workers を1より増やしてはいけない理由は、会話の途中の状態
    # （AMBIGUOUS_PENDING ほか）のところに書いてある。（2026-10-10）
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
