#!/bin/bash
# block-dangerous.sh — Blokkerer farlige kommandoer
# Versjon 1.0 · April 2026
set -euo pipefail
INPUT=$(cat 2>/dev/null || echo '{}')
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || echo "")
[[ -z "$CMD" ]] && exit 0

PATTERNS=(
  "rm -rf /" "rm -rf ~" "rm -rf \."
  "DROP TABLE" "DROP DATABASE" "TRUNCATE TABLE"
  "DELETE FROM .* WHERE 1"
  "git push.*--force" "git push.*-f"
  "chmod -R 777" "mkfs\." "dd if=.*/dev/"
)

for p in "${PATTERNS[@]}"; do
  if echo "$CMD" | grep -qiE "$p"; then
    echo "BLOKKERT: Farlig kommando." >&2
    echo "  Mønster: $p" >&2
    echo "  Kommando: $CMD" >&2
    exit 2
  fi
done

if echo "$CMD" | grep -q "sudo"; then
  echo "Advarsel: sudo detektert." >&2
fi
exit 0
