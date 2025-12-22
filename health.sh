#!/bin/bash
set -e

echo "=== Checking for secrets with gitleaks ==="
if ! command -v gitleaks &> /dev/null; then
  echo "gitleaks not installed. Install with: brew install gitleaks"
  exit 1
fi
gitleaks detect --source . -v

echo ""
echo "=== Checking for vulnerabilities ==="
pnpm audit --prod

echo ""
echo "=== Checking for outdated dependencies ==="
OUTDATED=$(pnpm outdated 2>&1 || true)
if echo "$OUTDATED" | grep -q "Package"; then
  echo "$OUTDATED"
  echo ""
  echo "NOTE: Some dependencies have updates available (not blocking)"
fi

echo ""
echo "=== Health check passed ==="
