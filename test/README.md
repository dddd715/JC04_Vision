# JC04 Vision Test

本目录用于 Jetson Orin NX 和 Jetson Orin Nano 上的 JC04 视觉资源占用测试。

完整流程、测试矩阵和结果解释见 [VISION_RESOURCE_TEST_PLAN.md](VISION_RESOURCE_TEST_PLAN.md)。

常用命令：

```bash
cd /home/nvidia/JC04_Vision/test

# 查看用例最终配置，不操作服务
./cases/T12.sh --dry-run

# 检查解析器和全部用例入口，不操作服务
./self_test.py

# 执行单个典型工况
./cases/T12.sh

# 快速验证整套脚本，每项只采60秒
./run_suite.sh --quick --repeat 1

# 正式自动执行T00-T13一轮（不执行T14/T15），预计约3小时；场景按中文提示自动倒计时
./run_suite.sh

# 可选：短用例重复3次，预计约8.5至9小时
./run_suite.sh --repeat 3

# 汇总已有结果
./aggregate_reports.py results
```

测试结果默认写入 `results/<hostname>/<timestamp>_<case>/`，该目录内容不会提交到Git。
