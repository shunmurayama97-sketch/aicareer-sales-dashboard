#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["requests"]
# ///
"""
営業管理ダッシュボード ビルドスクリプト（Notion 直読み版）

Notion DB「🎯 営業管理」を REST API で全件取得し、ダッシュボードHTMLを生成する。
テンプレート(template.html) + Notionデータ → index.html

旧仕様（CSVエクスポート + claude -p × MCP 16ビュー回避策）は廃止。
query_db() がページネーション込みで全件を1回で取得するため、Notion 1本が真実の源。

環境変数:
  NOTION_TOKEN   Notion インテグレーション トークン（必須）

使い方:
  NOTION_TOKEN=xxx python3 build.py
  python3 build.py --dry-run    # 取得・集計のみ（HTML出力なし）
"""

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
TEMPLATE_PATH = SCRIPT_DIR / "template.html"
OUTPUT_PATH = SCRIPT_DIR / "index.html"

# 「🎯 営業管理」データベース（collection ID）
NOTION_SALES_DB_ID = "2e593880ae56809d8371cd63f6bcca1e"
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")

# データ大幅減少ガード（誤った全消し防止）。取得件数がこれ未満なら更新スキップ
MIN_RECORDS = 500


# ── Notion REST API ──────────────────────────────────────────────────────────
def _headers() -> dict:
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def query_all_pages() -> list[dict]:
    """営業管理DBを全件取得（ページネーション対応）"""
    url = f"https://api.notion.com/v1/databases/{NOTION_SALES_DB_ID}/query"
    body: dict = {"page_size": 100}
    results = []
    while True:
        resp = requests.post(url, headers=_headers(), json=body, timeout=60)
        if resp.status_code != 200:
            print(f"エラー: Notion API status={resp.status_code}: {resp.text[:300]}",
                  file=sys.stderr)
            sys.exit(1)
        data = resp.json()
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        body["start_cursor"] = data["next_cursor"]
    return results


# ── プロパティ抽出 ─────────────────────────────────────────────────────────────
def p_text(props: dict, name: str) -> str:
    p = props.get(name, {})
    t = p.get("type", "")
    if t == "title":        return "".join(x["plain_text"] for x in p.get("title", []))
    if t == "rich_text":    return "".join(x["plain_text"] for x in p.get("rich_text", []))
    if t == "email":        return p.get("email") or ""
    if t == "url":          return p.get("url") or ""
    if t == "phone_number": return p.get("phone_number") or ""
    return ""

def p_select(props: dict, name: str) -> str:
    s = props.get(name, {}).get("select")
    return s["name"] if s else ""

def p_status(props: dict, name: str) -> str:
    s = props.get(name, {}).get("status")
    return s["name"] if s else ""

def p_checkbox(props: dict, name: str) -> bool:
    return props.get(name, {}).get("checkbox", False)

def p_date(props: dict, name: str) -> str:
    d = props.get(name, {}).get("date")
    return d["start"] if d else ""

def p_number(props: dict, name: str) -> int:
    return int(props.get(name, {}).get("number") or 0)


def extract_records(pages: list[dict]) -> list[dict]:
    """NotionページからダッシュボードJSON用レコードを構築（会社名でユニーク化）"""
    unique = {}
    for page in pages:
        props = page.get("properties", {})
        name = p_text(props, "会社名").strip()
        if not name or name in unique:
            continue
        unique[name] = {
            "n": name,
            "s": p_status(props, "ステータス"),
            "p": p_select(props, "優先度"),
            "i": p_select(props, "業種"),
            "cp": p_text(props, "担当者名"),
            "email": p_text(props, "メールアドレス"),
            "tel": p_text(props, "電話番号"),
            "url": p_text(props, "会社URL"),
            "biko": p_text(props, "備考").strip().split("\n")[0][:80],
            "lc": p_date(props, "最終接触日"),
            "sd": p_date(props, "配信日時"),
            "approved": p_checkbox(props, "配信する"),
            "linkClick": str(p_number(props, "クリック")) if p_number(props, "クリック") else "",
            "notionUrl": page.get("url", ""),
            "full": True,
        }
    return list(unique.values())


def to_dashboard_json(records: list[dict]) -> str:
    """レコードをソート・空フィールド除去してJSON文字列化"""
    # 新ステータス（ファネル進行が深い順に上へ）。移行期の旧名も後方に残す
    status_order = {
        "商談中": 0, "提案済み": 1, "反応あり": 2, "アプローチ済み": 3,
        "アプローチ準備": 4, "未着手": 5, "受注": 6, "失注": 7, "保留": 8,
        # 旧名フォールバック（移行完了後は出現しない）
        "初回接触済み": 3, "リサーチ中": 4, "未接触": 5,
    }
    prio_order = {"高": 0, "中": 1, "低": 2, "": 3}
    records.sort(key=lambda x: (prio_order.get(x["p"], 3), status_order.get(x["s"], 9)))

    # 空フィールド除去（JSONサイズ削減）。n/s は常に残す
    for c in records:
        for key in list(c.keys()):
            if c[key] == "" or c[key] == 0 or c[key] is False:
                if key not in ("n", "s"):
                    del c[key]

    return json.dumps(records, ensure_ascii=False)


def build_html(data_json: str) -> str:
    with open(TEMPLATE_PATH, "r") as f:
        template = f.read()
    return template.replace("__DASHBOARD_DATA__", data_json)


def print_summary(records: list[dict]):
    st = Counter(r.get("s", "") for r in records)
    pr = Counter(r.get("p", "") for r in records)
    lc = sum(1 for r in records if r.get("linkClick", "").strip() not in ("", "0"))
    em = sum(1 for r in records if r.get("email", "").strip())
    sd = sum(1 for r in records if r.get("sd", "").strip())
    print(f"企業数: {len(records)}")
    print(f"ステータス: {dict(sorted(st.items(), key=lambda x: -x[1]))}")
    print(f"優先度: {dict(sorted(pr.items(), key=lambda x: -x[1]))}")
    print(f"クリック有: {lc} / メール有: {em} / 配信済み: {sd}")


def main():
    parser = argparse.ArgumentParser(description="営業ダッシュボード ビルド（Notion直読み）")
    parser.add_argument("--dry-run", action="store_true", help="取得・集計のみ（HTML出力なし）")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        print("エラー: 環境変数 NOTION_TOKEN が未設定です", file=sys.stderr)
        sys.exit(1)

    print("📥 Notion 営業管理DB を取得中...")
    pages = query_all_pages()
    print(f"   {len(pages)} ページ取得")
    records = extract_records(pages)
    print_summary(records)

    # データ大幅減少ガード
    if len(records) < MIN_RECORDS:
        print(f"警告: 件数が {len(records)} 件と少ないため更新をスキップします", file=sys.stderr)
        sys.exit(2)

    if args.dry_run:
        print("🔍 --dry-run のため HTML 出力は行いません")
        return

    data_json = to_dashboard_json(records)
    html = build_html(data_json)
    with open(OUTPUT_PATH, "w") as f:
        f.write(html)
    print(f"\n✅ ダッシュボード更新完了: {OUTPUT_PATH} ({len(html)//1024}KB)")


if __name__ == "__main__":
    main()
