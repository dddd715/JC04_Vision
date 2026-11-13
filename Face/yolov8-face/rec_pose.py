"""
检测pose姿态进行跟随
"""

import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import rclpy
import torch
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import Image
from std_msgs.msg import String
from std_msgs.msg import Bool
from ultralytics import YOLO

os.environ["YOLO_VERBOSE"] = "False"
warnings.filterwarnings("ignore")

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from ControllerAll import VelocityController

GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
RESET = "\033[0m"

class PoseTrackDetector:
    def __init__(
        self,
        model: YOLO,
        device: str,
        tracker: str = "bytetrack.yaml",
        smooth_alpha: float = 0.4,
        max_jump: float = 60.0,
    ):
        self.model = model
        self.device = device
        self.tracker = tracker
        self.smooth_alpha = smooth_alpha
        self.max_jump = max_jump
        self.last_points = {}

    def predict(self, frame):
        A =  self.model.track(
            source=frame,
            device=self.device,
            tracker=self.tracker,
            persist=True,
            conf=0.3,
            iou=0.4,
            classes=[0],
            verbose=False,
        )
        return A

    def compute_hip_midpoint(self, keypoints_xy, keypoints_conf):
        left_point = keypoints_xy[11]
        right_point = keypoints_xy[12]
        left_conf = float(keypoints_conf[11])
        right_conf = float(keypoints_conf[12])

        left_valid = left_conf > 0.5
        right_valid = right_conf > 0.5

        if left_valid and right_valid:
            return (
                float((left_point[0] + right_point[0]) / 2.0),
                float((left_point[1] + right_point[1]) / 2.0),
            )

        return None

    def smooth_follow_point(self, current_point, prev_point):
        if prev_point is None:
            return current_point

        delta = np.array(current_point) - np.array(prev_point)
        distance = float(np.linalg.norm(delta))

        if distance > self.max_jump and distance > 1e-6:
            scale = self.max_jump / distance
            limited_point = (
                prev_point[0] + delta[0] * scale,
                prev_point[1] + delta[1] * scale,
            )
            return (float(limited_point[0]), float(limited_point[1]))

        return (
            float(self.smooth_alpha * current_point[0] + (1.0 - self.smooth_alpha) * prev_point[0]),
            float(self.smooth_alpha * current_point[1] + (1.0 - self.smooth_alpha) * prev_point[1]),
        )

    def extract_target(self, results, target_track_id=None, min_area=0.0, center_region=None):
        if not results:
            return None

        result = results[0]
        if result.boxes is None or len(result.boxes) == 0 or result.keypoints is None:
            return None

        boxes_xyxy = result.boxes.xyxy.cpu().numpy()
        confidences = result.boxes.conf.cpu().numpy()
        keypoints_xy = result.keypoints.xy.cpu().numpy()
        keypoints_conf = result.keypoints.conf.cpu().numpy()
        if result.boxes.is_track and result.boxes.id is not None:
            track_ids = result.boxes.id.int().cpu().tolist()
        else:
            track_ids = list(range(len(boxes_xyxy)))

        best_target = None
        best_area = -1.0

        for index, track_id in enumerate(track_ids):
            x1, y1, x2, y2 = boxes_xyxy[index]
            area = float(max(0.0, x2 - x1) * max(0.0, y2 - y1))
            if area <= 0.0:
                continue
            if target_track_id is not None and int(track_id) != int(target_track_id):
                continue
            if area < float(min_area):
                continue

            hip_point = self.compute_hip_midpoint(keypoints_xy[index], keypoints_conf[index])
            bbox_center = (
                float((x1 + x2) / 2.0),
                float((y1 + y2) / 2.0),
            )
            follow_point = hip_point if hip_point is not None else bbox_center
            prev_point = self.last_points.get(track_id)

            follow_point = self.smooth_follow_point(follow_point, prev_point)

            self.last_points[track_id] = follow_point

            if center_region is not None:
                x_min, y_min, x_max, y_max = center_region
                if not (x_min <= follow_point[0] <= x_max and y_min <= follow_point[1] <= y_max):
                    continue

            if area > best_area:
                best_area = area
                best_target = {
                    "track_id": int(track_id),
                    "follow_point": follow_point,
                    "hip_point": hip_point,
                    "bbox_center": bbox_center,
                    "point_source": "hip" if hip_point is not None else "bbox",
                    "bbox": (int(x1), int(y1), int(x2), int(y2)),
                    "area": area,
                    "conf": float(confidences[index]),
                }

        return best_target

