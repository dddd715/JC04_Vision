#!/usr/bin/env python3

"""Generate a Markdown and JSON summary from one JC04 resource test run."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Iterable


def read_tsv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "\t" in line:
            key, value = line.split("\t", 1)
            values[key] = value
    return values


def number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def percentile(values: Iterable[float], fraction: float = 0.95) -> float | None:
    data = sorted(values)
    if not data:
        return None
    index = max(0, math.ceil(len(data) * fraction) - 1)
    return data[index]


def stats(values: Iterable[float]) -> dict[str, float | None]:
    data = list(values)
    if not data:
        return {"avg": None, "p95": None, "max": None, "min": None}
    return {
        "avg": statistics.fmean(data),
        "p95": percentile(data),
        "max": max(data),
        "min": min(data),
    }


def slope_per_hour(points: list[tuple[float, float]]) -> float | None:
    """Return a least-squares slope, using the latter half of the samples."""
    if len(points) < 4:
        return None
    points = points[len(points) // 2 :]
    x_mean = statistics.fmean(point[0] for point in points)
    y_mean = statistics.fmean(point[1] for point in points)
    denominator = sum((x - x_mean) ** 2 for x, _ in points)
    if denominator <= 0:
        return None
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in points)
    return numerator / denominator * 3600.0


def fmt(value: float | None, digits: int = 1) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}"


def parse_system(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    cpu_values: list[float] = []
    previous: tuple[float, float] | None = None
    for row in rows:
        values = [
            number(row.get(key))
            for key in ("user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal")
        ]
        total = sum(values)
        idle = values[3] + values[4]
        if previous is not None:
            total_delta = total - previous[0]
            idle_delta = idle - previous[1]
            if total_delta > 0:
                cpu_values.append(100.0 * (total_delta - idle_delta) / total_delta)
        previous = (total, idle)

    available_mb = [number(row.get("mem_available_kb")) / 1024.0 for row in rows]
    total_mb = [number(row.get("mem_total_kb")) / 1024.0 for row in rows]
    used_percent = [
        100.0 * (total - available) / total
        for total, available in zip(total_mb, available_mb)
        if total > 0
    ]
    swap_used_mb = [
        (number(row.get("swap_total_kb")) - number(row.get("swap_free_kb"))) / 1024.0
        for row in rows
    ]
    load1 = [number(row.get("load1")) for row in rows]
    page_in = [number(row.get("pswpin")) for row in rows]
    page_out = [number(row.get("pswpout")) for row in rows]
    memory_points = [
        (
            number(row.get("timestamp")),
            (number(row.get("mem_total_kb")) - number(row.get("mem_available_kb"))) / 1024.0,
        )
        for row in rows
    ]

    return {
        "cpu_percent": stats(cpu_values),
        "memory_used_percent": stats(used_percent),
        "memory_available_mb": stats(available_mb),
        "swap_used_mb": stats(swap_used_mb),
        "load1": stats(load1),
        "swap_page_in_delta": (max(page_in) - min(page_in)) if page_in else 0,
        "swap_page_out_delta": (max(page_out) - min(page_out)) if page_out else 0,
        "memory_growth_mb_per_hour": slope_per_hour(memory_points),
        "sample_count": len(rows),
    }


def parse_services(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            grouped[row["service"]].append(row)

    output: dict[str, dict[str, object]] = {}
    for service, rows in grouped.items():
        cpu_values: list[float] = []
        previous: tuple[float, float] | None = None
        memory_mb: list[float] = []
        memory_points: list[tuple[float, float]] = []
        active_states: set[str] = set()
        restarts: list[int] = []
        for row in rows:
            timestamp = number(row.get("timestamp"))
            cpu_nsec = number(row.get("cpu_usage_nsec"))
            if previous is not None:
                elapsed = timestamp - previous[0]
                cpu_delta = cpu_nsec - previous[1]
                if elapsed > 0 and cpu_delta >= 0:
                    cpu_values.append(cpu_delta / 1_000_000_000.0 / elapsed * 100.0)
            previous = (timestamp, cpu_nsec)
            current_memory = number(row.get("memory_current_bytes"), -1)
            if current_memory >= 0:
                memory_mb.append(current_memory / 1024.0 / 1024.0)
                memory_points.append((timestamp, current_memory / 1024.0 / 1024.0))
            active_states.add(row.get("active_state", "unknown"))
            restarts.append(int(number(row.get("restarts"))))

        output[service] = {
            "cpu_percent": stats(cpu_values),
            "memory_mb": stats(memory_mb),
            "memory_growth_mb_per_hour": slope_per_hour(memory_points),
            "states": sorted(active_states),
            "final_state": rows[-1].get("active_state", "unknown"),
            "max_restarts": max(restarts) if restarts else 0,
        }
    return output


def parse_tegrastats(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    gpu: list[float] = []
    power: list[float] = []
    ram: list[float] = []
    temperatures: dict[str, list[float]] = defaultdict(list)
    power_rail = ""

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.search(r"GR3D_FREQ\s+(\d+(?:\.\d+)?)%", line)
        if match:
            gpu.append(float(match.group(1)))
        match = re.search(r"RAM\s+(\d+)/\d+MB", line)
        if match:
            ram.append(float(match.group(1)))
        for rail in ("VDD_IN", "POM_5V_IN", "POM_5V_GPU", "POM_5V_CPU"):
            match = re.search(rf"\b{rail}\s+(\d+)mW", line)
            if match and (not power_rail or rail == power_rail):
                if not power_rail:
                    power_rail = rail
                if rail == power_rail:
                    power.append(float(match.group(1)))
                break
        for sensor, value in re.findall(r"\b([A-Za-z][A-Za-z0-9_]*)@(-?\d+(?:\.\d+)?)C", line):
            temperatures[sensor].append(float(value))

    hottest_sensor = ""
    hottest_value: float | None = None
    for sensor, values in temperatures.items():
        sensor_max = max(values)
        if hottest_value is None or sensor_max > hottest_value:
            hottest_sensor = sensor
            hottest_value = sensor_max

    return {
        "gpu_percent": stats(gpu),
        "power_mw": stats(power),
        "power_rail": power_rail or "unknown",
        "tegrastats_ram_mb": stats(ram),
        "hottest_sensor": hottest_sensor or "unknown",
        "max_temperature_c": hottest_value,
        "temperature_max_c": {key: max(values) for key, values in temperatures.items()},
        "sample_count": max(len(gpu), len(ram), len(power)),
    }


def parse_topic_rates(directory: Path) -> dict[str, float | None]:
    rates: dict[str, float | None] = {}
    if not directory.exists():
        return rates
    for path in sorted(directory.glob("*.hz.log")):
        text = path.read_text(encoding="utf-8", errors="replace")
        topic_match = re.search(r"^topic:\s*(.+)$", text, re.MULTILINE)
        topic = topic_match.group(1).strip() if topic_match else path.stem
        matches = re.findall(r"average rate:\s*([0-9.]+)", text)
        rates[topic] = float(matches[-1]) if matches else None
    return rates


def parse_journal_rates(path: Path, duration: float) -> dict[str, float | None]:
    if not path.exists() or duration <= 0:
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    counts = {
        "face_inference_log_rate": len(re.findall(r"Detected \d+ face|未检测到人脸", text)),
        "pose_processing_log_rate": len(re.findall(r"target track_id=|未检测到可靠的人体", text)),
        "avoid_processing_log_rate": len(re.findall(r"Obstacle detected:|Path clear:|No valid depth data", text)),
        "hand_gesture_event_rate": len(re.findall(r"Gesture \[.*?\] detected", text)),
    }
    return {key: count / duration for key, count in counts.items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_dir", type=Path)
    args = parser.parse_args()
    result_dir = args.result_dir.resolve()

    manifest = read_tsv(result_dir / "manifest.tsv")
    case = read_tsv(result_dir / "case.tsv")
    system = parse_system(result_dir / "system_metrics.csv")
    services = parse_services(result_dir / "service_metrics.csv")
    tegra = parse_tegrastats(result_dir / "tegrastats.log")
    topic_rates = parse_topic_rates(result_dir / "topic_rates")
    duration = number(case.get("actual_duration_seconds") or case.get("duration_seconds"))
    journal_rates = parse_journal_rates(result_dir / "vision_journal.log", duration)
    min_available_threshold = number(case.get("min_available_memory_mb"), 512)
    max_memory_growth = number(case.get("max_memory_growth_mb_per_hour"), 40)

    warnings: list[str] = []
    if not case.get("case_id"):
        warnings.append("Case metadata is missing; this is not a complete test result.")
    if manifest.get("git_dirty") == "yes":
        warnings.append("The Git worktree was dirty, so this result is not a reproducible formal baseline.")
    if system.get("sample_count", 0) < 2:
        warnings.append("Core system samples are missing or insufficient for CPU calculation.")
    if tegra.get("sample_count", 0) < 1:
        warnings.append("No parseable tegrastats samples were collected.")
    minimum_available = system.get("memory_available_mb", {}).get("min") if system else None
    if minimum_available is not None and minimum_available < min_available_threshold:
        warnings.append(
            f"Minimum available memory {minimum_available:.0f} MB is below the configured {min_available_threshold:.0f} MB threshold."
        )
    if system and (system.get("swap_page_in_delta", 0) or system.get("swap_page_out_delta", 0)):
        warnings.append("Swap paging occurred during the core sampling window.")
    memory_growth = system.get("memory_growth_mb_per_hour") if system else None
    if duration >= 3600 and memory_growth is not None and memory_growth > max_memory_growth:
        warnings.append(
            f"System memory grew at {memory_growth:.1f} MB/hour, above the configured {max_memory_growth:.1f} MB/hour threshold."
        )
    expected_services = set(filter(None, case.get("expected_services", "").split(",")))
    startup_capture = case.get("capture_startup", "false").lower() == "true"
    for service in expected_services:
        states = services.get(service, {}).get("states", [])
        final_state = services.get(service, {}).get("final_state", "unknown")
        if startup_capture and final_state != "active":
            warnings.append(f"Startup case service {service} did not finish active: {final_state}.")
        elif not startup_capture and ("active" not in states or any(state != "active" for state in states)):
            warnings.append(f"Expected service {service} was not active for the complete sample window: {states}.")
        if services.get(service, {}).get("max_restarts", 0):
            warnings.append(f"Service {service} reported one or more restarts.")
    journal_path = result_dir / "vision_journal.log"
    if journal_path.exists():
        journal = journal_path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"Traceback|Out of memory|Killed process|segfault|CUDA[^\n]*error", journal, re.IGNORECASE):
            warnings.append("The service journal contains a crash, OOM, or runtime error signature.")
    kernel_path = result_dir / "kernel_journal.log"
    if kernel_path.exists():
        kernel = kernel_path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"Out of memory|Killed process|soctherm|thermal thrott|over.?current|OC ALARM", kernel, re.IGNORECASE):
            warnings.append("The kernel journal contains an OOM, thermal-throttle, or over-current signature.")

    verdict = "STABLE" if not warnings else "REVIEW"
    system_growth_display = memory_growth if duration >= 3600 else None
    summary = {
        "case": case,
        "manifest": manifest,
        "system": system,
        "services": services,
        "tegrastats": tegra,
        "topic_rates": topic_rates,
        "journal_event_rates": journal_rates,
        "warnings": warnings,
        "verdict": verdict,
    }
    (result_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        f"# {case.get('case_id', 'Unknown')} 视觉资源占用测试报告",
        "",
        f"- 结论：**{verdict}**",
        f"- 用例：{case.get('title', 'unknown')}",
        f"- 设备：{manifest.get('board_model', 'unknown')}",
        f"- 主机名：{manifest.get('hostname', 'unknown')}",
        f"- JetPack/L4T：{manifest.get('l4t_release', 'unknown')}",
        f"- Git commit：`{manifest.get('git_commit', 'unknown')}`，dirty={manifest.get('git_dirty', 'unknown')}",
        f"- 功耗模式：{manifest.get('nvpmodel', 'unknown')}",
        f"- 核心采集时长：{fmt(duration, 0)} 秒",
        f"- 相机配置：{manifest.get('expected_camera_resolution', 'unknown')}@{manifest.get('expected_camera_fps', 'unknown')} FPS",
        f"- 操作提示：{case.get('prompt', '无')}",
        f"- 测试后输出：{case.get('result_hint', '详见本报告指标')}",
        "",
        "## 整机指标",
        "",
        "| 指标 | 平均 | P95 | 最大/最小 |",
        "|---|---:|---:|---:|",
        f"| CPU占用 | {fmt(system.get('cpu_percent', {}).get('avg'))}% | {fmt(system.get('cpu_percent', {}).get('p95'))}% | {fmt(system.get('cpu_percent', {}).get('max'))}% |",
        f"| 内存占用 | {fmt(system.get('memory_used_percent', {}).get('avg'))}% | {fmt(system.get('memory_used_percent', {}).get('p95'))}% | {fmt(system.get('memory_used_percent', {}).get('max'))}% |",
        f"| 可用内存 | {fmt(system.get('memory_available_mb', {}).get('avg'), 0)} MB | {fmt(system.get('memory_available_mb', {}).get('p95'), 0)} MB | 最低 {fmt(system.get('memory_available_mb', {}).get('min'), 0)} MB |",
        f"| Swap占用 | {fmt(system.get('swap_used_mb', {}).get('avg'), 0)} MB | {fmt(system.get('swap_used_mb', {}).get('p95'), 0)} MB | {fmt(system.get('swap_used_mb', {}).get('max'), 0)} MB |",
        f"| GPU占用 | {fmt(tegra.get('gpu_percent', {}).get('avg'))}% | {fmt(tegra.get('gpu_percent', {}).get('p95'))}% | {fmt(tegra.get('gpu_percent', {}).get('max'))}% |",
        f"| 输入功耗 ({tegra.get('power_rail', 'unknown')}) | {fmt(tegra.get('power_mw', {}).get('avg'), 0)} mW | {fmt(tegra.get('power_mw', {}).get('p95'), 0)} mW | {fmt(tegra.get('power_mw', {}).get('max'), 0)} mW |",
        f"| 温度 | - | - | {tegra.get('hottest_sensor', 'unknown')} {fmt(tegra.get('max_temperature_c'))} C |",
        f"| 整机内存增长 | {fmt(system_growth_display)} MB/h | - | 仅一小时以上用例展示 |",
        "",
        "## 服务资源",
        "",
        "CPU按进程语义统计，100%代表占满一个CPU核心。内存来自systemd cgroup，包含服务子进程。",
        "",
        "| 服务 | CPU平均 | CPU P95 | CPU最大 | 内存平均 | 内存最大 | 内存增长 | 状态 | 重启 |",
        "|---|---:|---:|---:|---:|---:|---:|---|---:|",
    ]
    for service in ("camera", "jc04vision_face", "jc04vision_hand", "jc04vision_PoseAvoid", "jc04vision_PoseTrack"):
        item = services.get(service, {})
        cpu = item.get("cpu_percent", {})
        memory = item.get("memory_mb", {})
        service_growth = item.get("memory_growth_mb_per_hour") if duration >= 3600 else None
        lines.append(
            f"| {service} | {fmt(cpu.get('avg'))}% | {fmt(cpu.get('p95'))}% | {fmt(cpu.get('max'))}% | "
            f"{fmt(memory.get('avg'), 0)} MB | {fmt(memory.get('max'), 0)} MB | "
            f"{fmt(service_growth)} MB/h | "
            f"{','.join(item.get('states', [])) or 'N/A'} | {item.get('max_restarts', 0)} |"
        )

    lines.extend([
        "",
        "## FPS与事件率",
        "",
        "ROS话题FPS在核心资源采样完成后单独测量，不计入上面的资源统计。日志估算值可能受Python stdout缓冲影响，仅作为参考。",
        "",
        "| 观测项 | FPS/事件率 | 说明 |",
        "|---|---:|---|",
    ])
    topic_descriptions = {
        "/camera/camera/color/image_raw": "RealSense RGB输入FPS",
        "/camera/camera/aligned_depth_to_color/image_raw": "RealSense对齐深度输入FPS",
        "/face_detect/image": "Face处理结果图像FPS",
        "/pose_detect/image": "Pose节点当前声明该话题，但现有代码未发布图像",
        "/jc04_wave_sign": "Face/Hand识别事件率，不等于处理FPS",
        "/output_msg": "Pose检测到目标时的输出事件率",
        "/obstacle_detected": "障碍状态变化事件率，不等于深度处理FPS",
    }
    for topic, description in topic_descriptions.items():
        lines.append(f"| `{topic}` | {fmt(topic_rates.get(topic), 3)} | {description} |")
    lines.extend([
        f"| Face日志估算 | {fmt(journal_rates.get('face_inference_log_rate'), 3)} | rec_face推理事件/秒 |",
        f"| Pose日志估算 | {fmt(journal_rates.get('pose_processing_log_rate'), 3)} | rec_pose处理事件/秒 |",
        f"| PoseAvoid日志估算 | {fmt(journal_rates.get('avoid_processing_log_rate'), 3)} | 深度决策事件/秒 |",
        f"| Hand事件率 | {fmt(journal_rates.get('hand_gesture_event_rate'), 3)} | 受1秒日志节流影响，不是处理FPS |",
        "",
        "## 稳定性检查",
        "",
    ])
    if warnings:
        lines.extend(f"- REVIEW: {warning}" for warning in warnings)
    else:
        lines.append("- 未发现OOM、服务重启、持续换页或可用内存低于阈值等稳定性问题。")
    lines.extend([
        "",
        "FPS不参与通过/失败判断。STABLE仅表示本用例采集窗口内未命中已配置的稳定性告警。",
        "",
        "## 原始数据",
        "",
        "完整数据见本报告同目录下的CSV、tegrastats、journal和topic_rates文件。",
        "",
    ])
    (result_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(result_dir / "REPORT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
