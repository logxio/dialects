#!/usr/bin/env bash
#
# Reproduces every number in README.md. Run it from anywhere.
#
#   ./scripts/verify.sh
#
# Overridable:
#   PYTHON     python interpreter to build the two virtualenvs with (default: python3)
#   DIFY_CLI   path to the Dify plugin CLI; without it the packaging step is skipped
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
SKIPPED=()

step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

step "toolchain"
"$PYTHON" --version
node --version
pnpm --version
node -e '
const [maj, min] = process.versions.node.split(".").map(Number);
const ok = (maj === 22 && min >= 22) || (maj === 24 && min >= 15) || maj >= 25;
if (!ok) {
  console.error(`openclaw needs Node >=22.22.3 <23, >=24.15.0 <25, or >=25.9.0 (found ${process.versions.node})`);
  process.exit(1);
}
'

step "the two Python cores are the same file"
diff langchain/src/dialects_page_stats/core.py dify/page_stats_core.py
echo "identical"

step "langchain"
[ -d .venv-langchain ] || "$PYTHON" -m venv .venv-langchain
.venv-langchain/bin/pip install -q -e "langchain[test]"
.venv-langchain/bin/python -m pytest langchain/tests -q

step "dify"
[ -d .venv-dify ] || "$PYTHON" -m venv .venv-dify
.venv-dify/bin/pip install -q -r dify/requirements.txt pytest
.venv-dify/bin/python -m pytest dify/tests -q

step "dify packaging"
DIFY_CLI="${DIFY_CLI:-$(command -v dify || true)}"
if [ -n "$DIFY_CLI" ]; then
  "$DIFY_CLI" plugin package ./dify -o "$(mktemp -d)/page-stats.difypkg"
else
  echo "no Dify CLI on PATH; set DIFY_CLI to run this step"
  SKIPPED+=("dify plugin package")
fi

step "openclaw"
pnpm --dir openclaw install --frozen-lockfile
pnpm --dir openclaw run build
pnpm --dir openclaw exec openclaw plugins build --entry ./dist/index.js --check
pnpm --dir openclaw exec openclaw plugins validate --entry ./dist/index.js
pnpm --dir openclaw test

step "Python and TypeScript agree on identical bytes"
diff <(.venv-langchain/bin/python scripts/parity.py) <(node scripts/parity.mjs)
.venv-langchain/bin/python scripts/parity.py

if [ ${#SKIPPED[@]} -gt 0 ]; then
  printf '\n\033[1m== not run\033[0m\n'
  printf '  %s\n' "${SKIPPED[@]}"
  exit 0
fi

printf '\n\033[1m== all steps ran\033[0m\n'
