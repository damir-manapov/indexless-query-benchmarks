#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "=== Ruff Format Check ==="
uv run ruff format --check .

echo ""
echo "=== Ruff Lint ==="
uv run ruff check .

echo ""
echo "=== Type Checking (pyright) ==="
uv run pyright .

echo ""
echo "=== Python Check Passed ==="
