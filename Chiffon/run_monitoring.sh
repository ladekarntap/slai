#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export ARISTA_HOSTS="${ARISTA_HOSTS:-steswitch-vino-aswt01,steswitch-vino-aswt02}"
export ARISTA_USER="${ARISTA_USER:?ARISTA_USER must be set}"
export ARISTA_PASS="${ARISTA_PASS:?ARISTA_PASS must be set}"
export ARISTA_ENABLE_PASS="${ARISTA_ENABLE_PASS:-}"

python3 "${SCRIPT_DIR}/monitor_arista_7050cx3.py" | tee "${SCRIPT_DIR}/arista_monitoring_result.json"
