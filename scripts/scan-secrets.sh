#!/usr/bin/env bash
# Secret scan for opslayer. Run before any push; CI can run the same.
#   scripts/scan-secrets.sh             # audit against the baseline
#   scripts/scan-secrets.sh --baseline  # regenerate the baseline after legit changes
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" == "--baseline" ]]; then
    exec detect-secrets scan --baseline .secrets.baseline \
        --exclude-files '\.secrets\.baseline$' \
        --exclude-files '\.venv/' \
        --exclude-files '__pycache__/'
fi

exec detect-secrets scan --baseline .secrets.baseline \
    --exclude-files '\.secrets\.baseline$' \
    --exclude-files '\.venv/' \
    --exclude-files '__pycache__/'
