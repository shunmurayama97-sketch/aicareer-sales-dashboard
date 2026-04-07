#!/usr/bin/env python3
"""
営業管理ダッシュボード ビルドスクリプト

NotionからエクスポートしたCSVを読み込み、ダッシュボードHTMLを生成する。
テンプレート(template.html) + CSVデータ → index.html

使い方:
  python3 build.py                           # デフォルトCSVパスで実行
  python3 build.py --csv path/to/export.csv  # CSVパスを指定
"""

import csv
import json
import os
import sys
import argparse
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DEFAULT_CSV = SCRIPT_DIR.parent.parent / "sales" / "notion_eigyo_kanri_full.csv"
NOTION_URLS_PATH = SCRIPT_DIR / "notion_urls.json"
TEMPLATE_PATH = SCRIPT_DIR / "template.html"
OUTPUT_PATH = SCRIPT_DIR / "index.html"


def load_csv(csv_path: str) -> list[dict]:
    """NotionエクスポートCSVを読み込み、ユニーク企業リストを返す"""
    records = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("会社名", "").strip()
            if name:
                records.append(row)

    # 会社名でユニーク化（先頭を優先）
    unique = {}
    for r in records:
        name = r["会社名"].strip()
        if name not in unique:
            unique[name] = r

    return list(unique.values())


def load_notion_urls() -> dict:
    """会社名→NotionページURLのマッピングを読み込む"""
    if NOTION_URLS_PATH.exists():
        with open(NOTION_URLS_PATH, "r") as f:
            return json.load(f)
    return {}


def to_dashboard_json(records: list[dict]) -> str:
    """レコードをダッシュボード用の軽量JSONに変換"""
    notion_urls = load_notion_urls()
    dashboard = []
    for r in records:
        entry = {
            "n": r.get("会社名", "").strip(),
            "s": r.get("ステータス", "").strip(),
            "p": r.get("優先度", "").strip(),
            "i": r.get("業種", "").strip(),
            "cp": r.get("顧客担当者名", "").strip(),
            "email": r.get("メールアドレス", "").strip(),
            "tel": r.get("電話番号", "").strip(),
            "url": r.get("会社URL", "").strip(),
            "biko": (r.get("備考", "") or "").strip().split("\n")[0][:80],
            "lc": r.get("最終接触日", "").strip(),
            "sd": r.get("送信日", "").strip(),
            "fc": int(float(r.get("フォローアップ回数", "0") or "0")),
            "approved": r.get("承認済み", "").strip().lower() in ("yes", "true", "はい"),
            "linkClick": r.get("リンククリック日時", "").strip(),
            "notionUrl": notion_urls.get(r.get("会社名", "").strip(), ""),
            "full": True,
        }
        dashboard.append(entry)

    # ソート: 優先度高→中→低→未設定、同じ優先度内でステータス順
    status_order = {
        "初回接触済み": 0, "商談中": 1, "提案済み": 2,
        "リサーチ中": 3, "未接触": 4, "受注": 5, "失注": 6, "保留": 7,
    }
    prio_order = {"高": 0, "中": 1, "低": 2, "": 3}
    dashboard.sort(key=lambda x: (prio_order.get(x["p"], 3), status_order.get(x["s"], 9)))

    # 空フィールド除去（JSONサイズ削減）
    for c in dashboard:
        for key in list(c.keys()):
            if c[key] == "" or c[key] == 0 or c[key] is False:
                if key not in ("n", "s"):
                    del c[key]

    return json.dumps(dashboard, ensure_ascii=False)


def build_html(data_json: str) -> str:
    """テンプレートにデータを埋め込んでHTMLを生成"""
    with open(TEMPLATE_PATH, "r") as f:
        template = f.read()

    html = template.replace("__DASHBOARD_DATA__", data_json)
    return html


def print_summary(records: list[dict]):
    """集計サマリーを出力"""
    st = Counter(r.get("ステータス", "").strip() for r in records)
    pr = Counter(r.get("優先度", "").strip() for r in records)
    lc = sum(1 for r in records if r.get("リンククリック日時", "").strip())
    em = sum(1 for r in records if r.get("メールアドレス", "").strip())
    sd = sum(1 for r in records if r.get("送信日", "").strip())

    print(f"企業数: {len(records)}")
    print(f"ステータス: {dict(sorted(st.items(), key=lambda x: -x[1]))}")
    print(f"優先度: {dict(sorted(pr.items(), key=lambda x: -x[1]))}")
    print(f"リンク遷移: {lc} / メール有: {em} / 送信済み: {sd}")


def main():
    parser = argparse.ArgumentParser(description="営業ダッシュボード ビルド")
    parser.add_argument("--csv", default=str(DEFAULT_CSV), help="Notion CSVエクスポートのパス")
    args = parser.parse_args()

    csv_path = args.csv
    if not os.path.exists(csv_path):
        print(f"エラー: CSVが見つかりません: {csv_path}", file=sys.stderr)
        sys.exit(1)

    print(f"CSV読み込み: {csv_path}")
    records = load_csv(csv_path)
    print_summary(records)

    data_json = to_dashboard_json(records)
    html = build_html(data_json)

    with open(OUTPUT_PATH, "w") as f:
        f.write(html)

    print(f"\nダッシュボード更新完了: {OUTPUT_PATH} ({len(html)//1024}KB)")


if __name__ == "__main__":
    main()
