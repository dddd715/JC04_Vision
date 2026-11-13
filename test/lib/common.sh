#!/usr/bin/env bash

# shellcheck shell=bash

ALL_SERVICES=(camera jc04vision_face jc04vision_hand jc04vision_PoseAvoid jc04vision_PoseTrack)
STOP_ORDER=(jc04vision_PoseTrack jc04vision_PoseAvoid jc04vision_hand jc04vision_face camera)

log() {
    local line
    line="[$(date '+%F %T')] $*"
    printf '%s\n' "$line"
    if [[ -n "${LOG_FILE:-}" ]]; then
        printf '%s\n' "$line" >>"$LOG_FILE"
    fi
}

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

setup_sudo() {
    if (( EUID == 0 )); then
        SUDO=()
    else
        require_command sudo
        SUDO=(sudo)
    fi
}

start_sudo_keepalive() {
    (( EUID == 0 )) && return 0
    [[ -n "${SUDO_KEEPALIVE_PID:-}" ]] && return 0

    (
        # The case runner holds its flock on fd 9. Background workers must not
        # inherit it, otherwise they can keep the next suite case locked out
        # after the runner exits.
        exec 9>&-
        keepalive_sleep_pid=''
        cleanup_sudo_keepalive_worker() {
            [[ -z "$keepalive_sleep_pid" ]] && return 0
            kill "$keepalive_sleep_pid" 2>/dev/null || true
            wait "$keepalive_sleep_pid" 2>/dev/null || true
        }
        trap cleanup_sudo_keepalive_worker EXIT INT TERM

        while :; do
            sleep "${SUDO_KEEPALIVE_INTERVAL_SECONDS:-60}" &
            keepalive_sleep_pid=$!
            wait "$keepalive_sleep_pid" || exit 0
            keepalive_sleep_pid=''
            "${SUDO[@]}" -v >/dev/null 2>&1 || exit 0
        done
    ) &
    SUDO_KEEPALIVE_PID=$!
    log "sudo凭据已缓存，测试期间将自动续期，通常无需重复输入密码"
}

stop_sudo_keepalive() {
    local pid="${SUDO_KEEPALIVE_PID:-}"
    [[ -z "$pid" ]] && return 0
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    SUDO_KEEPALIVE_PID=''
}

contains_service() {
    local needle="$1"
    shift
    local item
    for item in "$@"; do
        [[ "$item" == "$needle" ]] && return 0
    done
    return 1
}

source_ros_environment() {
    [[ -f "$ROS_SETUP" ]] || die "ROS setup not found: $ROS_SETUP"
    [[ -f "$JC04_WORKSPACE_SETUP" ]] || die "JC04 workspace setup not found: $JC04_WORKSPACE_SETUP"

    # ROS setup scripts may reference unset variables.
    set +u
    # shellcheck disable=SC1090
    source "$ROS_SETUP"
    # shellcheck disable=SC1090
    source "$JC04_WORKSPACE_SETUP"
    set -u
}

verify_ros_domain() {
    local shell_domain="${ROS_DOMAIN_ID:-0}"
    local service_domain
    service_domain="$(sed -nE 's/^[[:space:]]*export[[:space:]]+ROS_DOMAIN_ID=([0-9]+).*$/\1/p' \
        /home/nvidia/.bashrc 2>/dev/null | tail -n 1)"
    service_domain="${service_domain:-0}"

    if [[ "${ENFORCE_ROS_DOMAIN_MATCH:-1}" == 1 && "$shell_domain" != "$service_domain" ]]; then
        die "Test shell ROS_DOMAIN_ID=$shell_domain differs from service ROS_DOMAIN_ID=$service_domain in /home/nvidia/.bashrc"
    fi
}

capture_service_state() {
    local output_file="$1"
    local service_name state
    : >"$output_file"
    for service_name in "${ALL_SERVICES[@]}"; do
        state="$(systemctl is-active "${service_name}.service" 2>/dev/null || true)"
        printf '%s\t%s\n' "$service_name" "${state:-unknown}" >>"$output_file"
    done
}

stop_all_services() {
    local service_name
    for service_name in "${STOP_ORDER[@]}"; do
        "${SUDO[@]}" systemctl stop "${service_name}.service"
    done
}

set_exact_services() {
    local requested=("$@")
    local service_name

    stop_all_services

    for service_name in "${ALL_SERVICES[@]}"; do
        if contains_service "$service_name" "${requested[@]}"; then
            "${SUDO[@]}" systemctl start "${service_name}.service"
        fi
    done

    # Wants= may pull in an excluded dependency (notably PoseAvoid for
    # PoseTrack). Remove it after all requested services have started.
    for service_name in "${STOP_ORDER[@]}"; do
        if ! contains_service "$service_name" "${requested[@]}"; then
            "${SUDO[@]}" systemctl stop "${service_name}.service"
        fi
    done

    for service_name in "${requested[@]}"; do
        systemctl is-active --quiet "${service_name}.service" || \
            die "Service failed to become active: ${service_name}.service"
    done
}

publish_bool() {
    local topic="$1"
    local value="$2"
    timeout "${ROS_COMMAND_TIMEOUT_SECONDS}s" ros2 topic pub --once \
        --qos-durability transient_local \
        --qos-reliability reliable \
        "$topic" std_msgs/msg/Bool "{data: ${value}}"
}

configure_runtime_flags() {
    local face_enabled="$1"
    local hand_enabled="$2"
    local pose_enabled="$3"

    if systemctl is-active --quiet jc04vision_face.service; then
        publish_bool /face_wave_enabled "$face_enabled"
    fi
    if systemctl is-active --quiet jc04vision_hand.service; then
        publish_bool /hand_wave_enabled "$hand_enabled"
    fi
    if systemctl is-active --quiet jc04vision_PoseTrack.service; then
        publish_bool /pose_follow_enabled "$pose_enabled"
    fi
}

restore_service_state() {
    local state_file="$1"
    local active_services=()
    local service_name state

    [[ -f "$state_file" ]] || return 0
    while IFS=$'\t' read -r service_name state; do
        [[ "$state" == active ]] && active_services+=("$service_name")
    done <"$state_file"

    log "正在恢复测试前的视觉服务状态"
    set_exact_services "${active_services[@]}"
    if (( ${#active_services[@]} > 0 )); then
        sleep "${SERVICE_START_SETTLE_SECONDS:-8}"
    fi
    configure_runtime_flags false false false || true
}

write_service_status() {
    local output_file="$1"
    local service_name
    : >"$output_file"
    for service_name in "${ALL_SERVICES[@]}"; do
        systemctl --no-pager --full status "${service_name}.service" >>"$output_file" 2>&1 || true
    done
}

wait_for_scene() {
    local scene="$1"
    local prompt="${2:-$scene}"
    log "$prompt"
    [[ -n "$scene" ]] || return 0

    log "场景准备说明：$scene"
    local seconds="${SCENE_SETTLE_SECONDS:-10}"
    if [[ "$seconds" =~ ^[0-9]+$ ]] && (( seconds > 0 )); then
        log "场景将在 ${seconds} 秒后自动开始采样，请在倒计时内完成动作，无需按回车确认"
        while (( seconds > 0 )); do
            if (( seconds <= 5 || seconds == ${SCENE_SETTLE_SECONDS:-10} )); then
                log "自动倒计时：${seconds} 秒"
            fi
            sleep 1
            seconds=$((seconds - 1))
        done
    fi
}
