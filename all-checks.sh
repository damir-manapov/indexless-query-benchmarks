#!/bin/bash
set -e

echo "========================================"
echo "Running all checks"
echo "========================================"

./check.sh
./health.sh
./terraform/check.sh

echo ""
echo "========================================"
echo "All checks passed successfully"
echo "========================================"
