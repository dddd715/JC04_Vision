#!/usr/bin/env bash
# Install all JC04 vision services on a production device.

set -Eeuo pipefail

readonly JC04_ROOT="/home/nvidia/JC04"
readonly VISION_ROOT="/home/nvidia/JC04_Vision"
readonly SERVICE_SOURCE_DIR="${VISION_ROOT}/start_stop/service_files"
readonly SERVICE_TARGET_DIR="/etc/systemd/system"
readonly UNIT_NAMES=(camera jc04vision_face jc04vision_hand jc04vision_PoseAvoid jc04vision_PoseTrack)
readonly BOOT_SERVICE_NAMES=(camera jc04vision_face jc04vision_hand jc04vision_PoseAvoid jc04vision_PoseTrack)


fail() {
    printf 'FAILED: %s\n' "$1" >&2
    exit 1
}

check_file() {
    local label="$1"
    local path="$2"
    if [[ -f "$path" ]]; then
        printf 'OK: %s\n' "$label"
    else
        fail "${label} is missing: ${path}"
    fi
}

check_executable() {
    local label="$1"
    local path="$2"
    if [[ -x "$path" ]]; then
        printf 'OK: %s\n' "$label"
    else
        fail "${label} is not executable: ${path}"
    fi
}

source_ros_environment() {
    # ROS setup scripts reference optional variables that may be unset.
    set +u
    source /opt/ros/humble/setup.bash
    source "${JC04_ROOT}/JC04Dev/install/setup.bash"
    set -u
}

printf '=== JC04 Vision service installation ===\n'
check_file 'ROS 2 Humble environment' '/opt/ros/humble/setup.bash'
check_file 'JC04 ROS workspace' "${JC04_ROOT}/JC04Dev/install/setup.bash"
check_file 'Face recognition program' "${VISION_ROOT}/Face/yolov8-face/rec_face.py"
check_file 'Face model' "${VISION_ROOT}/Face/yolov8-face/weight/yolov8n-face.onnx"
check_file 'Hand recognition program' "${VISION_ROOT}/Hand/Mediapipe_rec.py"
check_file 'Pose avoid program' "${VISION_ROOT}/Face/yolov8-face/PoseAvoid.py"
check_file 'Pose track program' "${VISION_ROOT}/Face/yolov8-face/rec_pose.py"
check_file 'MediaPipe gesture model' "${VISION_ROOT}/Hand/models/gesture_recognizer.task"
check_executable 'Camera startup script' '/home/nvidia/bin/jcbot_data_camera.sh'
check_executable 'MediaPipe Python environment' "${VISION_ROOT}/Hand/env-mediapipe/bin/python3"
check_executable 'Face startup script' "${VISION_ROOT}/start_stop/jc04vision_face.sh"
check_executable 'Hand startup script' "${VISION_ROOT}/start_stop/jc04vision_hand.sh"
check_executable 'Pose avoid startup script' "${VISION_ROOT}/start_stop/jc04vision_PoseAvoid.sh"
check_executable 'Pose track startup script' "${VISION_ROOT}/start_stop/jc04vision_PoseTrack.sh"

printf 'Checking Face Python dependencies...\n'
(
    source_ros_environment
    cd "${VISION_ROOT}/Face/yolov8-face"
    /usr/bin/python3 -c 'import cv2, rclpy, torch; from cv_bridge import CvBridge; from ultralytics import YOLO; print("OK: Face Python dependencies")'
) || fail 'Face Python dependency check failed'

printf 'Checking Hand Python dependencies...\n'
(
    source_ros_environment
    cd "${VISION_ROOT}/Hand"
    ./env-mediapipe/bin/python3 -c 'import cv2, mediapipe, rclpy; from cv_bridge import CvBridge; from mediapipe.tasks.python import vision; print("OK: Hand Python dependencies")'
) || fail 'Hand Python dependency check failed'

for service_name in "${UNIT_NAMES[@]}"; do
    check_file "${service_name}.service source" "${SERVICE_SOURCE_DIR}/${service_name}.service"
done

printf 'Installing systemd service files...\n'
for service_name in "${UNIT_NAMES[@]}"; do
    sudo install -m 0644 "${SERVICE_SOURCE_DIR}/${service_name}.service" "${SERVICE_TARGET_DIR}/${service_name}.service"
done

sudo systemctl daemon-reload
printf 'Enabling and starting all vision services...\n'
for service_name in "${BOOT_SERVICE_NAMES[@]}"; do
    sudo systemctl enable --now "${service_name}.service"
done

printf '=== Installation result ===\n'
for service_name in "${BOOT_SERVICE_NAMES[@]}"; do
    if sudo systemctl is-enabled --quiet "${service_name}.service"; then
        printf 'OK: %s.service starts at boot\n' "$service_name"
    else
        fail "${service_name}.service is not enabled"
    fi

    if sudo systemctl is-active --quiet "${service_name}.service"; then
        printf 'OK: %s.service is active\n' "$service_name"
    else
        sudo systemctl --no-pager --full status "${service_name}.service" || true
        fail "${service_name}.service did not start"
    fi
done

printf 'SUCCESS: JC04 Vision services are installed and enabled at boot.\n'
