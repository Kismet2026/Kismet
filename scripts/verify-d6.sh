#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${ROOT_DIR}/.venv-pytest/bin/python"

WITH_CDK_SYNTH=0

for arg in "$@"; do
  case "$arg" in
    --with-cdk-synth)
      WITH_CDK_SYNTH=1
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Usage: scripts/verify-d6.sh [--with-cdk-synth]" >&2
      exit 1
      ;;
  esac
done

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "Missing test virtualenv: ${VENV_PYTHON}" >&2
  echo "Create it first, for example:" >&2
  echo "  python3 -m venv .venv-pytest" >&2
  echo "  ./.venv-pytest/bin/python -m pip install pytest boto3 moto" >&2
  exit 1
fi

echo "==> Running Domain 6 unit tests"
for service_dir in \
  "${ROOT_DIR}/services/domain-6-analytics/admin-dashboard-service" \
  "${ROOT_DIR}/services/domain-6-analytics/activity-logger-service" \
  "${ROOT_DIR}/services/domain-6-analytics/analytics-pipeline-service" \
  "${ROOT_DIR}/services/domain-6-analytics/health-monitor-service"; do
  echo "--> $(basename "${service_dir}")"
  (
    cd "${service_dir}"
    "${VENV_PYTHON}" -m pytest -q tests/test_lambda_function.py
  )
done

echo
echo "==> Running cross-domain integration test"
"${VENV_PYTHON}" -m pytest -q \
  "${ROOT_DIR}/tests/test_cross_domain_integration.py"

echo
echo "==> Running Python syntax compilation check"
"${VENV_PYTHON}" -m compileall \
  "${ROOT_DIR}/services/domain-6-analytics" \
  "${ROOT_DIR}/frontend/admin/app.py" \
  "${ROOT_DIR}/tests/test_cross_domain_integration.py"

if [[ "${WITH_CDK_SYNTH}" -eq 1 ]]; then
  echo
  echo "==> Running CDK synth for Domain 6 with activity stream enabled"
  (
    cd "${ROOT_DIR}/infra"
    npx cdk synth KismetDomain6 -c enableActivityStream=true --app "python3 app.py" >/dev/null
  )
fi

echo
echo "D6 verification complete."
