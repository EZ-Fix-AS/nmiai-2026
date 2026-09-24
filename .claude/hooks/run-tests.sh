#!/bin/bash
# run-tests.sh — Kjør tester ved fullføring
# Versjon 1.0 · April 2026
cd "$CLAUDE_PROJECT_DIR" 2>/dev/null || exit 0

if [[ -f "package.json" ]]; then
  npm test --if-present 2>&1 | tail -10 || true
fi
if [[ -f "pytest.ini" ]] || [[ -f "pyproject.toml" ]] || [[ -f "setup.py" ]]; then
  python3 -m pytest --tb=short -q 2>&1 | tail -10 || true
fi
exit 0
