#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "=== Terraform Format & Validate (Selectel) ==="
if [ -d "selectel" ]; then
    (cd selectel && terraform fmt && if [ -d ".terraform" ]; then terraform validate; else echo "Not initialized, skipping validate"; fi)
fi

echo ""
echo "=== Terraform Format & Validate (Timeweb) ==="
if [ -d "timeweb" ]; then
    (cd timeweb && terraform fmt && if [ -d ".terraform" ]; then terraform validate; else echo "Not initialized, skipping validate"; fi)
fi

echo ""
echo "=== TFLint (Linting & Best Practices) ==="
if command -v tflint &> /dev/null; then
    tflint --init
    tflint --recursive
else
    echo "tflint not installed, skipping (install: brew install tflint)"
fi

echo ""
echo "=== Trivy (Security Misconfigurations) ==="
if command -v trivy &> /dev/null; then
    trivy config --severity HIGH,CRITICAL .
else
    echo "trivy not installed, skipping (install: brew install trivy)"
fi

echo ""
echo "=== Terraform Check Passed ==="
