#!/usr/bin/env bash

set -Eeuo pipefail

if (( $# != 1 )); then
    printf 'Usage: %s OUTPUT_DIR\n' "$0" >&2
    exit 2
fi

OUTPUT_DIR="$1"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
mkdir -p "$OUTPUT_DIR"

manifest="$OUTPUT_DIR/manifest.tsv"
environment="$OUTPUT_DIR/environment.txt"
: >"$manifest"
: >"$environment"

manifest_value() {
    local key="$1"
    local value="$2"
    value="${value//$'\t'/ }"
    value="${value//$'\n'/ }"
    printf '%s\t%s\n' "$key" "$value" >>"$manifest"
}

section() {
    printf '\n## %s\n' "$1" >>"$environment"
}

run_capture() {
    printf '$ %s\n' "$*" >>"$environment"
    "$@" >>"$environment" 2>&1 || true
}

board_model="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || printf 'unknown')"
l4t_release="$(head -n 1 /etc/nv_tegra_release 2>/dev/null || printf 'unknown')"
os_pretty="$(. /etc/os-release 2>/dev/null && printf '%s' "${PRETTY_NAME:-unknown}" || printf 'unknown')"
git_commit="$(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null || printf 'unknown')"
git_dirty=no
[[ -n "$(git -C "$PROJECT_ROOT" status --porcelain 2>/dev/null || true)" ]] && git_dirty=yes
nvpmodel_mode="$(nvpmodel -q 2>/dev/null | tr '\n' ' ' || printf 'unknown')"

manifest_value collected_at "$(date --iso-8601=seconds)"
manifest_value hostname "$(hostname)"
manifest_value board_model "$board_model"
manifest_value l4t_release "$l4t_release"
manifest_value os "$os_pretty"
manifest_value kernel "$(uname -r)"
manifest_value architecture "$(uname -m)"
manifest_value cpu_count "$(nproc)"
manifest_value memory_total_mb "$(awk '/MemTotal:/ {printf "%.0f", $2 / 1024}' /proc/meminfo)"
manifest_value nvpmodel "$nvpmodel_mode"
manifest_value git_commit "$git_commit"
manifest_value git_dirty "$git_dirty"
manifest_value ros_distro "${ROS_DISTRO:-unknown}"
manifest_value ros_domain_id "${ROS_DOMAIN_ID:-0}"
manifest_value expected_camera_resolution "${EXPECTED_CAMERA_RESOLUTION:-unknown}"
manifest_value expected_camera_fps "${EXPECTED_CAMERA_FPS:-unknown}"

section "Platform"
run_capture uname -a
run_capture lscpu
run_capture free -h
run_capture df -h /
run_capture nvpmodel -q
if command -v jetson_clocks >/dev/null 2>&1; then
    if (( EUID == 0 )); then
        run_capture jetson_clocks --show
    else
        run_capture sudo -n jetson_clocks --show
    fi
fi
run_capture sh -c 'for zone in /sys/class/thermal/thermal_zone*; do printf "%s " "$(cat "$zone/type" 2>/dev/null)"; cat "$zone/temp" 2>/dev/null; done'

section "Software"
run_capture git -C "$PROJECT_ROOT" status --short --branch
run_capture python3 --version
run_capture dpkg-query -W nvidia-jetpack nvidia-l4t-core ros-humble-ros-base ros-humble-rclpy
run_capture /usr/bin/python3 -c 'import cv2; print("opencv", cv2.__version__)'
run_capture /usr/bin/python3 -c 'import torch; print("torch", torch.__version__); print("cuda_available", torch.cuda.is_available())'
run_capture /usr/bin/python3 -c 'import onnxruntime as ort; print("onnxruntime", ort.__version__); print("providers", ort.get_available_providers())'

section "Model hashes"
find "$PROJECT_ROOT/Face" "$PROJECT_ROOT/Hand/models" -type f \
    \( -name '*.onnx' -o -name '*.task' \) -print0 2>/dev/null \
    | sort -z \
    | xargs -0 -r sha256sum >>"$environment" 2>&1 || true

section "RealSense"
if command -v rs-enumerate-devices >/dev/null 2>&1; then
    run_capture rs-enumerate-devices -s
else
    printf 'rs-enumerate-devices not installed\n' >>"$environment"
fi
run_capture lsusb

section "Vision services"
for service_name in camera jc04vision_face jc04vision_hand jc04vision_PoseAvoid jc04vision_PoseTrack; do
    run_capture systemctl show "${service_name}.service" \
        -p Id -p ActiveState -p SubState -p MainPID -p NRestarts \
        -p ExecMainStartTimestamp -p MemoryCurrent -p CPUUsageNSec
done
