#!/usr/bin/env bash
# MengerFlock benchmark evaluation script
# Usage: ./eval.sh <binary> <instance.tsp> <seed> <timeout>
# Output: tour_length on stdout, or "FAIL" on error
# Compatible with macOS and Linux

set -euo pipefail

BINARY="$1"
INSTANCE="$2"
SEED="${3:-42}"
TIMEOUT="${4:-30}"

BINARY_CMD=$(echo "$BINARY" | awk '{print $1}')
if ! command -v "$BINARY_CMD" > /dev/null 2>&1; then
    echo "FAIL: command not found: $BINARY_CMD" >&2
    exit 1
fi

if [ ! -f "$INSTANCE" ]; then
    echo "FAIL: instance not found: $INSTANCE" >&2
    exit 1
fi

# Create temporary files (macOS-compatible mktemp)
PARAM_FILE=$(mktemp /tmp/mengerflock_eval_XXXXXX)
TOUR_FILE=$(mktemp /tmp/mengerflock_eval_tour_XXXXXX)

trap 'rm -f "$PARAM_FILE" "$TOUR_FILE"' EXIT

cat > "$PARAM_FILE" <<EOF
PROBLEM_FILE = $INSTANCE
TOUR_FILE = $TOUR_FILE
SEED = $SEED
RUNS = 1
TIME_LIMIT = $TIMEOUT
EOF

# macOS-compatible timeout using perl
_timeout() {
    local secs="$1"; shift
    perl -e 'alarm shift; exec @ARGV' "$secs" "$@"
}

if _timeout "$TIMEOUT" "$BINARY" "$PARAM_FILE" > /dev/null 2>&1; then
    if [ -f "$TOUR_FILE" ]; then
        # Extract tour length (compatible grep, no GNU -oP)
        TOUR_LENGTH=$(grep 'COMMENT : Length = ' "$TOUR_FILE" | sed 's/.*Length = //' | tr -d '[:space:]')
        if [ -n "$TOUR_LENGTH" ]; then
            echo "$TOUR_LENGTH"
        else
            echo "FAIL: could not parse tour length" >&2
            exit 1
        fi
    else
        echo "FAIL: no tour file produced" >&2
        exit 1
    fi
else
    echo "FAIL: timeout or crash" >&2
    exit 1
fi
