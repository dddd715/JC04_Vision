"""
检测障碍物并发布 obstacle_detected 布尔信号
tag:
    v2版更简洁
"""

from typing import Optional

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Bool

GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
RESET = "\033[0m"


class AvoidNode(Node):
    def __init__(self):
        super().__init__("avoid_node")

        self.bridge = CvBridge()
        self.kernel = np.ones((3, 3), np.uint8)

        self.depth_topic = "/camera/camera/aligned_depth_to_color/image_raw"
        self.obstacle_detected_topic = "/obstacle_detected"

        self.stop_distance = 1.2
        self.roi_vertical_shift_ratio = 0.25
        self.roi_width_ratio = 0.40
        self.roi_height_ratio = 0.25
        self.min_valid_depth = 0.10
        self.max_valid_depth = 3.50
        self.depth_stat = "median"
        self.publish_zero_on_no_depth = True

        self.latest_depth_frame = None
        self.latest_depth_encoding = None
        self.obstacle_detected = False
        self.last_stop_state = None
        self.last_obstacle_detected_output = None

        self.obstacle_detected_pub = self.create_publisher(Bool, self.obstacle_detected_topic, 20)
        self.depth_subscription = self.create_subscription(
            Image,
            self.depth_topic,
            self.depth_callback,
            10,
        )

        self.get_logger().info(f"{GREEN}Avoid node started{RESET}")

    def depth_callback(self, msg: Image):
        self.latest_depth_encoding = msg.encoding
        self.latest_depth_frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
        self.evaluate_obstacle()

    def distance(self, depth_image: np.ndarray) -> Optional[float]:
        if depth_image is None or depth_image.size == 0:
            return None

        if depth_image.ndim != 2:
            return None

        depth_meters = self.depth_to_meters(depth_image, self.latest_depth_encoding)
        if depth_meters is None:
            return None

        depth_meters = self.filter_depth_noise(depth_meters)

        height, width = depth_meters.shape
        roi_w = max(1, int(width * self.roi_width_ratio))
        roi_h = max(1, int(height * self.roi_height_ratio))
        #深度信息阈值区间y轴
        center_y = int(height * (0.5 + self.roi_vertical_shift_ratio)) 
        y1 = max(0, center_y - roi_h // 2)
        x1 = max(0, (width - roi_w) // 2)
        
        x2 = min(width, x1 + roi_w)
        y2 = min(height, y1 + roi_h)

        roi = depth_meters[y1:y2, x1:x2]
        if roi.size == 0:
            return None

        valid_mask = np.isfinite(roi)
        valid_mask &= roi >= self.min_valid_depth
        valid_mask &= roi <= self.max_valid_depth
        valid_depths = roi[valid_mask]

        if valid_depths.size == 0:
            return None

        return float(np.median(valid_depths))

    def filter_depth_noise(self, depth_meters: np.ndarray) -> np.ndarray:
        valid_mask = np.isfinite(depth_meters)
        valid_mask &= depth_meters >= self.min_valid_depth
        valid_mask &= depth_meters <= self.max_valid_depth

        mask_uint8 = (valid_mask.astype(np.uint8)) * 255

        opened_mask = cv2.morphologyEx(mask_uint8, cv2.MORPH_OPEN, self.kernel)
        filtered_mask = cv2.morphologyEx(opened_mask, cv2.MORPH_CLOSE, self.kernel)

        filtered_depth = depth_meters.copy()
        filtered_depth[filtered_mask == 0] = np.nan
        return filtered_depth

    def depth_to_meters(self, depth_image: np.ndarray, encoding: Optional[str]) -> Optional[np.ndarray]:
        if encoding is None:
            return None

        if encoding == "16UC1":
            return depth_image.astype(np.float32) / 1000.0

        if encoding == "32FC1":
            return depth_image.astype(np.float32)

        self.get_logger().warning(f"Unsupported depth encoding: {encoding}")
        return None

    def evaluate_obstacle(self):
        if self.latest_depth_frame is None:
            return

        obstacle_distance = self.distance(self.latest_depth_frame)

        if obstacle_distance is None:
            if self.publish_zero_on_no_depth:
                self.obstacle_detected = True
                self.publish_obstacle_detected()
                print(f"{YELLOW}No valid depth data, publish obstacle_detected=True{RESET}")
            return

        if obstacle_distance < self.stop_distance:
            self.obstacle_detected = True
            self.publish_obstacle_detected()
            print("stop",
                f"{YELLOW}Obstacle detected: distance={obstacle_distance:.3f}m < {self.stop_distance:.3f}m, publish obstacle_detected=True{RESET}",
            )
        else:
            self.obstacle_detected = False
            self.publish_obstacle_detected()
            print("clear",
                f"{GREEN}Path clear: distance={obstacle_distance:.3f}m >= {self.stop_distance:.3f}m, publish obstacle_detected=False{RESET}",
            )

    def publish_obstacle_detected(self):
        if self.last_obstacle_detected_output == self.obstacle_detected:
            return

        self.last_obstacle_detected_output = self.obstacle_detected
        sign_msg = Bool()
        sign_msg.data = self.obstacle_detected
        self.obstacle_detected_pub.publish(sign_msg)
        self.get_logger().info(
            f"{BLUE}publish obstacle_detected: {sign_msg.data}{RESET}"
        )

def main(args=None):
    rclpy.init(args=args)
    node = AvoidNode()
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
