#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
USER_SKILLS_DIR="$HOME/.claude/skills"

echo "==> Source:  $SCRIPT_DIR"
echo "==> Parent:  $PARENT_DIR"
echo "==> Skills:  $USER_SKILLS_DIR"
echo

# 1. CLAUDE.md -> parent
if [ -f "$SCRIPT_DIR/CLAUDE.md" ]; then
  cp "$SCRIPT_DIR/CLAUDE.md" "$PARENT_DIR/CLAUDE.md"
  echo "[1/6] Copied CLAUDE.md -> $PARENT_DIR/CLAUDE.md"
else
  echo "[1/6] Skipped: $SCRIPT_DIR/CLAUDE.md not found"
fi

# 2. .claude/agents/* -> parent/.claude/agents/
SRC_AGENTS="$SCRIPT_DIR/.claude/agents"
DST_AGENTS="$PARENT_DIR/.claude/agents"
if [ -d "$SRC_AGENTS" ]; then
  mkdir -p "$DST_AGENTS"
  # 用 find + cp 處理（包含隱藏檔，避免空目錄 glob 失敗）
  copied=0
  while IFS= read -r -d '' file; do
    cp "$file" "$DST_AGENTS/"
    copied=$((copied + 1))
  done < <(find "$SRC_AGENTS" -mindepth 1 -maxdepth 1 ! -name '.DS_Store' -print0)
  echo "[2/6] Copied $copied item(s) -> $DST_AGENTS/"
else
  echo "[2/6] Skipped: $SRC_AGENTS not found"
fi

# 3. .claude/hooks/* -> parent/.claude/hooks/  (gate 強制腳本)
SRC_HOOKS="$SCRIPT_DIR/.claude/hooks"
DST_HOOKS="$PARENT_DIR/.claude/hooks"
if [ -d "$SRC_HOOKS" ]; then
  mkdir -p "$DST_HOOKS"
  # 只複製一般檔案：跳過 __pycache__ 等生成目錄（clone 跑過測試後必有；裸 cp 撞目錄會因 set -e 中斷，造成 step 3 之後的部署靜默缺失）
  find "$SRC_HOOKS" -maxdepth 1 -type f -exec cp {} "$DST_HOOKS/" \;
  chmod +x "$DST_HOOKS/gate-check.sh"
  echo "[3/6] Copied hooks -> $DST_HOOKS/"
else
  echo "[3/6] Skipped: $SRC_HOOKS not found"
fi

# 4. hooks 設定 -> parent/.claude/settings.json（無則複製，有則合併 PreToolUse／SessionStart）
SRC_SETTINGS="$SCRIPT_DIR/.claude/settings.json"
DST_SETTINGS="$PARENT_DIR/.claude/settings.json"
if [ -f "$SRC_SETTINGS" ]; then
  if [ ! -f "$DST_SETTINGS" ]; then
    cp "$SRC_SETTINGS" "$DST_SETTINGS"
    echo "[4/6] Copied settings.json -> $DST_SETTINGS"
  else
    python3 - "$SRC_SETTINGS" "$DST_SETTINGS" <<'PYEOF'
import json, sys
src_path, dst_path = sys.argv[1], sys.argv[2]
with open(src_path) as f: src = json.load(f)
with open(dst_path) as f: dst = json.load(f)
added = 0
for event, src_entries in src.get("hooks", {}).items():
    entries = dst.setdefault("hooks", {}).setdefault(event, [])
    for entry in src_entries:
        if entry not in entries:
            entries.append(entry)
            added += 1
if added:
    with open(dst_path, "w") as f:
        json.dump(dst, f, indent=2, ensure_ascii=False)
        f.write("\n")
print(f"[4/6] Merged settings.json: {added} hook entry(ies) added" if added
      else "[4/6] settings.json already up to date")
PYEOF
  fi
else
  echo "[4/6] Skipped: $SRC_SETTINGS not found"
fi

# 5. skills/* -> ~/.claude/skills/  (always overwrite: repo is source of truth)
SRC_SKILLS="$SCRIPT_DIR/skills"
if [ -d "$SRC_SKILLS" ]; then
  mkdir -p "$USER_SKILLS_DIR"
  synced=0
  for skill_path in "$SRC_SKILLS"/*/; do
    [ -d "$skill_path" ] || continue
    skill_name="$(basename "$skill_path")"
    [ "$skill_name" = "_deprecated" ] && continue
    target="$USER_SKILLS_DIR/$skill_name"
    mkdir -p "$target"
    cp -Rf "$skill_path"/. "$target/"
    rm -f "$target/.DS_Store"
    echo "      + sync   $skill_name"
    synced=$((synced + 1))
  done
  echo "[5/6] Skills synced: $synced overwritten with repo version"
else
  echo "[5/6] Skipped: $SRC_SKILLS not found"
fi

# 6. seed RETRO -> parent/retro/RETRO.md（僅在不存在時建立，絕不覆蓋專案累積的教訓）
SRC_SEED="$SCRIPT_DIR/seed/RETRO.seed.md"
DST_RETRO="$PARENT_DIR/retro/RETRO.md"
if [ -f "$SRC_SEED" ]; then
  if [ ! -f "$DST_RETRO" ]; then
    mkdir -p "$PARENT_DIR/retro"
    cp "$SRC_SEED" "$DST_RETRO"
    echo "[6/6] Seeded retro/RETRO.md (通用約束庫)"
  else
    echo "[6/6] Skipped: $DST_RETRO already exists (不覆蓋累積教訓)"
  fi
else
  echo "[6/6] Skipped: $SRC_SEED not found"
fi
echo
echo "Done."
