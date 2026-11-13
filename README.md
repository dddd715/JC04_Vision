# JC04 Vision 部署验收与检查流程

## 1. 适用范围

本流程用于验收 `/home/nvidia/JC04_Vision` 中的 Face、Hand、RealSense 相机和 Pose 视觉部署资产。目标是确认目录、模型、Python 环境、脚本、systemd unit、开机自启和识别话题均符合量产要求。

视觉交接目录应为：

```text
/home/nvidia/JC04_Vision/
├── Face/
│   └── yolov8-face/
│       ├── ControllerAll.py
│       ├── PoseAvoid.py
│       ├── rec_face.py
│       ├── rec_pose.py
│       └── weight/
│           ├── yolo26n-pose.onnx
│           └── yolov8n-face.onnx
├── Hand/
│   ├── MediapipeTest_rec.py
│   ├── env-mediapipe/
│   └── models/
│       └── gesture_recognizer.task
└── start_stop/
    ├── jc04vision_face.sh
    ├── jc04vision_hand.sh
    ├── jc04vision_PoseAvoid.sh
    ├── jc04vision_PoseTrack.sh
    ├── install_vision_services.sh
    ├── start_vision_services.sh
    ├── stop_vision_services.sh
    ├── vision_service_status.sh
    └── service_files/
        ├── camera.service
        ├── jc04vision_face.service
        ├── jc04vision_hand.service
        ├── jc04vision_PoseAvoid.service
        └── jc04vision_PoseTrack.service
```

相机启动脚本是系统级运行资产，固定路径为：

```text
/home/nvidia/bin/jcbot_data_camera.sh
```
## 2. Ultralytics 安装与验收

`rec_face.py` 和 `rec_pose.py` 从系统 Python 导入 `ultralytics`。部署机必须在 `/usr/bin/python3` 对应环境安装该包。先确认 JetPack 对应的 PyTorch 已可用；不要使用通用 pip 命令覆盖已验证的 ARM/CUDA 版 PyTorch。

```bash
/usr/bin/python3 -c 'import torch; print(torch.__version__); print(torch.cuda.is_available())'
/usr/bin/python3 -c 'import cv2; print(cv2.__version__)'
```

 Ultralytics `8.3.154`。在已具备 PyTorch、OpenCV、NumPy 等依赖的系统 Python 中安装：

```bash
sudo /usr/bin/python3 -m pip install 'ultralytics==8.3.154'
```

Ultralytics 官方安装说明：<https://docs.ultralytics.com/quickstart/>。

## 3. Realsense驱动安装

APT 仓库安装步骤如下:

```bash
sudo apt update

sudo apt install -y ros-humble-realsense2-camera
```

验证是否安装成功：
```bash
realsense-viewer
```
若安装成功则Realsense的 GUI 界面正常启动，左侧设备列表显示相机，点击后开启深度流、RGB 流等，能实时看到画面即表示驱动安装成功


```bash
#再新建终端
ros2 launch realsense2_camera rs_launch.py
# 查看话题
ros2 topic list | grep camera
```
若能正常输出图像话题（如 /camera/color/image_raw、/camera/depth/image_rect_raw），即安装成功。
若失败则需从源码编译安装，参考教程：<https://blog.gitcode.com/7aa77d66382b1311db0c710ea38cc1c2.html>。

RealSense Linux 官方安装说明：<https://github.com/IntelRealSense/librealsense/blob/master/doc/installation.md>。

## 4. 量产安装

完成第 2、3 节前置条件后执行：

```bash
cd /home/nvidia/JC04_Vision/start_stop
chmod +x *.sh
chmod +x /home/nvidia/bin/jcbot_data_camera.sh
./install_vision_services.sh
```

输入 `nvidia` 用户的 sudo 密码。脚本会完成以下工作：

1. 检查 ROS 2、JC04 ROS 工作空间、Face/Hand/Pose 程序、ONNX 与手势模型、MediaPipe Python 环境，以及 `/home/nvidia/bin/jcbot_data_camera.sh`。
2. 导入 Face 与 Hand 所需 Python 包。
3. 安装 `camera.service`、`jc04vision_face.service`、`jc04vision_hand.service`、`jc04vision_PoseAvoid.service`、`jc04vision_PoseTrack.service` 到 `/etc/systemd/system/`。
4. 执行 `systemctl daemon-reload`。
5. 启用并启动相机、Face、Hand、Pose Avoid、Pose Track 五项视觉服务。

安装通过的判据是最后一行：

```text
SUCCESS: JC04 Vision services are installed and enabled at boot.
```

## 5. 手动环境验收测试

