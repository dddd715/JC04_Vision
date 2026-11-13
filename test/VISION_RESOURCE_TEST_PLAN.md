# JC04视觉模块资源占用测试方案

## 1. 测试目标

本方案用于测量JC04机器人视觉模块在以下平台上的CPU、内存、GPU、功耗、温度和稳定性：

- Jetson Orin NX
- Jetson Orin Nano 4GB
- JetPack 6.2
- Intel RealSense，RGB和对齐深度流均为640x480@15 FPS

生产视觉组合为以下五项systemd服务同步启动：

```text
camera.service
jc04vision_face.service
jc04vision_hand.service
jc04vision_PoseAvoid.service
jc04vision_PoseTrack.service
```

Face、Hand和Pose Track还需要通过ROS Bool话题启用；PoseAvoid在服务启动后持续处理深度帧。本测试记录各视觉功能FPS，但FPS不参与通过或失败判定。底盘运动不属于本测试范围。

## 2. 测试原则

1. Orin NX用于验证工具和提供对照数据，量产结论以Orin Nano 4GB实测结果为准。
2. 所有对比设备必须使用相同Git commit、模型和相机配置；同型号设备必须使用相同功耗模式和散热条件。
3. 默认不启用`jetson_clocks`。只有量产配置长期启用时，才在所有设备上统一启用。
4. 核心资源采样期间不运行RViz、`realsense-viewer`或`ros2 topic hz`图像订阅。
5. ROS话题FPS在核心采样结束后单独测量，避免探针改变主测试结果。
6. 每个短用例预热2分钟；默认自动套件执行T00-T13一轮以控制在约3小时，正式重复性评估可显式执行3轮；T14和T15不属于本自动流程。
7. 多块板同时联网时必须使用不同的`ROS_DOMAIN_ID`，避免DDS跨板发现和控制话题串扰。

## 3. 测试前准备

### 3.1 软件和服务

先完成项目根目录README中的部署验收，确认五项服务可以正常启动。检查：

```bash
cd /home/nvidia/JC04_Vision
git status --short --branch
git rev-parse HEAD

cd start_stop
./vision_service_status.sh
```

各设备必须处于同一个Git commit。若测试工作区有未提交修改，报告会记录`git_dirty=yes`，该结果不应与其他正式结果直接比较。

### 3.2 相机配置

本测试脚本不会修改`/home/nvidia/bin/jcbot_data_camera.sh`。开始前确认该脚本实际配置为：

```text
RGB: 640x480@15 FPS
Depth: 640x480@15 FPS
Align depth to color: enabled
```

先进行一次独立功能检查：

```bash
ros2 topic hz /camera/camera/color/image_raw --wall-time
ros2 topic hz /camera/camera/aligned_depth_to_color/image_raw --wall-time
```

观察约30秒后按`Ctrl+C`退出。正式核心采样时不要保留这两个命令。

### 3.3 功耗和散热

记录功耗模式：

```bash
sudo nvpmodel -q
sudo jetson_clocks --show
```

不要为了得到更高分数临时切换到MAXN或开启锁频。设备应使用该板型在机器人上的实际量产配置；Orin NX与Orin Nano的功耗模式名称和功率上限可以不同，但同型号样机必须一致。记录供电方式、风扇策略和环境温度。

### 3.4 ROS Domain

每块板使用不同Domain，例如：

```text
Orin-NX:     ROS_DOMAIN_ID=31
Orin-Nano-1: ROS_DOMAIN_ID=41
Orin-Nano-2: ROS_DOMAIN_ID=42
```

本项目systemd启动脚本从`/home/nvidia/.bashrc`读取该值。测试终端和`.bashrc`中的值必须一致。修改后重启视觉服务，再开始测试。

### 3.5 配置文件

统一检查[test/config.env](config.env)：

- `DEFAULT_SAMPLE_INTERVAL_MS=500`：短测试采样间隔。
- `LONG_SAMPLE_INTERVAL_MS=1000`：长稳测试采样间隔。
- `ROS_PROBE_SECONDS=30`：资源采样后的话题FPS测量时间。
- `MIN_AVAILABLE_MEMORY_MB=512`：Orin Nano 4GB可用内存告警线。
- `MAX_MEMORY_GROWTH_MB_PER_HOUR=40`：一小时以上用例的整机内存增长告警线。
- `RESTORE_INITIAL_SERVICE_STATE=1`：测试后恢复原服务active/inactive状态。

测试无法查询节点内部保存的Face/Hand/Pose enable状态，因此恢复服务后会将三个开关统一设为`false`。机器人上层控制程序应在测试结束后重新发布所需状态。

## 4. 通用执行流程

每个用例由[run_case.sh](run_case.sh)执行，流程如下：

