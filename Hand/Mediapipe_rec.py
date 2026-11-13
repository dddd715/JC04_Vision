import os
import threading

import cv2
import mediapipe as mp
import rclpy
from cv_bridge import CvBridge
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import Image
from std_msgs.msg import Bool
from std_msgs.msg import String


class GestureProcessor:

    MODEL_PATH = os.path.join(
        os.path.dirname(__file__),
        "models",
        "gesture_recognizer.task",
    )

    def __init__(
        self,
        num_hands: int = 2,
        min_hand_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
    ):
        self.gesture_recognizer = None
        self.latest_result = None
        self.init_gesture_recognizer(
            num_hands=num_hands,
            min_hand_detection_confidence=min_hand_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

    def init_gesture_recognizer(
        self,
        num_hands: int,
        min_hand_detection_confidence: float,
        min_tracking_confidence: float,
    ):
        if not os.path.exists(self.MODEL_PATH):
            raise FileNotFoundError(
                f"Gesture recognizer model not found: {self.MODEL_PATH}"
            )

        base_options = python.BaseOptions(model_asset_path=self.MODEL_PATH)
        options = vision.GestureRecognizerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.IMAGE,
            num_hands=num_hands,
            min_hand_detection_confidence=min_hand_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self.gesture_recognizer = vision.GestureRecognizer.create_from_options(
            options
        )

    def process_frame(self, frame_bgr):
        rgb_frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb_frame = rgb_frame.copy()
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

        self.latest_result = self.gesture_recognizer.recognize(mp_image)

    def get_gesture_names(self) -> list[str]:
        if not self.latest_result or not self.latest_result.gestures:
            return []

        names = []
        for hand_gestures in self.latest_result.gestures:
            if hand_gestures:
                names.append(hand_gestures[0].category_name)
        return names

    def has_gesture(self) -> bool:
        for name in self.get_gesture_names():
            if name and name.lower() != "none":
                return True
        return False

    def close(self):
        if self.gesture_recognizer:
            self.gesture_recognizer.close()


class HandGesturePublisher(Node):

    def __init__(self):
        super().__init__("hand_gesture_publisher")
        self.msg = "left"
        self.gesture_topic = "jc04_wave_sign"
        self.declare_parameter("image_topic", "/camera/camera/color/image_raw")
        self.declare_parameter("enable_topic", "/hand_wave_enabled")
        self.image_topic = self.get_parameter("image_topic").get_parameter_value().string_value
        self.enable_topic = self.get_parameter("enable_topic").get_parameter_value().string_value
        self.hand_wave_enabled = False
        self.sub_image = None
        self.lock = threading.Lock()

        self.pub_gesture = self.create_publisher(
            String, self.gesture_topic, 10
        )
        enable_qos = QoSProfile(depth=1)
        enable_qos.reliability = QoSReliabilityPolicy.RELIABLE
        enable_qos.durability = QoSDurabilityPolicy.TRANSIENT_LOCAL
        self.enable_subscription = self.create_subscription(
            Bool,
            self.enable_topic,
            self.enable_callback,
            enable_qos,
        )

        self.bridge = CvBridge()
        self.processor = GestureProcessor()

        self.get_logger().info("HandGesturePublisher started.")
        self.get_logger().info(
            f"Image topic: {self.image_topic} | "
            f"Enable topic: {self.enable_topic} | "
            f"Publish: {self.gesture_topic}"
        )
        self.get_logger().info("Hand wave is disabled until enable topic publishes true")

    def enable_callback(self, msg: Bool):
        enabled = bool(msg.data)
        if enabled == self.hand_wave_enabled:
            return

        self.hand_wave_enabled = enabled
        if enabled:
            self.start_image_subscription()
            self.get_logger().info("Hand wave enabled, camera subscription started")
        else:
            self.stop_image_subscription()
            self.get_logger().info("Hand wave disabled, camera subscription stopped")

    def start_image_subscription(self):
        if self.sub_image is not None:
            return

        self.sub_image = self.create_subscription(
            Image,
            self.image_topic,
            self.image_callback,
            10,
        )

    def stop_image_subscription(self):
        if self.sub_image is None:
            return

        self.destroy_subscription(self.sub_image)
        self.sub_image = None

    def image_callback(self, msg: Image):
        if not self.hand_wave_enabled:
            return

        try:
            with self.lock:
                frame_bgr = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
                self.processor.process_frame(frame_bgr)
                names = self.processor.get_gesture_names()
                gesture_detected = self.processor.has_gesture()
        except Exception as exc:
            self.get_logger().error(f"Gesture processing failed: {exc}")
            return

        if gesture_detected:
            gesture_msg = String()
            gesture_msg.data = self.msg
            self.pub_gesture.publish(gesture_msg)
            self.get_logger().info(
                f"Gesture {names} detected -> publish {self.msg}",
                throttle_duration_sec=1.0,
            )

    def destroy_node(self):
        self.processor.close()
        cv2.destroyAllWindows()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = HandGesturePublisher()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
