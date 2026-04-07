#!/bin/bash
# ─────────────────────────────────────────────
# 営業管理ダッシュボード 全自動同期スクリプト
#
# Notion営業管理DBから全件取得し、ダッシュボードを更新する。
# claude -p (Max契約CLI) × Notion MCP で100件ずつ取得→マージ。
#
# 使い方:
#   ./sync.sh        # 通常実行（毎朝launchdから自動起動）
#   ./sync.sh --now  # 即時実行（ログ標準出力）
# ─────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
CSV_PATH="$PROJECT_DIR/sales/notion_eigyo_kanri_full.csv"
WORK_DIR="$SCRIPT_DIR/.sync_work"
LOG_FILE="$SCRIPT_DIR/sync.log"
LOCK_FILE="/tmp/sales-dashboard-sync.lock"

NOW_MODE=false
[ "${1:-}" = "--now" ] && NOW_MODE=true

log() {
  local msg="$(date '+%Y-%m-%d %H:%M:%S') $1"
  echo "$msg" >> "$LOG_FILE"
  $NOW_MODE && echo "$msg"
}

# ── ロック ──
if [ -f "$LOCK_FILE" ]; then
  log "[SKIP] 別プロセスが実行中"
  exit 0
fi
trap "rm -f $LOCK_FILE" EXIT
touch "$LOCK_FILE"

log "[START] 同期開始"
mkdir -p "$WORK_DIR"

cd "$PROJECT_DIR"

# ── パス1: 複数ビュー＋ソートで取得 ──
PASS1_PROMPT='Notionの営業管理DB全件を取得してJSONに出力してください。出力以外のテキストは不要です。

以下のビューURLを全て並列でquery-database-viewしてください:
1. https://www.notion.so/2e593880ae56809d8371cd63f6bcca1e?v=07fd0d3028d745ce88f55a880ec7ca75
2. https://www.notion.so/2e593880ae56809d8371cd63f6bcca1e?v=2e593880-ae56-802d-b184-000c51a70eb2
3. https://www.notion.so/2e593880ae56809d8371cd63f6bcca1e?v=2fbb5327-4655-4eff-9c1b-2601490f556d
4. https://www.notion.so/2e793880ae5680f8a201c582a9ce0b6c?v=2e793880-ae56-807e-b346-000cc33ae0ed

結果ファイルを全て読み込み、URLキーで重複排除してマージし、以下のPythonスクリプトで保存してください:

```python
import json, glob
all_records = {}
result_dir = ".claude/projects/-Users-shunmurayama-AICAREER/*/tool-results/"
for fpath in sorted(glob.glob(result_dir + "mcp-notion-notion-query-database-view-*.txt")):
    try:
        with open(fpath) as f:
            raw = json.load(f)
        data = json.loads(raw[0]["text"])
        for r in data["results"]:
            url = r.get("url","")
            if url and url not in all_records:
                all_records[url] = r
    except:
        pass
with open("apps/sales-dashboard/.sync_work/pass1.json","w") as f:
    json.dump(list(all_records.values()), f, ensure_ascii=False)
print(f"pass1: {len(all_records)}件")
```

上記Pythonを実行してください。'

log "[PASS1] 4ビュー並列クエリ"
echo "$PASS1_PROMPT" | claude -p --allowedTools 'mcp__notion__*,Bash,Read' 2>/dev/null | tail -3 >> "$LOG_FILE"

# ── パス2: ソート違いビューで追加取得 ──
PASS2_PROMPT='Notionの営業管理DBから追加レコードを取得します。以下を全て並列でquery-database-viewしてください:

1. https://www.notion.so/2e593880ae56809d8371cd63f6bcca1e?v=33b93880-ae56-813a-b114-000c3dac21a7
2. https://www.notion.so/2e593880ae56809d8371cd63f6bcca1e?v=33b93880-ae56-81de-bc7b-000c5a055b15
3. https://www.notion.so/2e593880ae56809d8371cd63f6bcca1e?v=33b93880-ae56-81b8-b529-000cc9802aab
4. https://www.notion.so/2e593880ae56809d8371cd63f6bcca1e?v=33b93880-ae56-810b-8a52-000c66571f76

