"""
检测人脸挥手
"""

import os
os.environ["YOLO_VERBOSE"] = "False"

import warnings
warnings.filterwarnings("ignore")

import cv2
import rclpy
import torch
import time
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import Image
from std_msgs.msg import Bool
from std_msgs.msg import String
from ultralytics import YOLO

RED     = "\033[31m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
BLUE    = "\033[34m"
RESET   = "\033[0m"

class FaceDetectPublisher(Node):
    def __init__(self):
        super().__init__("face_detect_publisher")

        self.publisher_ = self.create_publisher(String, "/jc04_wave_sign", 50)  
        self.image_pub = self.create_publisher(Image, "/face_detect/image", 50)
        self.output_data = "left"
        self.bridge = CvBridge()
        self.declare_parameter("camera_topic", "/camera/camera/color/image_raw")
        self.declare_parameter("enable_topic", "/face_wave_enabled")
        self.camera_topic = self.get_parameter("camera_topic").value
        self.enable_topic = self.get_parameter("enable_topic").value
        self.face_wave_enabled = False
        self.image_subscription = None
        enable_qos = QoSProfile(depth=1)
        enable_qos.reliability = QoSReliabilityPolicy.RELIABLE
        enable_qos.durability = QoSDurabilityPolicy.TRANSIENT_LOCAL
        self.enable_subscription = self.create_subscription(
            Bool,
            self.enable_topic,
            self.enable_callback,
            enable_qos,
        )
        # 间隔
        self.last_detect_time = 0.0      
        self.detect_interval = 5.0
        

        self.weight_path = "./weight/yolov8n-face.onnx"
        self.device = "0"
        # This legacy face-keypoint ONNX does not contain task metadata.
        self.model = YOLO(str(self.weight_path), task="pose")

        self.kpt_colors = [
            (255, 0, 0),
            (255, 0, 0),
            (0, 0, 255),
            (255, 255, 0),
            (255, 255, 0),
        ]
        print(f"{GREEN}Loaded model: {self.weight_path}{RESET}")
        print(f"{GREEN}Running on device: {self.device}{RESET}")
        # print(f"{RED}错误信息{RESET}")
        # print(f"{YELLOW}警告信息{RESET}")

        self.get_logger().info(f"Camera topic: {self.camera_topic}")
        self.get_logger().info(f"Enable topic: {self.enable_topic}")
        self.get_logger().info("Face wave is disabled until enable topic publishes true")
        self.get_logger().info("Publishing wave commands to /jc04_wave_sign")

    def enable_callback(self, msg: Bool):
        enabled = bool(msg.data)
        if enabled == self.face_wave_enabled:
            return

        self.face_wave_enabled = enabled
        self.last_detect_time = 0.0
        if enabled:
            self.start_camera_subscription()
            self.get_logger().info("Face wave enabled, camera subscription started")
        else:
            self.stop_camera_subscription()
            self.get_logger().info("Face wave disabled, camera subscription stopped")

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

    def image_callback(self, msg: Image):
        if not self.face_wave_enabled:
            return

        # ROS Image -> OpenCV BGR
        now = time.time()
        if now - self.last_detect_time < self.detect_interval:
            return                           # 未到5s，跳过本帧
        self.last_detect_time = now
        frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")

        results = self.model(frame, device=self.device, verbose=False)
        faces = []

        for result in results:
            boxes = result.boxes.xyxy.cpu().numpy() if result.boxes is not None else []
            confs = result.boxes.conf.cpu().numpy() if result.boxes is not None else []
            kpts_data = None
            if result.keypoints is not None:
                kpts_data = result.keypoints.data.cpu().numpy()

            for i, (box, conf) in enumerate(zip(boxes, confs)):
                x1, y1, x2, y2 = map(int, box)
                face_info = {
                    "conf": round(float(conf), 4),
                    "bbox": {
                        "x1": x1,
                        "y1": y1,
                        "x2": x2,
                        "y2": y2,
                        "w": x2 - x1,
                        "h": y2 - y1,
                    },
                }

                if kpts_data is not None and i < len(kpts_data):
                    keypoints = []
                    for kpt in kpts_data[i]:
                        keypoints.append({
                            "x": int(kpt[0]),
                            "y": int(kpt[1]),
                            "conf": round(float(kpt[2]), 4),
                        })
                    face_info["keypoints"] = keypoints

                faces.append(face_info)

                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

                if kpts_data is not None and i < len(kpts_data):
                    for j, kpt in enumerate(kpts_data[i]):
                        kx, ky, kconf = int(kpt[0]), int(kpt[1]), float(kpt[2])
                        if kconf > 0.8:
                            color = self.kpt_colors[j % len(self.kpt_colors)]
                            cv2.circle(frame, (kx, ky), 4, color, -1)

        if faces:
            msg_out = String()
            msg_out.data = self.output_data         
            self.publisher_.publish(msg_out)
            print(f"{BLUE}Detected {len(faces)} face(s), published {msg_out.data}{RESET}")

        else:
            print(f"{YELLOW}未检测到人脸{RESET}")
            
        img_msg = self.bridge.cv2_to_imgmsg(frame, encoding="bgr8")
        self.image_pub.publish(img_msg)

def main(args=None):
    rclpy.init(args=args)
    node = FaceDetectPublisher()
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
