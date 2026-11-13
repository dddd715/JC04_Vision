#!/usr/bin/env bash

set -Eeuo pipefail

if (( $# < 3 )); then
    printf 'Usage: %s OUTPUT_DIR DURATION_SECONDS TOPIC...\n' "$0" >&2
    exit 2
fi

OUTPUT_DIR="$1"
DURATION_SECONDS="$2"
shift 2
mkdir -p "$OUTPUT_DIR"

pids=()
for topic in "$@"; do
    safe_name="$(sed 's#^/##; s#[^A-Za-z0-9_.-]#_#g' <<<"$topic")"
    {
        printf 'topic: %s\n' "$topic"
        printf 'measurement_started_at: %s\n' "$(date --iso-8601=seconds)"
        timeout --signal=INT "${DURATION_SECONDS}s" \
            ros2 topic hz --window 200 --wall-time "$topic" || true
    } >"$OUTPUT_DIR/${safe_name}.hz.log" 2>&1 &
    pids+=("$!")
done

for pid in "${pids[@]}"; do
    wait "$pid" || true
done
