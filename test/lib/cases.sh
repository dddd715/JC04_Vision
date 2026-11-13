#!/usr/bin/env bash

# shellcheck shell=bash

load_case() {
    local case_id="$1"

    CASE_ID="$case_id"
    CASE_WARMUP_SECONDS="${DEFAULT_WARMUP_SECONDS:-120}"
    CASE_SAMPLE_INTERVAL_MS="${DEFAULT_SAMPLE_INTERVAL_MS:-500}"
    CASE_FACE_ENABLED=false
    CASE_HAND_ENABLED=false
    CASE_POSE_ENABLED=false
    CASE_CAPTURE_STARTUP=false
    CASE_SERVICES=()
    CASE_SCENE=""
    CASE_PROMPT=""
    CASE_RESULT_HINT=""

    case "$case_id" in
        T00)
            CASE_TITLE="Robot baseline without vision"
            CASE_DESCRIPTION="Stop all JC04 vision services and measure the robot background load."
            CASE_DURATION_SECONDS=300
            CASE_PROMPT="正在进行机器人后台基线检测，无需操作，请保持设备运行。"
            CASE_RESULT_HINT="输出机器人后台基线的CPU、内存、GPU、功耗和温度。"
            ;;
        T01)
            CASE_TITLE="RealSense camera only"
            CASE_DESCRIPTION="Measure the RealSense driver and ROS image transport load."
            CASE_DURATION_SECONDS=600
            CASE_SERVICES=(camera)
            CASE_PROMPT="正在进行相机检测，请保持相机和视野稳定。"
            CASE_RESULT_HINT="输出RealSense相机和ROS图像传输的资源占用。"
            ;;
        T02)
            CASE_TITLE="Camera and PoseAvoid"
            CASE_DESCRIPTION="Measure aligned depth processing and obstacle detection load."
            CASE_DURATION_SECONDS=600
            CASE_SERVICES=(camera jc04vision_PoseAvoid)
            CASE_SCENE="Keep the center depth ROI clear, then place an obstacle inside 1.2 m for at least 60 seconds."
            CASE_PROMPT="正在进行避障检测，请先保持路径清空，随后在摄像头前方1.2米内放置障碍物。"
            CASE_RESULT_HINT="输出深度处理、避障服务的CPU、内存、GPU和事件率。"
            ;;
        T03)
            CASE_TITLE="Camera and Face"
            CASE_DESCRIPTION="Measure the rec_face ONNX model increment over the camera baseline."
            CASE_DURATION_SECONDS=600
            CASE_SERVICES=(camera jc04vision_face)
            CASE_FACE_ENABLED=true
            CASE_SCENE="Keep one clearly visible face near the center of the RGB image."
            CASE_PROMPT="正在进行人脸识别检测，请站在摄像头前，保持一张清晰人脸。"
            CASE_RESULT_HINT="输出人脸识别服务的资源占用和人脸事件率。"
            ;;
        T04)
            CASE_TITLE="Camera and Hand"
            CASE_DESCRIPTION="Measure the MediaPipe gesture recognizer increment over the camera baseline."
            CASE_DURATION_SECONDS=600
            CASE_SERVICES=(camera jc04vision_hand)
            CASE_HAND_ENABLED=true
            CASE_SCENE="Keep one open hand clearly visible; alternate left/right position once per minute."
            CASE_PROMPT="正在进行手势识别检测，请站在摄像头前展示一只张开的手，并适当左右移动。"
            CASE_RESULT_HINT="输出手势识别服务的资源占用和手势事件率。"
            ;;
        T05)
            CASE_TITLE="Camera and PoseTrack"
            CASE_DESCRIPTION="Measure rec_pose without PoseAvoid. The runner removes the Wanted dependency after PoseTrack starts."
            CASE_DURATION_SECONDS=600
            CASE_SERVICES=(camera jc04vision_PoseTrack)
            CASE_POSE_ENABLED=true
            CASE_SCENE="Keep one full person visible near the center and move left/right at a steady pace."
            CASE_PROMPT="当前正在进行人物跟随，请站在摄像头前进行姿态检测，并缓慢左右移动。"
            CASE_RESULT_HINT="输出人物跟随服务的资源占用和姿态事件率。"
            ;;
        T06)
            CASE_TITLE="Full-stack service startup peak"
            CASE_DESCRIPTION="Start resource collection before all five services to capture model-load CPU and memory peaks."
            CASE_DURATION_SECONDS=300
            CASE_WARMUP_SECONDS=0
            CASE_CAPTURE_STARTUP=true
            CASE_SERVICES=(camera jc04vision_face jc04vision_hand jc04vision_PoseAvoid jc04vision_PoseTrack)
            CASE_PROMPT="正在进行视觉服务启动峰值检测，请保持设备和摄像头稳定，系统将自动启动全部视觉服务。"
            CASE_RESULT_HINT="输出全部视觉服务启动阶段的CPU和内存峰值。"
            ;;
        T10)
            CASE_TITLE="Full stack standby"
            CASE_DESCRIPTION="Start all services while Face, Hand, and PoseTrack remain disabled; PoseAvoid stays active by design."
            CASE_DURATION_SECONDS=600
            CASE_SERVICES=(camera jc04vision_face jc04vision_hand jc04vision_PoseAvoid jc04vision_PoseTrack)
            CASE_PROMPT="正在进行生产待机检测，请保持摄像头视野为空，无需启用人脸、手势和人物跟随。"
            CASE_RESULT_HINT="输出生产待机状态下全部视觉服务的资源占用。"
            ;;
        T11)
            CASE_TITLE="Full stack enabled without targets"
            CASE_DESCRIPTION="Enable all visual functions with no person, face, hand, or near obstacle in view."
            CASE_DURATION_SECONDS=900
            CASE_SERVICES=(camera jc04vision_face jc04vision_hand jc04vision_PoseAvoid jc04vision_PoseTrack)
            CASE_FACE_ENABLED=true
            CASE_HAND_ENABLED=true
            CASE_POSE_ENABLED=true
            CASE_SCENE="Use an empty scene with no person, face, hand, or obstacle within 1.2 m."
            CASE_PROMPT="正在进行全功能空场景检测，请离开摄像头视野，并移除近距离障碍物。"
            CASE_RESULT_HINT="输出全功能启用但没有检测目标时的资源占用。"
            ;;
        T12)
            CASE_TITLE="Full stack typical workload"
            CASE_DESCRIPTION="Run the production combination with one person, one hand, and a clear/obstacle depth sequence."
            CASE_DURATION_SECONDS=1800
            CASE_SERVICES=(camera jc04vision_face jc04vision_hand jc04vision_PoseAvoid jc04vision_PoseTrack)
            CASE_FACE_ENABLED=true
            CASE_HAND_ENABLED=true
            CASE_POSE_ENABLED=true
            CASE_SCENE="Use one person facing the camera. Show one open hand periodically and alternate clear path/obstacle every five minutes."
            CASE_PROMPT="正在进行典型工况检测，请安排一人站在摄像头前，周期性展示一只手，并按提示切换清空/障碍路径。"
            CASE_RESULT_HINT="输出典型生产工况的资源指标、温度、功耗和稳定性结论。"
            ;;
        T13)
            CASE_TITLE="Full stack stress workload"
            CASE_DESCRIPTION="Run all visual functions with a complex scene intended to maximize post-processing load."
            CASE_DURATION_SECONDS=1800
            CASE_SERVICES=(camera jc04vision_face jc04vision_hand jc04vision_PoseAvoid jc04vision_PoseTrack)
            CASE_FACE_ENABLED=true
            CASE_HAND_ENABLED=true
            CASE_POSE_ENABLED=true
            CASE_SCENE="Use multiple visible people, up to two hands, and repeated near-obstacle transitions without covering the camera."
            CASE_PROMPT="正在进行压力工况检测，请安排多人或双手进入视野，并反复进行近距离障碍切换。"
            CASE_RESULT_HINT="输出复杂场景下的资源峰值、服务重启和稳定性结论。"
            ;;
        T14)
            CASE_TITLE="Two-hour full-stack endurance"
            CASE_DESCRIPTION="Run the production visual combination for two hours to detect memory growth, restarts, and thermal issues."
            CASE_DURATION_SECONDS=7200
            CASE_SAMPLE_INTERVAL_MS="${LONG_SAMPLE_INTERVAL_MS:-1000}"
            CASE_SERVICES=(camera jc04vision_face jc04vision_hand jc04vision_PoseAvoid jc04vision_PoseTrack)
            CASE_FACE_ENABLED=true
            CASE_HAND_ENABLED=true
            CASE_POSE_ENABLED=true
            CASE_SCENE="Maintain the typical T12 scene and repeat its clear/obstacle sequence throughout the run."
            CASE_PROMPT="正在进行两小时长稳检测，请维持典型工况并按提示重复清空/障碍切换。"
            CASE_RESULT_HINT="输出长时间内存增长、温度、功耗和服务稳定性。"
            ;;
        T15)
            CASE_TITLE="Eight-hour full-stack endurance"
            CASE_DESCRIPTION="Run the production visual combination for eight hours on a representative board."
            CASE_DURATION_SECONDS=28800
            CASE_SAMPLE_INTERVAL_MS="${LONG_SAMPLE_INTERVAL_MS:-1000}"
            CASE_SERVICES=(camera jc04vision_face jc04vision_hand jc04vision_PoseAvoid jc04vision_PoseTrack)
            CASE_FACE_ENABLED=true
            CASE_HAND_ENABLED=true
            CASE_POSE_ENABLED=true
            CASE_SCENE="Maintain the typical T12 scene and record any operator scene changes in notes.txt."
            CASE_PROMPT="正在进行八小时长稳检测，请维持典型工况并记录场景变化。"
            CASE_RESULT_HINT="输出最终长时间运行的内存增长、温度、功耗和稳定性。"
            ;;
        *)
            printf 'Unknown case: %s\n' "$case_id" >&2
            return 2
            ;;
    esac

    CASE_DURATION_SECONDS="${DURATION_SECONDS:-$CASE_DURATION_SECONDS}"
    CASE_WARMUP_SECONDS="${WARMUP_SECONDS:-$CASE_WARMUP_SECONDS}"
    CASE_SAMPLE_INTERVAL_MS="${SAMPLE_INTERVAL_MS:-$CASE_SAMPLE_INTERVAL_MS}"
}

case_service_csv() {
    local IFS=,
    printf '%s' "${CASE_SERVICES[*]}"
}
