#!/bin/bash
# format-file.sh — Auto-formatering etter skriving
# Versjon 1.0 · April 2026
INPUT=$(cat 2>/dev/null || echo '{}')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null || echo "")
[[ -z "$FILE" ]] && exit 0
[[ ! -f "$FILE" ]] && exit 0

if echo "$FILE" | grep -qE '\.(js|ts|jsx|tsx|json|css|html|md)$'; then
  npx prettier --write "$FILE" 2>/dev/null || true
fi
if echo "$FILE" | grep -qE '\.py$'; then
  python3 -m black --quiet "$FILE" 2>/dev/null || true
fi
exit 0
