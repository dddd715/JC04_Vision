#!/usr/bin/env bash

set -Eeuo pipefail

usage() {
    printf 'Usage: %s OUTPUT_DIR DURATION_SECONDS INTERVAL_MS\n' "$0" >&2
}

if (( $# != 3 )); then
    usage
    exit 2
fi

OUTPUT_DIR="$1"
DURATION_SECONDS="$2"
INTERVAL_MS="$3"

[[ "$DURATION_SECONDS" =~ ^[0-9]+$ ]] || { printf 'Duration must be an integer\n' >&2; exit 2; }
[[ "$INTERVAL_MS" =~ ^[0-9]+$ ]] || { printf 'Interval must be an integer\n' >&2; exit 2; }
(( DURATION_SECONDS > 0 )) || { printf 'Duration must be positive\n' >&2; exit 2; }
(( INTERVAL_MS >= 100 )) || { printf 'Interval must be at least 100 ms\n' >&2; exit 2; }

mkdir -p "$OUTPUT_DIR"
SYSTEM_CSV="$OUTPUT_DIR/system_metrics.csv"
SERVICE_CSV="$OUTPUT_DIR/service_metrics.csv"
TEGRA_LOG="$OUTPUT_DIR/tegrastats.log"
SERVICES=(camera jc04vision_face jc04vision_hand jc04vision_PoseAvoid jc04vision_PoseTrack)

printf '%s\n' 'timestamp,user,nice,system,idle,iowait,irq,softirq,steal,mem_total_kb,mem_available_kb,swap_total_kb,swap_free_kb,pswpin,pswpout,load1,load5,load15' >"$SYSTEM_CSV"
printf '%s\n' 'timestamp,service,active_state,sub_state,main_pid,cpu_usage_nsec,memory_current_bytes,tasks_current,restarts' >"$SERVICE_CSV"
: >"$TEGRA_LOG"

tegra_pid=''
cleanup() {
    if [[ -n "$tegra_pid" ]] && kill -0 "$tegra_pid" 2>/dev/null; then
        kill -INT "$tegra_pid" 2>/dev/null || true
        wait "$tegra_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

if command -v tegrastats >/dev/null 2>&1; then
    timeout --signal=INT "${DURATION_SECONDS}s" \
        stdbuf -oL tegrastats --interval "$INTERVAL_MS" >"$TEGRA_LOG" 2>&1 &
    tegra_pid=$!
else
    printf 'tegrastats not found\n' >"$TEGRA_LOG"
fi

interval_seconds="$(awk -v ms="$INTERVAL_MS" 'BEGIN { printf "%.3f", ms / 1000.0 }')"
deadline=$(( $(date +%s) + DURATION_SECONDS ))

while (( $(date +%s) < deadline )); do
    timestamp="$(date +%s.%N)"
    read -r _ user nice system idle iowait irq softirq steal _ </proc/stat
    mem_total="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
    mem_available="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
    swap_total="$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)"
    swap_free="$(awk '/^SwapFree:/ {print $2}' /proc/meminfo)"
    pswpin="$(awk '$1 == "pswpin" {print $2}' /proc/vmstat)"
    pswpout="$(awk '$1 == "pswpout" {print $2}' /proc/vmstat)"
    read -r load1 load5 load15 _ </proc/loadavg

    printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
        "$timestamp" "$user" "$nice" "$system" "$idle" "${iowait:-0}" \
        "${irq:-0}" "${softirq:-0}" "${steal:-0}" "$mem_total" \
        "$mem_available" "$swap_total" "$swap_free" "$pswpin" "$pswpout" \
        "$load1" "$load5" "$load15" >>"$SYSTEM_CSV"

    for service_name in "${SERVICES[@]}"; do
        properties="$(systemctl show "${service_name}.service" \
            -p ActiveState -p SubState -p MainPID -p CPUUsageNSec \
            -p MemoryCurrent -p TasksCurrent -p NRestarts 2>/dev/null || true)"
        active_state="$(awk -F= '$1 == "ActiveState" {print $2}' <<<"$properties")"
        sub_state="$(awk -F= '$1 == "SubState" {print $2}' <<<"$properties")"
        main_pid="$(awk -F= '$1 == "MainPID" {print $2}' <<<"$properties")"
        cpu_usage="$(awk -F= '$1 == "CPUUsageNSec" {print $2}' <<<"$properties")"
        memory_current="$(awk -F= '$1 == "MemoryCurrent" {print $2}' <<<"$properties")"
        tasks_current="$(awk -F= '$1 == "TasksCurrent" {print $2}' <<<"$properties")"
        restarts="$(awk -F= '$1 == "NRestarts" {print $2}' <<<"$properties")"

        printf '%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
            "$timestamp" "$service_name" "${active_state:-unknown}" \
            "${sub_state:-unknown}" "${main_pid:-0}" "${cpu_usage:-0}" \
            "${memory_current:-0}" "${tasks_current:-0}" "${restarts:-0}" \
            >>"$SERVICE_CSV"
    done

    sleep "$interval_seconds"
done

cleanup
trap - EXIT INT TERM
