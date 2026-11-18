#!/usr/bin/env bash
# Builds and deploys the platform and the cells from CloudShell (docs/DEPLOY.md).
#   ROLE_ARN=... CELLSAAS_PEPPER=... ./scripts/deploy.sh [platform|cells|all]
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ROLE_ARN:?set ROLE_ARN to the LabRole ARN}"
: "${CELLSAAS_PEPPER:?set CELLSAAS_PEPPER (16+ chars)}"
WHAT="${1:-all}"
CELL_RCU="${CELL_RCU:-10}"; CELL_WCU="${CELL_WCU:-10}"; RESERVED="${RESERVED:-0}"

deploy_platform() {
  sam build -t templates/platform.yaml --build-dir .aws-sam/platform
  sam deploy --template-file .aws-sam/platform/template.yaml --stack-name cellsaas-platform \
    --resolve-s3 --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
    --parameter-overrides ExecutionRoleArn="$ROLE_ARN" ApiKeyPepper="$CELLSAAS_PEPPER"
}

deploy_cell() {  # id rcu wcu reserved
  sam deploy --template-file .aws-sam/cell/template.yaml --stack-name "cellsaas-cell-$1" \
    --resolve-s3 --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
    --parameter-overrides CellId="$1" ReadCapacity="$2" WriteCapacity="$3" ReservedConcurrency="$4" \
    ExecutionRoleArn="$ROLE_ARN"
}

deploy_cells() {
  sam build -t templates/cell.yaml --build-dir .aws-sam/cell
  for cell in c1 c2 c3 q; do deploy_cell "$cell" "$CELL_RCU" "$CELL_WCU" "$RESERVED"; done
  # The pool has the capacity of the four cells together (fair comparison, SPEC 5.5).
  deploy_cell pool $((CELL_RCU * 4)) $((CELL_WCU * 4)) $((RESERVED * 4))
}

case "$WHAT" in
  platform) deploy_platform ;;
  cells) deploy_cells ;;
  all) deploy_platform; deploy_cells ;;
  *) echo "usage: $0 [platform|cells|all]"; exit 2 ;;
esac
aws cloudformation describe-stacks --stack-name cellsaas-platform --query "Stacks[0].Outputs" --output table
