#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "=== Terraform Format ==="
terraform fmt -recursive

echo ""
echo "=== Terraform Validate ==="
terraform validate

echo ""
echo "=== TFLint (Linting & Best Practices) ==="
if command -v tflint &> /dev/null; then
    tflint --init
    tflint
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
