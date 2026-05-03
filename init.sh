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
  echo "[1/3] Copied CLAUDE.md -> $PARENT_DIR/CLAUDE.md"
else
  echo "[1/3] Skipped: $SCRIPT_DIR/CLAUDE.md not found"
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
  echo "[2/3] Copied $copied item(s) -> $DST_AGENTS/"
else
  echo "[2/3] Skipped: $SRC_AGENTS not found"
fi

# 3. skills/* -> ~/.claude/skills/  (skip if same-named folder already exists)
SRC_SKILLS="$SCRIPT_DIR/skills"
if [ -d "$SRC_SKILLS" ]; then
  mkdir -p "$USER_SKILLS_DIR"
  added=0
  skipped=0
  for skill_path in "$SRC_SKILLS"/*/; do
    [ -d "$skill_path" ] || continue
    skill_name="$(basename "$skill_path")"
    target="$USER_SKILLS_DIR/$skill_name"
    if [ -e "$target" ]; then
      echo "      - skip   $skill_name (already exists)"
      skipped=$((skipped + 1))
    else
      cp -R "$skill_path" "$target"
      echo "      + copy   $skill_name"
      added=$((added + 1))
    fi
  done
  echo "[3/3] Skills synced: $added added, $skipped skipped"
else
  echo "[3/3] Skipped: $SRC_SKILLS not found"
fi

echo
echo "Done."