```bash
test -f /opt/ros/humble/setup.bash && echo "ROS 2 OK"
test -f /home/nvidia/JC04/JC04Dev/install/setup.bash && echo "JC04 ROS workspace OK"
test -f /home/nvidia/JC04_Vision/Face/yolov8-face/ControllerAll.py && echo "Controller OK"
test -f /home/nvidia/JC04_Vision/Face/yolov8-face/weight/yolov8n-face.onnx && echo "Face model OK"
test -f /home/nvidia/JC04_Vision/Face/yolov8-face/weight/yolo26n-pose.onnx && echo "Pose model OK"
test -f /home/nvidia/JC04_Vision/Hand/models/gesture_recognizer.task && echo "Hand model OK"
test -x /home/nvidia/JC04_Vision/Hand/env-mediapipe/bin/python3 && echo "MediaPipe Python OK"
test -x /home/nvidia/bin/jcbot_data_camera.sh && echo "Camera startup script OK"

source /opt/ros/humble/setup.bash
source /home/nvidia/JC04/JC04Dev/install/setup.bash
cd /home/nvidia/JC04_Vision/Face/yolov8-face
/usr/bin/python3 -c 'import cv2, rclpy, torch; from cv_bridge import CvBridge; from ultralytics import YOLO; from ControllerAll import VelocityController; print("Face Python OK")'

cd /home/nvidia/JC04_Vision/Hand
./env-mediapipe/bin/python3 -c 'import cv2, mediapipe, rclpy; from cv_bridge import CvBridge; from mediapipe.tasks.python import vision; print("Hand Python OK")'

bash -n /home/nvidia/JC04_Vision/start_stop/*.sh && echo "Shell syntax OK"
bash -n /home/nvidia/bin/jcbot_data_camera.sh && echo "Camera script syntax OK"
systemd-analyze verify /home/nvidia/JC04_Vision/start_stop/service_files/*.service
```

预期效果：每项文件、环境和 Python 导入检查均输出 `OK`，并输出 `Shell syntax OK` 和 `Camera script syntax OK`。`systemd-analyze` 不应报告本项目 unit 的语法错误。

## 6. systemd 验收测试

先确认相机脚本存在且可执行：

```bash
test -x /home/nvidia/bin/jcbot_data_camera.sh && echo "Camera startup script OK"
```

再确认 systemd 已加载的相机 unit 使用正确路径：

```bash
sudo systemctl cat camera.service
sudo systemctl show camera.service -p FragmentPath -p ExecStart -p WorkingDirectory
```

预期效果：`FragmentPath=/etc/systemd/system/camera.service`，并且 `ExecStart` 和 `WorkingDirectory` 分别包含 `/home/nvidia/bin/jcbot_data_camera.sh` 与 `/home/nvidia/bin`。
按以下顺序重新加载并验证相机自启服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable camera.service
sudo systemctl restart camera.service
systemctl is-enabled camera.service
systemctl is-active camera.service
sudo systemctl --no-pager --full status camera.service
```

预期效果：依次显示 `enabled`、`active`，并且状态中的主进程命令为 `/bin/bash /home/nvidia/bin/jcbot_data_camera.sh`。服务重启会短暂中断相机数据流，应在视觉任务空闲时执行。

检查全部视觉服务的加载、启用与运行状态：

```bash
for service_name in camera jc04vision_face jc04vision_hand jc04vision_PoseAvoid jc04vision_PoseTrack; do
  systemctl is-enabled "${service_name}.service"
  systemctl is-active "${service_name}.service"
done
```

预期效果：每个服务依次输出 `enabled` 和 `active`。`jc04vision_PoseAvoid.service` 和 `jc04vision_PoseTrack.service` 均在 `camera.service` 之后启动；Pose Track 还在 Pose Avoid 之后启动。

## 7. 手动视觉功能验收测试

启动 Face：

```bash
ros2 topic pub --once --qos-durability transient_local --qos-reliability reliable \
  /face_wave_enabled std_msgs/msg/Bool "{data: true}"
ros2 topic echo /jc04_wave_sign
```

预期效果：面对相机时，Face 服务日志出现 `Detected ... face(s), published left`，话题输出 `data: left`。

启动 Hand：

```bash
ros2 topic pub --once --qos-durability transient_local --qos-reliability reliable \
  /hand_wave_enabled std_msgs/msg/Bool "{data: true}"
ros2 topic echo /jc04_wave_sign
```

预期效果：五指张开时，Hand 服务日志出现 `Gesture [...] detected -> publish left`，话题输出 `data: left`。

验收 Pose Avoid：

```bash 
ros2 topic echo /obstacle_detected 

ros2 topic echo /camera/camera/aligned_depth_to_color/image_raw --once
```
预期效果：相机深度话题有数据；近距离障碍物出现时 /obstacle_detected 输出 data: true，移开后恢复 data: false。

验收 Pose Track：

```bash 
ros2 topic pub --once --qos-durability transient_local --qos-reliability reliable \
  /pose_follow_enabled std_msgs/msg/Bool "{data: true}" 

ros2 topic echo /pose_detect/image --once
```
预期效果：/pose_detect/image 可收到图像，目标人物在画面中央时机器人向前跟随；偏左或偏右时输出对应转向。必须在周边安全、急停有效且机器人可受控的区域执行。

## 8. 重启验收测试

在系统空闲且可安全重启时执行：

```bash
sudo reboot
```

设备恢复后执行：

```bash
cd /home/nvidia/JC04_Vision/start_stop
./vision_service_status.sh
```

预期效果：
camera、Face、Hand、Pose Avoid、Pose Track 均显示 `Active: active (running)`。随后再次执行第 7 节的 Face、Hand、Pose Avoid 和 Pose Track 话题检查；这一步通过，才表示开机自启验收完成。


## tips
## 观察手柄模式日志：
```bash
journalctl -fu joy_teleop.service
```
