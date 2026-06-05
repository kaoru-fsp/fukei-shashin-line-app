# -*- coding: utf-8 -*-
"""
Firestore 地名の誤入力 一括置換スクリプト（複数ルール対応）

使い方（app.py と同じ環境＝環境変数 FIREBASE_CREDENTIALS が設定済みの場所で実行）:

  1) まずドライラン（変更内容を表示するだけ・DBは書き換えません）:
        python fix_area_typos.py
     → ルールごとの対象件数と例、監査ログ area_typo_fix_log.csv が出力されます。

  2) 問題なければ実適用:
        python fix_area_typos.py apply

修正ルール（必要に応じてここに追記すれば増やせます）:
  - Area「上北村」→「上北山村」（奈良県）
  - Area「茅野氏」→「茅野市」（長野県）
  - Area「佐川氏」→「佐川町」（高知県）

安全設計:
  - 既定はドライラン。'apply' を付けたときだけ書き込みます。
  - 各ルールは「対象フィールドに wrong が含まれるときだけ wrong→right と部分置換」。
    right が wrong を部分文字列として含まないため、二重実行しても安全（冪等）。
  - 変更前後を area_typo_fix_log.csv に記録（ロールバックの参照用）。

※「高知県佐川氏」(1件) は正しくは「佐川町」(佐川市ではない)です。
  CORRECTIONS に {"field": "Area", "wrong": "佐川氏", "right": "佐川町"} を追記しています。
"""
import os
import sys
import csv
import json

import firebase_admin
from firebase_admin import credentials, firestore

COLLECTION = "Master_Photos"
LOG_PATH = "area_typo_fix_log.csv"
BATCH_SIZE = 400  # Firestore のバッチ上限(500)未満

CORRECTIONS = [
    {"field": "Area", "wrong": "上北村", "right": "上北山村"},
    {"field": "Area", "wrong": "茅野氏", "right": "茅野市"},
    {"field": "Area", "wrong": "佐川氏", "right": "佐川町"}
]

APPLY = (len(sys.argv) > 1 and sys.argv[1].lower() == "apply")


def init_db():
    creds_json = os.environ.get("FIREBASE_CREDENTIALS")
    if not creds_json:
        print("[ERROR] 環境変数 FIREBASE_CREDENTIALS が設定されていません。app.py と同じ環境で実行してください。")
        sys.exit(1)
    cred = credentials.Certificate(json.loads(creds_json))
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    return firestore.client()


def main():
    db = init_db()
    print(f"[INFO] モード: {'APPLY（実書き込み）' if APPLY else 'DRY-RUN（確認のみ・書き込みなし）'}")
    for c in CORRECTIONS:
        print(f"       ルール: {c['field']}「{c['wrong']}」→「{c['right']}」")

    # doc_id -> {field: new_value} と、ログ行 (doc_id, field, old, new, rule)
    updates = {}
    log_rows = []
    rule_count = {f"{c['field']}:{c['wrong']}": 0 for c in CORRECTIONS}

    for doc in db.collection(COLLECTION).stream():
        d = doc.to_dict() or {}
        doc_changes = {}
        for c in CORRECTIONS:
            field, wrong, right = c["field"], c["wrong"], c["right"]
            cur = doc_changes.get(field, d.get(field, "") or "")
            if wrong in cur:
                new = cur.replace(wrong, right)
                if new != cur:
                    doc_changes[field] = new
                    rule_count[f"{field}:{wrong}"] += 1
                    log_rows.append([doc.id, field, (d.get(field, "") or ""), new, f"{wrong}->{right}"])
        if doc_changes:
            updates[doc.id] = doc_changes

    total = sum(rule_count.values())
    for k, n in rule_count.items():
        print(f"[INFO] 対象 {k}: {n} 件")
    print(f"[INFO] 変更対象ドキュメント: {len(updates)} 件 / 変更箇所合計: {total} 件")

    # 監査ログ
    with open(LOG_PATH, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["doc_id", "field", "old_value", "new_value", "rule"])
        w.writerows(log_rows)
    print(f"[INFO] 変更内容を {LOG_PATH} に書き出しました。")
    for row in log_rows[:5]:
        print(f"    {row[0]}: {row[1]} 「{row[2]}」→「{row[3]}」")
    if len(log_rows) > 5:
        print(f"    …ほか {len(log_rows) - 5} 件")

    if not updates:
        print("[INFO] 対象がありません。終了します。")
        return

    if not APPLY:
        print("\n[DRY-RUN] 書き込みは行っていません。問題なければ次を実行してください:")
        print("    python fix_area_typos.py apply")
        return

    # 実適用（バッチ書き込み）
    items = list(updates.items())
    done = 0
    for i in range(0, len(items), BATCH_SIZE):
        chunk = items[i:i + BATCH_SIZE]
        batch = db.batch()
        for doc_id, changes in chunk:
            batch.update(db.collection(COLLECTION).document(doc_id), changes)
        batch.commit()
        done += len(chunk)
        print(f"[INFO] 更新済みドキュメント: {done}/{len(items)}")

    print(f"[DONE] {done} 件のドキュメントを更新しました（変更箇所合計 {total} 件）。")


if __name__ == "__main__":
    main()