1. 获取独占锁，防止同一设备同时运行两个测试。
2. 保存五项视觉服务的初始状态。
3. 采集板型、系统、功耗模式、软件版本、模型哈希和相机信息。
4. 停止全部视觉服务，再按用例启动精确服务组合。
5. 发布Face、Hand、Pose Track的enable状态。
6. 输出中文场景提示并自动倒计时，操作员在倒计时内完成场景布置，然后自动预热。
7. 在无额外ROS图像探针情况下采集核心资源。
8. 截取测试窗口内的五项服务journal。
9. 核心采样结束后，单独测量ROS话题FPS。
10. 生成`REPORT.md`和`summary.json`。
11. 恢复测试前服务状态，并将识别enable状态重置为false。

脚本会调用`sudo systemctl`和`sudo journalctl`。运行器先尝试复用已有sudo凭据；如果凭据未缓存且当前有终端，只需认证一次，后续会自动续期，避免长流程反复输入密码。无终端执行时请提前运行一次`sudo -v`。

## 5. 测试用例

| 用例 | 服务和状态 | 默认采集时间 | 场景与目的 | 执行脚本 |
|---|---|---:|---|---|
| T00 | 全部视觉服务停止 | 5分钟 | 测量机器人后台基线 | `cases/T00.sh` |
| T01 | Camera | 10分钟 | 测量RealSense和ROS图像传输 | `cases/T01.sh` |
| T02 | Camera + PoseAvoid | 10分钟 | 清空路径后放入1.2m内障碍，测量深度处理 | `cases/T02.sh` |
| T03 | Camera + Face，Face=true | 10分钟 | 保持一张清晰人脸，测量Face增量 | `cases/T03.sh` |
| T04 | Camera + Hand，Hand=true | 10分钟 | 保持一只张开的手，测量MediaPipe增量 | `cases/T04.sh` |
| T05 | Camera + Pose Track，Pose=true | 10分钟 | 单人在画面中移动，隔离Pose增量 | `cases/T05.sh` |
| T06 | 五服务从停止状态同步启动 | 5分钟 | 采集器先启动，测量模型加载CPU和内存峰值 | `cases/T06.sh` |
| T10 | 五服务启动，三个enable=false | 10分钟 | 测量生产待机；PoseAvoid仍持续运行 | `cases/T10.sh` |
| T11 | 五服务全部启用 | 15分钟 | 无人、无手、无近障碍空场景 | `cases/T11.sh` |
| T12 | 五服务全部启用 | 30分钟 | 单人、单手、清空/障碍切换的典型工况 | `cases/T12.sh` |
| T13 | 五服务全部启用 | 30分钟 | 多人、双手、反复障碍切换的压力工况 | `cases/T13.sh` |
| T14 | 五服务全部启用 | 2小时 | 典型工况长稳测试（当前自动流程不执行） | `cases/T14.sh` |
| T15 | 五服务全部启用 | 8小时 | 代表性样机最终长稳测试（当前自动流程不执行） | `cases/T15.sh` |

T05的systemd unit通过`Wants=`依赖PoseAvoid。运行器先正常启动Pose Track，再停止被自动拉起的PoseAvoid，且不修改任何unit文件。T05只用于诊断；本自动流程的生产结论使用T12和T13。

T06没有预热。脚本先停止五项服务并启动资源采集器，1秒后依次启动Camera、Face、Hand、PoseAvoid和PoseTrack，因此可以捕获模型加载阶段峰值。它测量视觉服务启动，不代替整机冷启动和开机自启验收；整机重启仍按项目根目录README执行3次。

## 6. 执行方法

### 6.1 无副作用检查

以下命令只打印解析后的用例，不操作服务：

```bash
cd /home/nvidia/JC04_Vision/test
./self_test.py
./cases/T12.sh --dry-run
```

### 6.2 单个用例

```bash
./cases/T12.sh
```

可覆盖时长和预热时间；场景提示会自动倒计时，不需要按回车确认：

```bash
./cases/T12.sh --warmup 30 --duration 300 --interval 500
```

SSH无人值守执行（当前默认即为自动模式）：

```bash
./cases/T12.sh --non-interactive
```

脚本只跳过人工确认，操作员仍需提前布置对应场景。

### 6.3 快速验证

正式测试前，在每种板型上运行一次：

```bash
./run_suite.sh --quick --repeat 1 --non-interactive
```

快速模式每项预热10秒、采集60秒，只验证脚本和数据链路，不形成正式资源结论。

### 6.4 正式短测试

```bash
./run_suite.sh
```

默认自动执行T00至T13（包括T06）1轮。核心采样共145分钟、预热共20分钟、FPS探测约5.5分钟，加上服务切换和环境采集后预计约2小时50分钟至3小时；场景动作在中文提示和倒计时期间完成，不需要按回车确认。

需要3轮重复性数据时执行：

```bash
./run_suite.sh --repeat 3
```

多轮模式按轮次交叉执行，先完成所有用例的第1轮，再进行后续轮次，以减少连续执行同一负载造成的热偏差；总时间预计约8.5至9小时。

### 6.5 长稳测试

