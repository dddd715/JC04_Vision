import math
import time

from geometry_msgs.msg import Twist

GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"


class VelocityController:
    def __init__(
        self,
        node,
        cmd_vel_topic="/cmd_vel",
        forward_speed=1.0,
        turn_speed=0.45,
        max_linear_speed=None,
        max_angular_speed=None,
        camera_horizontal_fov_deg=69.4,
        large_turn_angle_deg=20.0,
        turn_correction_linear_speed=0.3,
        large_turn_linear_speed=0.0,
        turn_kp=0.02,
        turn_deadband_angle_deg=3.0,
        angular_accel=1.5,
        angular_decel=2.5,
        control_hz=30.0,
        command_timeout=0.50,
        initially_enabled=True,
    ):
        self.node = node
        self.forward_speed = abs(forward_speed)
        self.turn_speed = abs(turn_speed)
        self.max_linear_speed = (
            self.forward_speed if max_linear_speed is None else abs(max_linear_speed)
        )
        self.max_angular_speed = (
            self.turn_speed if max_angular_speed is None else abs(max_angular_speed)
        )
        self.camera_horizontal_fov_deg = max(float(camera_horizontal_fov_deg), 1e-6)
        self.large_turn_angle_deg = max(float(large_turn_angle_deg), 0.0)
        self.turn_correction_linear_speed = self.clamp(
            abs(float(turn_correction_linear_speed)),
            0.0,
            self.max_linear_speed,
        )
        self.large_turn_linear_speed = self.clamp(
            abs(float(large_turn_linear_speed)),
            0.0,
            self.turn_correction_linear_speed,
        )
        # At 20 degrees, the default P controller reaches 0.5 rad/s.
        self.turn_kp = max(float(turn_kp), 0.0)
        self.turn_deadband_angle_deg = max(float(turn_deadband_angle_deg), 0.0)
        self.angular_accel = max(float(angular_accel), 1e-6)
        self.angular_decel = max(float(angular_decel), 1e-6)
        self.control_hz = max(float(control_hz), 1.0)
        self.command_timeout = max(float(command_timeout), 0.0)

        self.obstacle_detected = False
        self.enabled = bool(initially_enabled)
        self.stop_cmd_sent = False
        self.disabled_stop_published = False
        self.cmd_vel_pub = node.create_publisher(Twist, cmd_vel_topic, 20)

        self.current_twist = Twist()
        self.target_twist = Twist()
        self.last_cmd_time = time.monotonic()
        self.last_update_time = self.last_cmd_time

        self.control_timer = node.create_timer(
            1.0 / self.control_hz,
            self.control_loop,
        )

    def set_enabled(self, enabled, publish_stop=True):
        enabled = bool(enabled)
        if self.enabled == enabled:
            return

        self.enabled = enabled
        now = time.monotonic()
        self.last_cmd_time = now
        self.last_update_time = now

        if enabled:
            self.disabled_stop_published = False
            self.stop_cmd_sent = False
            # print(f"{GREEN}Vision cmd_vel publishing enabled{RESET}")
            return

        self.target_twist = Twist()
        self.current_twist = Twist()
        self.disabled_stop_published = False
        # print(f"{YELLOW}Vision cmd_vel publishing disabled{RESET}")
        if publish_stop:
            self.publish_disabled_stop_once()

    def publish_disabled_stop_once(self):
        if self.disabled_stop_published:
            return

        self.publish_twist(Twist())
        self.disabled_stop_published = True

    def set_obstacle_detected(self, detected):
        previous_state = self.obstacle_detected
        self.obstacle_detected = bool(detected)

        if self.obstacle_detected and not previous_state:
            print(f"{YELLOW}Obstacle detected, force stop cmd_vel{RESET}")
            self.stop(force=True)
        elif not self.obstacle_detected and previous_state:
            self.stop_cmd_sent = False
            print(f"{GREEN}Obstacle cleared, resume cmd_vel publishing{RESET}")

    def publish_cmd_vel(self, twist, force=False):
        target_twist = self.sanitize_twist(twist)

        if not self.enabled:
            self.target_twist = Twist()
            self.current_twist = Twist()
            if force:
                self.publish_disabled_stop_once()
            return False

        if self.obstacle_detected and not force and target_twist.linear.x > 0.0:
            target_twist.linear.x = 0.0
            print(f"{YELLOW}Obstacle too close, suppress forward linear.x{RESET}")

        self.target_twist = target_twist
        self.last_cmd_time = time.monotonic()

        if force:
            self.current_twist = self.copy_twist(target_twist)
            self.publish_twist(self.current_twist)
        return True

    def forward(self, speed=None):
        twist = Twist()
        twist.linear.x = self.forward_speed if speed is None else speed
        self.publish_cmd_vel(twist)

    def turn(self, direction, angular_speed=None, heading_error_deg=None):
        twist = Twist()
        speed = self.get_turn_speed(heading_error_deg, angular_speed)
        if speed <= 0.0:
            self.publish_cmd_vel(twist)
            return

        # 普通修正保持较高线速度；超过 20 度时降到强转向线速度，
        # 角速度继续按误差比例增大，避免转向期间完全停止跟随。
        if self.is_small_turn(heading_error_deg):
            twist.linear.x = self.turn_correction_linear_speed
        else:
            twist.linear.x = self.large_turn_linear_speed

        if direction == "L":
            twist.angular.z = speed
        elif direction == "R":
            twist.angular.z = -speed
        # else:
        #     twist.angular.z = 0.0

        self.publish_cmd_vel(twist)

    def stop(self, force=False):
        twist = Twist()
        self.publish_cmd_vel(twist, force=force)

    def controller_sign(self, action, horizontal_offset_px=None, image_width=None):
        if action == "F":
            self.forward()
        elif action in ("L", "R"):
            heading_error_deg = self.horizontal_offset_to_angle_deg(
                horizontal_offset_px,
                image_width,
            )
            self.turn(action, heading_error_deg=heading_error_deg)
        else:
            self.stop()

    def horizontal_offset_to_angle_deg(self, horizontal_offset_px, image_width):
        if horizontal_offset_px is None or image_width is None:
            return None

        horizontal_offset_px = float(horizontal_offset_px)
        image_width = float(image_width)
        if (
            not math.isfinite(horizontal_offset_px)
            or not math.isfinite(image_width)
            or image_width <= 0.0
        ):
            return None

        focal_length_px = image_width / (
            2.0 * math.tan(math.radians(self.camera_horizontal_fov_deg) / 2.0)
        )
        if focal_length_px <= 0.0 or not math.isfinite(focal_length_px):
            return None

        return math.degrees(math.atan(abs(horizontal_offset_px) / focal_length_px))

    def get_turn_speed(self, heading_error_deg, angular_speed):
        if angular_speed is not None:
            return min(abs(angular_speed), self.max_angular_speed)

        if heading_error_deg is None or not math.isfinite(heading_error_deg):
            return self.turn_speed

        error_deg = abs(heading_error_deg)
        if error_deg <= self.turn_deadband_angle_deg:
            return 0.0

        return self.clamp(
            error_deg * self.turn_kp,
            0.0,
            self.turn_speed,
        )

    def is_small_turn(self, heading_error_deg):
        if heading_error_deg is None or not math.isfinite(heading_error_deg):
            return False

        return abs(heading_error_deg) <= self.large_turn_angle_deg

    def control_loop(self):
        now = time.monotonic()
        dt = max(now - self.last_update_time, 1e-3)
        self.last_update_time = now

        if not self.enabled:
            return

        effective_target = self.get_effective_target(now)
        next_twist = Twist()
        # Keep linear velocity direct; angular velocity is shaped here to prevent
        # visual L/R jitter from commanding an instantaneous reversal.
        next_twist.linear.x = effective_target.linear.x
        next_twist.angular.z = self.step_angular_towards(
            self.current_twist.angular.z,
            effective_target.angular.z,
            dt,
        )

        self.current_twist = self.sanitize_twist(next_twist)
        self.publish_twist(self.current_twist)

    def get_effective_target(self, now):
        if self.command_timeout > 0.0 and (now - self.last_cmd_time) > self.command_timeout:
            return Twist()

        effective_target = self.copy_twist(self.target_twist)
        if self.obstacle_detected and effective_target.linear.x > 0.0:
            effective_target.linear.x = 0.0
        return effective_target

    def publish_twist(self, twist):
        sanitized = self.sanitize_twist(twist)
        self.cmd_vel_pub.publish(sanitized)
        self.stop_cmd_sent = self.is_zero_twist(sanitized)

    def sanitize_twist(self, twist):
        sanitized = Twist()
        sanitized.linear.x = self.clamp(
            twist.linear.x, 
            -self.max_linear_speed, 
            self.max_linear_speed
        )
        sanitized.linear.y = 0.0
        sanitized.linear.z = 0.0
        sanitized.angular.x = 0.0
        sanitized.angular.y = 0.0
        sanitized.angular.z = self.clamp(
            twist.angular.z,
            -self.max_angular_speed,
            self.max_angular_speed,
        )
        return sanitized

    def copy_twist(self, twist):
        copied = Twist()
        copied.linear.x = twist.linear.x
        copied.linear.y = twist.linear.y
        copied.linear.z = twist.linear.z
        copied.angular.x = twist.angular.x
        copied.angular.y = twist.angular.y
        copied.angular.z = twist.angular.z
        return copied

    def is_zero_twist(self, twist):
        return (
            abs(twist.linear.x) < 1e-6
            and abs(twist.linear.y) < 1e-6
            and abs(twist.linear.z) < 1e-6
            and abs(twist.angular.x) < 1e-6
            and abs(twist.angular.y) < 1e-6
            and abs(twist.angular.z) < 1e-6
        )

    def step_angular_towards(self, current, target, dt):
        # A sign change must brake to zero before starting the opposite turn.
        # This keeps a one-frame center crossing from becoming a sharp L/R oscillation.
        if current * target < 0.0:
            return self.step_towards(current, 0.0, self.angular_accel, self.angular_decel, dt)

        moving_away = abs(target) < abs(current)
        rate_limit = self.angular_decel if moving_away else self.angular_accel
        return self.step_towards(current, target, rate_limit, rate_limit, dt)

    def step_towards(self, current, target, accel_limit, decel_limit, dt):
        delta = target - current
        if abs(delta) < 1e-9:
            return target

        moving_away = abs(target) < 1e-9 or (current * target < 0.0) or (abs(target) < abs(current))
        max_step = (decel_limit if moving_away else accel_limit) * dt

        if abs(delta) <= max_step:
            return target
        return current + max_step * (1.0 if delta > 0.0 else -1.0)

    def clamp(self, value, lower, upper):
        return max(lower, min(value, upper))