class PoseDetectPublisher(Node):
    def __init__(self):
        super().__init__("pose_detect_publisher")

        self.bridge = CvBridge()
        self.weight_path = "./weight/yolo26n-pose.onnx"
        self.device = "0"
        self.model = YOLO(str(self.weight_path), task="pose")
        self.detect_interval = 0.10
        self.last_detect_time = 0.0
        self.forward_speed = 0.8
        self.turn_speed = 0.5
        # 保持跟随连贯性：普通方向修正不应让机器人从 0.8m/s 降到 0.6m/s。
        self.turn_correction_linear_speed = 0.6
        self.large_turn_linear_speed = 0.4
        # 转向采用角度滞回，避免髋部中心在画面中周期性摆动时频繁切换方向。
        self.turn_exit_angle_deg = 3.0
        self.turn_enter_angle_deg = 6.0
        self.large_turn_angle_deg = 20.0
        self.turn_confirm_frames = 3
        self.tracking_action = "F"
        self.pending_turn_action = None
        self.pending_turn_frames = 0
        # 首次锁定时保留中心区域约束，避免误锁，但不要求目标过于靠近相机。
        self.min_target_area_ratio = 0.2
        self.acquire_center_ratio = 0.3
        self.locked_track_id = None
        self.lost_frame_count = 0.0
        self.max_lost_frames = 10
        self.obstacle_detected_topic = "/obstacle_detected"
        self.declare_parameter("camera_topic", "/camera/camera/color/image_raw")
        self.declare_parameter("enable_topic", "/pose_follow_enabled")
        self.camera_topic = self.get_parameter("camera_topic").value
        self.enable_topic = self.get_parameter("enable_topic").value
        self.camera_timeout = 0.75
        self.follow_enabled = False
        self.camera_active = False
        self.last_image_time = 0.0
        self.image_subscription = None

        self.pose_detector = PoseTrackDetector(self.model, self.device)

        self.controller = VelocityController(
            node=self,
            cmd_vel_topic="/cmd_vel",
            forward_speed=self.forward_speed,
            turn_speed=self.turn_speed,
            turn_correction_linear_speed=self.turn_correction_linear_speed,
            large_turn_linear_speed=self.large_turn_linear_speed,
            turn_deadband_angle_deg=self.turn_exit_angle_deg,
            large_turn_angle_deg=self.large_turn_angle_deg,
            initially_enabled=False,
        )
        enable_qos = QoSProfile(depth=1)
        enable_qos.reliability = QoSReliabilityPolicy.RELIABLE
        enable_qos.durability = QoSDurabilityPolicy.TRANSIENT_LOCAL
        self.output_pub = self.create_publisher(String, "/output_msg", 20)
        self.image_pub = self.create_publisher(Image, "/pose_detect/image", 20)
        self.enable_subscription = self.create_subscription(
            Bool,
            self.enable_topic,
            self.enable_callback,
            enable_qos,
        )
        self.obstacle_subscription = self.create_subscription(
            Bool,
            self.obstacle_detected_topic,
            self.obstacle_callback,
            10,
        )
        self.camera_watchdog_timer = self.create_timer(0.2, self.camera_watchdog_callback)

        print(f"{GREEN}Loaded pose model: {self.weight_path}{RESET}")
        print(f"{GREEN}Running on device: {self.device}{RESET}")
        print(f"{GREEN}Subscribed obstacle topic: {self.obstacle_detected_topic}{RESET}")
        print(f"{GREEN}Subscribed enable topic: {self.enable_topic}{RESET}")
        print(f"{GREEN}Camera topic: {self.camera_topic}{RESET}")
        print(f"{GREEN}Pose follow is disabled until enable topic publishes true{RESET}")

    def enable_callback(self, msg: Bool):
        enabled = bool(msg.data)
        if enabled == self.follow_enabled:
            return

        self.follow_enabled = enabled
        self.last_detect_time = 0.0
        if self.follow_enabled:
            self.start_camera_subscription()
            print(f"{GREEN}Pose follow enabled, camera subscription started{RESET}")
        else:
            self.locked_track_id = None
            self.lost_frame_count = 0.0
            self.reset_turn_state()
            self.camera_active = False
            self.stop_camera_subscription()
            self.controller.stop()
            print(f"{YELLOW}Pose follow disabled, camera subscription stopped{RESET}")
        self.update_controller_enabled()

    def start_camera_subscription(self):
        if self.image_subscription is not None:
            return

        self.image_subscription = self.create_subscription(
            Image,
            self.camera_topic,
            self.image_callback,
            10,
        )

    def stop_camera_subscription(self):
        if self.image_subscription is None:
            return

        self.destroy_subscription(self.image_subscription)
        self.image_subscription = None

    def obstacle_callback(self, msg: Bool):
        self.controller.set_obstacle_detected(msg.data)

    def camera_watchdog_callback(self):
        if not self.camera_active:
            return

        if time.time() - self.last_image_time <= self.camera_timeout:
            return

        self.camera_active = False
        print(f"{YELLOW}Camera image timeout, disable vision cmd_vel publishing{RESET}")
        self.update_controller_enabled()

    def update_controller_enabled(self):
        self.controller.set_enabled(self.follow_enabled and self.camera_active)

    def get_center_region(self, frame_width, frame_height):
        center_width = frame_width * self.acquire_center_ratio
        x_min = int((frame_width - center_width) / 2.0)
        x_max = int((frame_width + center_width) / 2.0)
        return (x_min, 0, x_max, frame_height)

    def reset_turn_state(self):
        """清除转向确认计数，下一次检测从正常前进状态开始。"""
        self.tracking_action = "F"
        self.pending_turn_action = None
        self.pending_turn_frames = 0

    def update_turn_state(self, offset_x, frame_width):
        """根据航向误差更新带滞回和连续帧确认的 F/L/R 状态。"""
        heading_error_deg = self.controller.horizontal_offset_to_angle_deg(
            offset_x,
            frame_width,
        )
        if heading_error_deg is None:
            self.reset_turn_state()
            return "C", None

        # 误差回到 3 度以内时立即退出转向，恢复正常前进。
        if heading_error_deg <= self.turn_exit_angle_deg:
            self.reset_turn_state()
            return self.tracking_action, heading_error_deg

        # 3~6 度是滞回区：保持上一个已确认状态，并中断连续越界计数。
        if heading_error_deg <= self.turn_enter_angle_deg:
            self.pending_turn_action = None
            self.pending_turn_frames = 0
            return self.tracking_action, heading_error_deg

        requested_action = "R" if offset_x > 0.0 else "L"

        # 已经处于正确转向状态时无需重新累计确认帧。
        if requested_action == self.tracking_action:
            self.pending_turn_action = None
            self.pending_turn_frames = 0
            return self.tracking_action, heading_error_deg

        # 只有同一方向连续 3 个检测帧超过 6 度，才进入或切换转向状态。
        if requested_action == self.pending_turn_action:
            self.pending_turn_frames += 1
        else:
            self.pending_turn_action = requested_action
            self.pending_turn_frames = 1

        if self.pending_turn_frames >= self.turn_confirm_frames:
            self.tracking_action = requested_action
            self.pending_turn_action = None
            self.pending_turn_frames = 0

        return self.tracking_action, heading_error_deg

    def handle_track(self, track_id, hip_point, frame_width, frame_height):
        hip_x, hip_y = hip_point

        if hip_x < 0 or hip_y < 0 or hip_x >= frame_width or hip_y >= frame_height:
            print(f"{YELLOW}track_id={track_id} C hip=({hip_x:.1f}, {hip_y:.1f}){RESET}")
            self.reset_turn_state()
            return "C"

        screen_mid_x = frame_width / 2.0
        offset_x = hip_x - screen_mid_x
        action, heading_error_deg = self.update_turn_state(offset_x, frame_width)
        angle_text = "invalid" if heading_error_deg is None else f"{heading_error_deg:.1f}deg"
        color = GREEN if action == "F" else BLUE
        print(
            f"{color}track_id={track_id} {action} hip=({hip_x:.1f}, {hip_y:.1f}) "
            f"error={angle_text} pending={self.pending_turn_action}:"
            f"{self.pending_turn_frames}/{self.turn_confirm_frames}{RESET}"
        )
        return action

    def controller_sign(self, action, horizontal_offset_px, image_width):
        self.controller.controller_sign(action, horizontal_offset_px, image_width)

    def image_callback(self, msg: Image):
        if not self.follow_enabled:
            return

        now = time.time()
        self.last_image_time = now
        if not self.camera_active:
            self.camera_active = True
            self.update_controller_enabled()

        if now - self.last_detect_time < self.detect_interval:
            return
        self.last_detect_time = now

        frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        frame_height, frame_width = frame.shape[:2]
        min_target_area = frame_width * frame_height * self.min_target_area_ratio
        center_region = self.get_center_region(frame_width, frame_height)

        results = self.pose_detector.predict(frame)
        target = None

        # 锁定track_id目标
        if self.locked_track_id is not None:
            target = self.pose_detector.extract_target(
                results,
                target_track_id=self.locked_track_id,
                min_area=0.0,
            )
            if target is None:
                self.lost_frame_count += 1
                print(
                    f"{YELLOW}暂时未检测到锁定目标 track_id={self.locked_track_id} "
                    f"({self.lost_frame_count}/{self.max_lost_frames}){RESET}"
                )
                if self.lost_frame_count >= self.max_lost_frames:
                    print(f"{YELLOW}连续丢失过久，清除锁定目标 track_id={self.locked_track_id}{RESET}")
                    self.locked_track_id = None
                    self.lost_frame_count = 0
            else:
                self.lost_frame_count = 0

        if self.locked_track_id is None:
            target = self.pose_detector.extract_target(
                results,
                target_track_id=None,
                min_area=min_target_area,
                center_region=center_region,
            )
            if target is not None:
                # 新目标不能继承上一目标的转向方向和连续帧计数。
                self.reset_turn_state()
                self.locked_track_id = target["track_id"]
                self.lost_frame_count = 0
                print(
                    f"{GREEN}锁定目标 track_id={self.locked_track_id} "
                    f"center_region={center_region} area={target['area']:.1f}{RESET}"
                )

        if target is None:
            print(
                f"{YELLOW}未检测到可靠的人体髋部目标中心"
                f"(locked_track_id={self.locked_track_id}, min_area={min_target_area:.0f}){RESET}"
            )
            self.reset_turn_state()
            self.controller.stop()
            return

        follow_x, follow_y = target["follow_point"]
        action = self.handle_track(target["track_id"], target["follow_point"], frame_width, frame_height)
        self.controller_sign(action, follow_x - frame_width / 2.0, frame_width)
        output_msg = String()
        output_msg.data = f"{int(round(follow_x))},{int(round(follow_y))}"
        self.output_pub.publish(output_msg)

        print(
            f"{BLUE}target track_id={target['track_id']} "
            f"bbox={target['bbox']} point=({follow_x:.1f}, {follow_y:.1f}) "
            f"source={target['point_source']} area={target['area']:.1f}{RESET}"
        )
    
def main(args=None):
    rclpy.init(args=args)
    node = PoseDetectPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
