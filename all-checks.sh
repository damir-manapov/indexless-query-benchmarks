#!/bin/bash
set -e

echo "========================================"
echo "Running all checks"
echo "========================================"

./check.sh
./health.sh

echo ""
echo "========================================"
echo "All checks passed successfully"
echo "========================================"