当前自动测试闭环只执行`T00-T13`，不执行`T14`和`T15`长稳用例。长稳用例定义仍保留在配置中供后续专项测试参考，不属于本流程的默认结果。

## 7. 采集内容

核心采样包括：

- `/proc/stat`整机CPU累计时间。
- `/proc/meminfo`可用内存和Swap。
- `/proc/vmstat`Swap换入换出。
- systemd cgroup的每服务CPU、内存、任务数和重启次数。
- `tegrastats`的GPU、RAM、温度和输入功耗。
- 测试窗口内五项视觉服务journal。
- 测试窗口内kernel journal，用于检查OOM、热降频和过流事件。

服务CPU按Linux进程语义表示，`100%`等于占满一个CPU核心；整机CPU已经归一化为`0%`到`100%`。服务内存来自systemd cgroup，Camera服务产生的ROS子进程也包含在内。

## 8. FPS说明

报告会展示以下可外部观测数据：

- RGB输入话题FPS。
- 对齐深度输入话题FPS。
- `/face_detect/image`输出FPS。
- Pose、PoseAvoid和Face的journal处理事件估算率。
- Hand识别事件率。

当前代码存在以下限制：

- Face设计为每5秒推理一次，约0.2 FPS属于预期行为。
- `/pose_detect/image`虽然已创建publisher，但当前`rec_pose.py`没有发布图像。
- Hand没有逐帧输出话题，且识别日志有1秒节流，所以外部脚本无法无侵入地得到严格的Hand处理FPS。
- `/output_msg`只在Pose找到目标时发布，不能等同于所有Pose推理帧。
- `/obstacle_detected`只在状态变化时发布，不能等同于深度处理FPS。

因此报告将严格区分“话题FPS”“日志估算处理率”和“识别事件率”，不把事件率错误标记为算法处理FPS。需要精确的Hand/Pose内部处理FPS时，应另行给四个节点增加测试模式计数器；不要用额外图像订阅数量代替内部处理量。

## 9. 结果目录

每次运行产生：

```text
test/results/<hostname>/<timestamp>_<case>/
├── REPORT.md
├── summary.json
├── manifest.tsv
├── environment.txt
├── case.tsv
├── system_metrics.csv
├── service_metrics.csv
├── tegrastats.log
├── vision_journal.log
├── kernel_journal.log
├── service_status_before.txt
├── service_status_after.txt
├── initial_service_state.tsv
├── test.log
└── topic_rates/
```

汇总多个设备或多次测试：

```bash
./aggregate_reports.py results
```

生成的`results/SUMMARY.md`包含设备、板型、用例、CPU P95、GPU P95、最低可用内存、最大功耗、最高温度和RGB FPS。

## 10. 结论规则

FPS仅展示，不参与判定。单次报告的`STABLE`表示采样窗口内没有命中以下问题：

- OOM、进程被杀、CUDA运行错误或Traceback。
- 预期服务在采样期间退出或发生重启。
- 可用内存低于512MB。
- 测试期间发生Swap换入或换出。

CPU或GPU达到高占用会完整展示，但不会在没有产品性能门槛时直接判失败。温度、功耗和频率应结合该设备的`nvpmodel`配置人工复核；如出现热降频，最终结论应标记为不稳定。

内存增长速率只在T14和T15等至少一小时的结果中展示，短测试的线性斜率噪声过大，不用于结论。正式基线还要求`git_dirty=no`；工作区存在未提交修改时报告会标记`REVIEW`。

## 11. 多板测试要求

1. 用Git tag或完整commit固定测试版本，禁止一块板使用dirty工作区、另一块使用正式commit。
2. 各设备使用唯一主机名和`ROS_DOMAIN_ID`。
3. 使用同型号RealSense、同分辨率和帧率。
4. 同型号设备使用相同功耗模式、散热器、风扇策略和供电；跨板型报告保留各自量产功耗模式。
5. 同一测试场景标记人物与相机位置，记录环境温度。
6. 原始结果在各板本地生成，测试完成后再集中回收，避免SSH监控命令改变负载。
7. 同型号Orin Nano之间关键指标偏差超过10%时，检查散热、供电、存储和后台服务。

## 12. 异常处理

脚本收到`Ctrl+C`或命令失败时会尝试恢复初始服务状态。若终端掉电或设备重启，恢复逻辑无法执行，重新登录后运行：

```bash
cd /home/nvidia/JC04_Vision/start_stop
./start_vision_services.sh

ros2 topic pub --once --qos-durability transient_local --qos-reliability reliable \
  /face_wave_enabled std_msgs/msg/Bool '{data: false}'
ros2 topic pub --once --qos-durability transient_local --qos-reliability reliable \
  /hand_wave_enabled std_msgs/msg/Bool '{data: false}'
ros2 topic pub --once --qos-durability transient_local --qos-reliability reliable \
  /pose_follow_enabled std_msgs/msg/Bool '{data: false}'
```

然后检查：

```bash
./vision_service_status.sh
```
