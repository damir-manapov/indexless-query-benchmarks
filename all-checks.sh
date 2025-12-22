#!/bin/bash
set -e

echo "========================================"
echo "Running all checks"
echo "========================================"

echo ""
echo "=== Formatting ==="
pnpm format

echo ""
echo "=== Linting ==="
pnpm lint

echo ""
echo "=== Type checking ==="
pnpm typecheck

echo ""
echo "=== Running tests ==="
pnpm test

echo ""
echo "=== All checks passed ==="
./health.sh

echo ""
echo "========================================"
echo "All checks passed successfully"
echo "========================================"
