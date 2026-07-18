#!/bin/bash
# CLIP Pre-commit Hook — blocks accidental API key leaks
# Install: cp tools/pre_commit_check.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit

set -e

STAGED=$(git diff --cached --name-only)

if [ -z "$STAGED" ]; then
  exit 0
fi

FAIL=0

# Patterns that look like real API keys
PATTERNS=(
  'sk-ant-[a-zA-Z0-9_-]{20,}'      # Anthropic API key
  'tvly-[a-zA-Z0-9]{20,}'          # Tavily API key
  'AIza[0-9A-Za-z_-]{35}'          # Google API key
  '[a-z]{16}'                        # Gmail app password (16 lowercase chars)
  'AKIA[0-9A-Z]{16}'               # AWS access key
)

# Files that should never be committed
BLOCKED_FILES=(".env" "credentials.json" "token.json" "gcp-oauth.keys.json")

echo "🔍 CLIP pre-commit: scanning for secrets..."

# Check for blocked filenames
for file in $STAGED; do
  for blocked in "${BLOCKED_FILES[@]}"; do
    if [[ "$(basename $file)" == "$blocked" ]]; then
      echo "❌ BLOCKED: Attempted to commit $file — this file must never be committed."
      FAIL=1
    fi
  done
done

# Check staged content for secret patterns
for pattern in "${PATTERNS[@]}"; do
  MATCHES=$(git diff --cached -U0 | grep '^\+' | grep -E "$pattern" 2>/dev/null || true)
  if [ -n "$MATCHES" ]; then
    echo "❌ BLOCKED: Possible API key or secret detected in staged changes:"
    echo "$MATCHES" | head -5
    echo ""
    echo "  Remove the secret and try again."
    echo "  If this is a false positive, use: git commit --no-verify"
    FAIL=1
  fi
done

if [ $FAIL -eq 1 ]; then
  echo ""
  echo "Commit blocked to protect your secrets. Fix the issues above."
  exit 1
fi

echo "✅ No secrets found. Proceeding with commit."
exit 0
