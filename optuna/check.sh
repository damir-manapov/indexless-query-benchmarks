#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "=== Ruff Format ==="
uv run ruff format .

echo ""
echo "=== Ruff Lint ==="
uv run ruff check .

echo ""
echo "=== Type Checking (pyright) ==="
uv run pyright .

echo ""
echo "=== Running Tests (pytest) ==="
uv run pytest storage/tests/ -v

echo ""
echo "=== Python Check Passed ==="