結果ファイルを全て読み込み（pass1含む）、URLで重複排除してマージし保存してください:

```python
import json, glob
all_records = {}
# pass1読み込み
try:
    with open("apps/sales-dashboard/.sync_work/pass1.json") as f:
        for r in json.load(f):
            url = r.get("url","")
            if url: all_records[url] = r
except: pass
# 新規結果読み込み
result_dir = ".claude/projects/-Users-shunmurayama-AICAREER/*/tool-results/"
for fpath in sorted(glob.glob(result_dir + "mcp-notion-notion-query-database-view-*.txt")):
    try:
        with open(fpath) as f:
            raw = json.load(f)
        data = json.loads(raw[0]["text"])
        for r in data["results"]:
            url = r.get("url","")
            if url and url not in all_records:
                all_records[url] = r
    except: pass
with open("apps/sales-dashboard/.sync_work/pass2.json","w") as f:
    json.dump(list(all_records.values()), f, ensure_ascii=False)
print(f"pass2: {len(all_records)}件")
```

上記Pythonを実行してください。'

log "[PASS2] ソート違いビュー追加取得"
echo "$PASS2_PROMPT" | claude -p --allowedTools 'mcp__notion__*,Bash,Read' 2>/dev/null | tail -3 >> "$LOG_FILE"

# ── パス3: 業種別＋日付ソートで残り取得 ──
PASS3_PROMPT='Notionの営業管理DBから残りのレコードを取得します。以下を全て並列でquery-database-viewしてください:

1. https://www.notion.so/2e593880ae56809d8371cd63f6bcca1e?v=33b93880-ae56-815d-829e-000c66260b9c
2. https://www.notion.so/2e593880ae56809d8371cd63f6bcca1e?v=33b93880-ae56-812b-a41c-000c9db9dd08
3. https://www.notion.so/2e593880ae56809d8371cd63f6bcca1e?v=33b93880-ae56-81d8-aaf9-000cb1f37729
4. https://www.notion.so/2e593880ae56809d8371cd63f6bcca1e?v=33b93880-ae56-81a2-9fce-000cd78d9723

結果ファイルを全て読み込み（pass2含む）、URLで重複排除してマージし保存してください:

```python
import json, glob
all_records = {}
try:
    with open("apps/sales-dashboard/.sync_work/pass2.json") as f:
        for r in json.load(f):
            url = r.get("url","")
            if url: all_records[url] = r
except: pass
result_dir = ".claude/projects/-Users-shunmurayama-AICAREER/*/tool-results/"
for fpath in sorted(glob.glob(result_dir + "mcp-notion-notion-query-database-view-*.txt")):
    try:
        with open(fpath) as f:
            raw = json.load(f)
        data = json.loads(raw[0]["text"])
        for r in data["results"]:
            url = r.get("url","")
            if url and url not in all_records:
                all_records[url] = r
    except: pass
with open("apps/sales-dashboard/.sync_work/pass3.json","w") as f:
    json.dump(list(all_records.values()), f, ensure_ascii=False)
print(f"pass3: {len(all_records)}件")
```

上記Pythonを実行してください。'

log "[PASS3] 業種別+日付ソート"
echo "$PASS3_PROMPT" | claude -p --allowedTools 'mcp__notion__*,Bash,Read' 2>/dev/null | tail -3 >> "$LOG_FILE"

# ── パス4: メール・URL・備考・担当者ソートで最終取得 ──
PASS4_PROMPT='Notionの営業管理DBから最終レコードを取得します。以下を全て並列でquery-database-viewしてください:

