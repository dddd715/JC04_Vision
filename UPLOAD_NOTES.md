# 机器人项目上传说明

本仓库为机器人 `/home/nvidia/JC04_Vision` 在 2026-11-13 的文件快照。

- 包含 Face、Hand、start_stop、test 的源码、配置和三个模型文件。
- 排除 Hand/env-mediapipe 虚拟环境、Python 缓存及测试结果、日志。运行前需按目标 Jetson 环境准备依赖。
- 模型文件直接保存在 Git 中；原先仅用于虚拟环境大文件的 Git LFS 配置已移除。
- 机器人源目录实际缺少 start_stop/service_files/camera.service，亦未包含外部路径 /home/nvidia/bin/jcbot_data_camera.sh。README 中引用这些资产的安装流程需要先补齐相应文件。
- 本次上传使用独立快照，不包含原阿里云仓库历史，不改变机器人源目录或其 Git 远程地址。
