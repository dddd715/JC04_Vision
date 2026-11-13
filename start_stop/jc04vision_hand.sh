#!/bin/bash

sleep 5

source /opt/ros/humble/setup.bash
source /home/nvidia/JC04/JC04Dev/install/setup.bash

if [ -z "$ROS_DOMAIN_ID" ]; then
    ROS_DOMAIN_ID=$(grep -oP 'export ROS_DOMAIN_ID=\K\d+' /home/nvidia/.bashrc 2>/dev/null || echo 0)
fi
export ROS_DOMAIN_ID

exec /home/nvidia/JC04_Vision/Hand/env-mediapipe/bin/python3 /home/nvidia/JC04_Vision/Hand/Mediapipe_rec.py
