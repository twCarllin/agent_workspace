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
  echo "[1/5] Copied CLAUDE.md -> $PARENT_DIR/CLAUDE.md"
else
  echo "[1/5] Skipped: $SCRIPT_DIR/CLAUDE.md not found"
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
  done < <(find "$SRC_AGENTS" -mindepth 1 -maxdepth 1 -print0)
  echo "[2/5] Copied $copied item(s) -> $DST_AGENTS/"
else
  echo "[2/5] Skipped: $SRC_AGENTS not found"
fi

# 3. .claude/hooks/* -> parent/.claude/hooks/  (gate 強制腳本)
SRC_HOOKS="$SCRIPT_DIR/.claude/hooks"
DST_HOOKS="$PARENT_DIR/.claude/hooks"
if [ -d "$SRC_HOOKS" ]; then
  mkdir -p "$DST_HOOKS"
  cp "$SRC_HOOKS"/* "$DST_HOOKS/"
  chmod +x "$DST_HOOKS/gate-check.sh"
  echo "[3/5] Copied hooks -> $DST_HOOKS/"
else
  echo "[3/5] Skipped: $SRC_HOOKS not found"
fi

# 4. hooks 設定 -> parent/.claude/settings.json（無則複製，有則合併 PreToolUse）
SRC_SETTINGS="$SCRIPT_DIR/.claude/settings.json"
DST_SETTINGS="$PARENT_DIR/.claude/settings.json"
if [ -f "$SRC_SETTINGS" ]; then
  if [ ! -f "$DST_SETTINGS" ]; then
    cp "$SRC_SETTINGS" "$DST_SETTINGS"
    echo "[4/5] Copied settings.json -> $DST_SETTINGS"
  else
    python3 - "$SRC_SETTINGS" "$DST_SETTINGS" <<'PYEOF'
import json, sys
src_path, dst_path = sys.argv[1], sys.argv[2]
with open(src_path) as f: src = json.load(f)
with open(dst_path) as f: dst = json.load(f)
entries = dst.setdefault("hooks", {}).setdefault("PreToolUse", [])
added = 0
for entry in src["hooks"]["PreToolUse"]:
    if entry not in entries:
        entries.append(entry)
        added += 1
if added:
    with open(dst_path, "w") as f:
        json.dump(dst, f, indent=2, ensure_ascii=False)
        f.write("\n")
print(f"[4/5] Merged settings.json: {added} hook entry(ies) added" if added
      else "[4/5] settings.json already up to date")
PYEOF
  fi
else
  echo "[4/5] Skipped: $SRC_SETTINGS not found"
fi

# 5. skills/* -> ~/.claude/skills/  (always overwrite: repo is source of truth)
SRC_SKILLS="$SCRIPT_DIR/skills"
if [ -d "$SRC_SKILLS" ]; then
  mkdir -p "$USER_SKILLS_DIR"
  synced=0
  for skill_path in "$SRC_SKILLS"/*/; do
    [ -d "$skill_path" ] || continue
    skill_name="$(basename "$skill_path")"
    target="$USER_SKILLS_DIR/$skill_name"
    mkdir -p "$target"
    cp -Rf "$skill_path"/. "$target/"
    echo "      + sync   $skill_name"
    synced=$((synced + 1))
  done
  echo "[5/5] Skills synced: $synced overwritten with repo version"
else
  echo "[5/5] Skipped: $SRC_SKILLS not found"
fi

echo
echo "Done."
