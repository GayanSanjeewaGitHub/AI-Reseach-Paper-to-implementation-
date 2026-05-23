#!/usr/bin/env bash
# MengerFlock Live Dashboard
# Usage: ./dashboard.sh [state_dir] [refresh_seconds]
# Default: ./dashboard.sh state 5

STATE_DIR="${1:-state}"
REFRESH="${2:-5}"
RESULTS="$STATE_DIR/results.tsv"
STRAT_LOG="$STATE_DIR/strategist_log.tsv"
START_TIME=$(date +%s)

while true; do
    clear

    NOW=$(date +"%H:%M:%S")
    ELAPSED=$(( $(date +%s) - START_TIME ))
    MINS=$(( ELAPSED / 60 ))
    SECS=$(( ELAPSED % 60 ))

    # Count results
    TOTAL=0; KEEPS=0; DISCARDS=0; CRASHES=0
    if [ -f "$RESULTS" ]; then
        TOTAL=$(tail -n +2 "$RESULTS" | wc -l | tr -d ' ')
        KEEPS=$(tail -n +2 "$RESULTS" | awk -F'\t' '$7=="keep"' | wc -l | tr -d ' ')
        DISCARDS=$(tail -n +2 "$RESULTS" | awk -F'\t' '$7=="discard"' | wc -l | tr -d ' ')
        CRASHES=$(tail -n +2 "$RESULTS" | awk -F'\t' '$7=="crash"' | wc -l | tr -d ' ')
    fi

    # Header
    echo "┌──────────────────────────────────────────────────────────────┐"
    printf "│  MengerFlock Dashboard  %-20s  Runtime: %dm %ds  │\n" "$NOW" "$MINS" "$SECS"
    echo "├──────────────────────────────────────────────────────────────┤"
    printf "│  Experiments: %-4s  keep: %-4s  discard: %-4s  crash: %-4s  │\n" "$TOTAL" "$KEEPS" "$DISCARDS" "$CRASHES"
    echo "├──────────────────────────────────────────────────────────────┤"

    # Per-researcher stats
    if [ -f "$RESULTS" ]; then
        RESEARCHERS=$(tail -n +2 "$RESULTS" | awk -F'\t' '{print $2}' | sort -u)
        for R in $RESEARCHERS; do
            MODULE=$(tail -n +2 "$RESULTS" | awk -F'\t' -v r="$R" '$2==r {print $3}' | tail -1)
            R_KEEPS=$(tail -n +2 "$RESULTS" | awk -F'\t' -v r="$R" '$2==r && $7=="keep"' | wc -l | tr -d ' ')
            R_DISCARDS=$(tail -n +2 "$RESULTS" | awk -F'\t' -v r="$R" '$2==r && $7=="discard"' | wc -l | tr -d ' ')
            R_CRASHES=$(tail -n +2 "$RESULTS" | awk -F'\t' -v r="$R" '$2==r && $7=="crash"' | wc -l | tr -d ' ')
            R_TOTAL=$(( R_KEEPS + R_DISCARDS + R_CRASHES ))

            # Progress bar (10 chars, filled by keeps ratio)
            if [ "$R_TOTAL" -gt 0 ]; then
                FILL=$(( R_KEEPS * 10 / R_TOTAL ))
            else
                FILL=0
            fi
            BAR=""
            for i in $(seq 1 10); do
                if [ "$i" -le "$FILL" ]; then
                    BAR="${BAR}█"
                else
                    BAR="${BAR}░"
                fi
            done

            printf "│  %-4s %-20s %s  %s keep / %s disc / %s crash  │\n" \
                "$R" "($MODULE)" "$BAR" "$R_KEEPS" "$R_DISCARDS" "$R_CRASHES"
        done
    else
        echo "│  No results yet                                              │"
    fi

    echo "├──────────────────────────────────────────────────────────────┤"

    # Last 5 experiments
    echo "│  Recent experiments:                                         │"
    if [ -f "$RESULTS" ] && [ "$TOTAL" -gt 0 ]; then
        tail -5 "$RESULTS" | while IFS=$'\t' read -r TS RES MOD COMMIT AVG BEST STATUS HYP DESC; do
            # Truncate hypothesis to fit
            SHORT_HYP=$(echo "$HYP" | cut -c1-40)
            TIME_PART=$(echo "$TS" | sed 's/.*T//')
            printf "│  %s %-4s %-7s %-40s │\n" "$TIME_PART" "$RES" "$STATUS" "$SHORT_HYP"
        done
    else
        echo "│  (waiting for first results...)                              │"
    fi

    echo "├──────────────────────────────────────────────────────────────┤"

    # Strategist activity
    STRAT_COUNT=0
    if [ -f "$STRAT_LOG" ]; then
        STRAT_COUNT=$(tail -n +2 "$STRAT_LOG" | wc -l | tr -d ' ')
    fi
    LAST_STRAT=""
    if [ "$STRAT_COUNT" -gt 0 ]; then
        LAST_STRAT=$(tail -1 "$STRAT_LOG" | awk -F'\t' '{print $2 ": " substr($3,1,50)}')
    fi
    printf "│  Strategist: %-3s actions  %-33s │\n" "$STRAT_COUNT" "$LAST_STRAT"

    # Shutdown check
    if [ -f "$STATE_DIR/shutdown" ]; then
        echo "│  *** SHUTDOWN REQUESTED ***                                  │"
    fi

    echo "└──────────────────────────────────────────────────────────────┘"
    echo ""
    echo "  Refreshing every ${REFRESH}s. Ctrl+C to exit."

    sleep "$REFRESH"
done