1. https://www.notion.so/2e593880ae56809d8371cd63f6bcca1e?v=33b93880-ae56-81fe-8496-000c7cbec039
2. https://www.notion.so/2e593880ae56809d8371cd63f6bcca1e?v=33b93880-ae56-816d-b3c4-000c6a96f616
3. https://www.notion.so/2e593880ae56809d8371cd63f6bcca1e?v=33b93880-ae56-8195-b87c-000c36ece81d
4. https://www.notion.so/2e593880ae56809d8371cd63f6bcca1e?v=33b93880-ae56-817f-84e1-000c9104dfcb

結果ファイルを全て読み込み（pass3含む）、URLで重複排除してマージしCSVに出力してください:

```python
import json, glob, csv
all_records = {}
try:
    with open("apps/sales-dashboard/.sync_work/pass3.json") as f:
        for r in json.load(f):
            url = r.get("url","")
            if url: all_records[url] = r
except: pass
result_dir = ".claude/projects/-Users-shunmurayama-AICAREER/*/tool-results/"
for fpath in sorted(glob.glob(result_dir + "mcp-notion-notion-query-database-view-*.txt")):
    try:
        with open(fpath) as f:
            raw = json.load(f)
        data = json.loads(raw[0]["text"])
        for r in data["results"]:
            url = r.get("url","")
            if url and url not in all_records:
                all_records[url] = r
    except: pass

# CSV出力
fields = ["会社名","Discord_Message_ID","Discord通知済み","アプローチチャネル","ステータス",
          "フォローアップ回数","メールアドレス","リンククリック日時","事業部","会社URL","備考",
          "優先度","承認済み","担当者","担当者メールアドレス","担当者名","担当者電話番号",
          "文面ドラフト_Gmail","文面ドラフト_LinkedIn","文面ドラフト_X","最終接触日","業種",
          "次回アクション日","次回フォローアップ日","送信日","電話番号","顧客担当者名"]

date_map = {"リンククリック日時":"date:リンククリック日時:start","最終接触日":"date:最終接触日:start",
            "次回アクション日":"date:次回アクション日:start","次回フォローアップ日":"date:次回フォローアップ日:start",
            "送信日":"date:送信日:start"}
bool_map = {"Discord通知済み":"Discord通知済み","承認済み":"承認済み"}

with open("sales/notion_eigyo_kanri_full.csv","w",encoding="utf-8-sig",newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for r in all_records.values():
        row = {}
        for field in fields:
            if field in date_map:
                row[field] = r.get(date_map[field],"") or ""
            elif field in bool_map:
                v = r.get(bool_map[field],"")
                row[field] = "Yes" if v == "__YES__" else "No"
            else:
                row[field] = r.get(field,"") or ""
        w.writerow(row)

print(f"CSV出力: {len(all_records)}件 → sales/notion_eigyo_kanri_full.csv")
```

上記Pythonを実行してください。'

log "[PASS4] 最終取得＋CSV出力"
echo "$PASS4_PROMPT" | claude -p --allowedTools 'mcp__notion__*,Bash,Read,Write' 2>/dev/null | tail -3 >> "$LOG_FILE"

# ── ビルド ──
if [ -f "$CSV_PATH" ]; then
  python3 "$SCRIPT_DIR/build.py" --csv "$CSV_PATH" >> "$LOG_FILE" 2>&1
  TOTAL=$(python3 -c "import csv; print(sum(1 for _ in csv.reader(open('$CSV_PATH',encoding='utf-8-sig')))-1)")
  log "[DONE] $TOTAL 件でダッシュボード更新完了"
else
  log "[ERROR] CSVが見つかりません"
  exit 1
fi

# ── GitHub Pages にデプロイ ──
cd "$SCRIPT_DIR"
if [ -d ".git" ]; then
  git add index.html notion_urls.json
  git diff --cached --quiet || {
    git commit -m "sync: $(date '+%Y-%m-%d %H:%M') - ${TOTAL}件"
    git push origin main >> "$LOG_FILE" 2>&1
    log "[DEPLOY] GitHub Pages更新完了"
  }
fi
cd "$PROJECT_DIR"

# ── ワークファイル削除 ──
rm -rf "$WORK_DIR"
