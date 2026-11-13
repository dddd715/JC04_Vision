#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

# shellcheck disable=SC1091
source "$SCRIPT_DIR/config.env"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/cases.sh"

usage() {
    cat <<'EOF'
Usage: run_case.sh CASE_ID [options]

Options:
  --duration SECONDS       Override the case measurement duration.
  --warmup SECONDS         Override the case warm-up duration.
  --interval MS            Override the resource sample interval.
  --output DIR             Override the result root directory.
  --non-interactive        Compatibility option; scene setup is always automatic.
  --no-ros-probes          Skip post-measurement ROS topic FPS probes.
  --no-restore             Leave the tested service layout running.
  --dry-run                Print the resolved case without changing services.
  -h, --help               Show this help.
EOF
}

if (( $# == 0 )); then
    usage >&2
    exit 2
fi
if [[ "$1" == -h || "$1" == --help ]]; then
    usage
    exit 0
fi
CASE_ARG="$1"
shift

DRY_RUN=0
while (( $# )); do
    case "$1" in
        --duration)
            (( $# >= 2 )) || die "--duration requires a value"
            DURATION_SECONDS="$2"
            shift 2
            ;;
        --warmup)
            (( $# >= 2 )) || die "--warmup requires a value"
            WARMUP_SECONDS="$2"
            shift 2
            ;;
        --interval)
            (( $# >= 2 )) || die "--interval requires a value"
            SAMPLE_INTERVAL_MS="$2"
            shift 2
            ;;
        --output)
            (( $# >= 2 )) || die "--output requires a value"
            RESULTS_ROOT="$2"
            shift 2
            ;;
        --non-interactive)
            NON_INTERACTIVE=1
            shift
            ;;
        --no-ros-probes)
            ENABLE_ROS_PROBES=0
            shift
            ;;
        --no-restore)
            RESTORE_INITIAL_SERVICE_STATE=0
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "Unknown option: $1"
            ;;
    esac
done

load_case "$CASE_ARG"

[[ "$CASE_DURATION_SECONDS" =~ ^[0-9]+$ ]] || die "Duration must be an integer"
[[ "$CASE_WARMUP_SECONDS" =~ ^[0-9]+$ ]] || die "Warm-up must be an integer"
[[ "$CASE_SAMPLE_INTERVAL_MS" =~ ^[0-9]+$ ]] || die "Interval must be an integer"

printf 'Case: %s - %s\n' "$CASE_ID" "$CASE_TITLE"
printf 'Description: %s\n' "$CASE_DESCRIPTION"
printf 'Services: %s\n' "$(case_service_csv)"
printf 'Flags: face=%s hand=%s pose=%s\n' "$CASE_FACE_ENABLED" "$CASE_HAND_ENABLED" "$CASE_POSE_ENABLED"
printf 'Warm-up: %ss, duration: %ss, interval: %sms\n' \
    "$CASE_WARMUP_SECONDS" "$CASE_DURATION_SECONDS" "$CASE_SAMPLE_INTERVAL_MS"
[[ -z "$CASE_SCENE" ]] || printf 'Scene: %s\n' "$CASE_SCENE"
printf '提示: %s\n' "$CASE_PROMPT"
printf '测试后输出: %s\n' "$CASE_RESULT_HINT"

(( DRY_RUN == 0 )) || exit 0

require_command systemctl
require_command journalctl
require_command python3
require_command flock
require_command timeout
setup_sudo
if (( ${#SUDO[@]} > 0 )); then
    if "${SUDO[@]}" -n -v >/dev/null 2>&1; then
        log "检测到可复用的sudo凭据，不需要输入密码"
    elif [[ -t 0 ]]; then
        log "需要进行一次sudo认证，认证成功后本次测试将自动续期"
        "${SUDO[@]}" -v || die "sudo认证失败，无法自动执行测试"
    else
        die "当前没有可复用的sudo凭据；请先在终端执行一次 sudo -v，再启动自动测试"
    fi
    # All later privileged commands must fail instead of opening another
    # password prompt if the cached timestamp expires.
    SUDO=(sudo -n)
fi
source_ros_environment
verify_ros_domain
export EXPECTED_CAMERA_RESOLUTION EXPECTED_CAMERA_FPS

if [[ -z "${RESULTS_ROOT:-}" ]]; then
    RESULTS_ROOT="$SCRIPT_DIR/results"
fi
DEVICE_ID="${DEVICE_ID:-$(hostname -s)}"
timestamp="$(date '+%Y%m%d_%H%M%S')"
RESULT_DIR="$RESULTS_ROOT/$DEVICE_ID/${timestamp}_${CASE_ID}"
mkdir -p "$RESULT_DIR"
LOG_FILE="$RESULT_DIR/test.log"
log "开始执行 $CASE_ID：$CASE_TITLE"
log "$CASE_PROMPT"

exec 9>/tmp/jc04_vision_resource_test.lock
flock -n 9 || die "Another JC04 vision resource test is already running"

INITIAL_STATE_FILE="$RESULT_DIR/initial_service_state.tsv"
capture_service_state "$INITIAL_STATE_FILE"
restored=0
collector_pid=''
restore_on_exit() {
    local status=$?
    trap - EXIT INT TERM
    if [[ -n "$collector_pid" ]] && kill -0 "$collector_pid" 2>/dev/null; then
        kill -TERM "$collector_pid" 2>/dev/null || true
        wait "$collector_pid" 2>/dev/null || true
    fi
    if [[ "${RESTORE_INITIAL_SERVICE_STATE:-1}" == 1 && "$restored" == 0 ]]; then
        restore_service_state "$INITIAL_STATE_FILE" || true
        restored=1
    fi
    stop_sudo_keepalive || true
    exit "$status"
}
trap restore_on_exit EXIT INT TERM
start_sudo_keepalive

log "正在采集设备、软件、模型和相机环境信息"
"$SCRIPT_DIR/collect_environment.sh" "$RESULT_DIR"

if [[ "$CASE_CAPTURE_STARTUP" == true ]]; then
    log "正在准备停止状态，用于采集视觉服务启动峰值"
    stop_all_services
    sleep 5
    write_service_status "$RESULT_DIR/service_status_before.txt"
else
    log "正在应用 $CASE_ID 的服务组合"
    set_exact_services "${CASE_SERVICES[@]}"
    sleep "$SERVICE_START_SETTLE_SECONDS"
    configure_runtime_flags "$CASE_FACE_ENABLED" "$CASE_HAND_ENABLED" "$CASE_POSE_ENABLED"
    write_service_status "$RESULT_DIR/service_status_before.txt"
fi

wait_for_scene "$CASE_SCENE" "$CASE_PROMPT"
if (( CASE_WARMUP_SECONDS > 0 )); then
    log "场景准备完成，正在预热 ${CASE_WARMUP_SECONDS} 秒，请继续保持提示中的动作"
    sleep "$CASE_WARMUP_SECONDS"
fi

start_epoch="$(date +%s)"
start_iso="$(date --iso-8601=seconds)"
cat >"$RESULT_DIR/case.tsv" <<EOF
case_id	$CASE_ID
title	$CASE_TITLE
description	$CASE_DESCRIPTION
expected_services	$(case_service_csv)
face_enabled	$CASE_FACE_ENABLED
hand_enabled	$CASE_HAND_ENABLED
pose_enabled	$CASE_POSE_ENABLED
warmup_seconds	$CASE_WARMUP_SECONDS
duration_seconds	$CASE_DURATION_SECONDS
sample_interval_ms	$CASE_SAMPLE_INTERVAL_MS
min_available_memory_mb	$MIN_AVAILABLE_MEMORY_MB
max_memory_growth_mb_per_hour	$MAX_MEMORY_GROWTH_MB_PER_HOUR
started_at	$start_iso
scene	$CASE_SCENE
capture_startup	$CASE_CAPTURE_STARTUP
prompt	$CASE_PROMPT
result_hint	$CASE_RESULT_HINT
EOF

log "正式资源采样开始，ROS话题探针暂未启动，不会干扰核心指标"
if [[ "$CASE_CAPTURE_STARTUP" == true ]]; then
    "$SCRIPT_DIR/collect_metrics.sh" "$RESULT_DIR" \
        "$CASE_DURATION_SECONDS" "$CASE_SAMPLE_INTERVAL_MS" &
    collector_pid=$!
    sleep 1
    log "正在资源采样窗口内启动全部视觉服务"
    set_exact_services "${CASE_SERVICES[@]}"
    sleep "$SERVICE_START_SETTLE_SECONDS"
    configure_runtime_flags "$CASE_FACE_ENABLED" "$CASE_HAND_ENABLED" "$CASE_POSE_ENABLED"
    wait "$collector_pid"
    collector_pid=''
else
    "$SCRIPT_DIR/collect_metrics.sh" "$RESULT_DIR" \
        "$CASE_DURATION_SECONDS" "$CASE_SAMPLE_INTERVAL_MS"
fi
end_epoch="$(date +%s)"
end_iso="$(date --iso-8601=seconds)"
actual_duration=$(( end_epoch - start_epoch ))
cat >>"$RESULT_DIR/case.tsv" <<EOF
ended_at	$end_iso
actual_duration_seconds	$actual_duration
EOF

"${SUDO[@]}" journalctl --no-pager -o short-iso \
    --since "$start_iso" --until "$end_iso" \
    -u camera.service \
    -u jc04vision_face.service \
    -u jc04vision_hand.service \
    -u jc04vision_PoseAvoid.service \
    -u jc04vision_PoseTrack.service \
    >"$RESULT_DIR/vision_journal.log" 2>&1 || true
"${SUDO[@]}" journalctl --no-pager -o short-iso -k \
    --since "$start_iso" --until "$end_iso" \
    >"$RESULT_DIR/kernel_journal.log" 2>&1 || true
write_service_status "$RESULT_DIR/service_status_after.txt"

if [[ "${ENABLE_ROS_PROBES:-1}" == 1 && "${ROS_PROBE_SECONDS:-0}" -gt 0 ]]; then
    log "正在单独测量ROS话题频率，持续 ${ROS_PROBE_SECONDS} 秒"
    # shellcheck disable=SC2206
    probe_topics=($ROS_PROBE_TOPICS)
    "$SCRIPT_DIR/measure_topics.sh" "$RESULT_DIR/topic_rates" \
        "$ROS_PROBE_SECONDS" "${probe_topics[@]}"
fi

log "正在生成测试报告"
python3 "$SCRIPT_DIR/generate_report.py" "$RESULT_DIR"

summary_line="$(python3 -c 'import json,sys; data=json.load(open(sys.argv[1], encoding="utf-8")); system=data.get("system", {}); tegra=data.get("tegrastats", {}); fmt=lambda value: "N/A" if value is None else f"{value:.1f}"; print(data.get("verdict", "UNKNOWN"), len(data.get("warnings", [])), fmt(system.get("cpu_percent", {}).get("p95")), fmt(tegra.get("gpu_percent", {}).get("p95")), fmt(system.get("memory_available_mb", {}).get("min")))' "$RESULT_DIR/summary.json" 2>/dev/null || printf 'UNKNOWN 0 N/A N/A N/A')"
read -r verdict warning_count cpu_p95 gpu_p95 memory_min <<<"$summary_line"
log "测试结束：$CASE_TITLE；结果=$verdict；告警数量=$warning_count"
log "测试后输出：$CASE_RESULT_HINT 实测关键指标：整机CPU P95=${cpu_p95}%，GPU P95=${gpu_p95}%，最低可用内存=${memory_min}MB。"
log "详细报告：$RESULT_DIR/REPORT.md"

if [[ "${RESTORE_INITIAL_SERVICE_STATE:-1}" == 1 ]]; then
    restore_service_state "$INITIAL_STATE_FILE"
    restored=1
fi
stop_sudo_keepalive
trap - EXIT INT TERM

log "Completed: $RESULT_DIR"
