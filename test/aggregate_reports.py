#!/usr/bin/env python3

"""Aggregate all summary.json files below a results directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def nested(data: dict, *keys: str):
    value = data
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def fmt(value, digits=1):
    return "N/A" if value is None else f"{float(value):.{digits}f}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    summaries = []
    for path in sorted(args.results_root.rglob("summary.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["_path"] = path
            summaries.append(data)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Skip {path}: {exc}")

    output = args.output or args.results_root / "SUMMARY.md"
    lines = [
        "# JC04 Vision 多板资源测试汇总",
        "",
        "CPU为整机占用率；服务进程CPU的100%代表一个核心。本表中的FPS仅为观测值，不参与结论。",
        "",
        "| 设备 | 板型 | 用例 | 结论 | CPU P95 | GPU P95 | 最低可用内存 | 最大功耗 | 最高温度 | RGB FPS | 报告 |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for data in summaries:
        manifest = data.get("manifest", {})
        case = data.get("case", {})
        report = data["_path"].with_name("REPORT.md")
        try:
            report_link = report.relative_to(output.parent)
        except ValueError:
            report_link = report
        lines.append(
            "| {host} | {board} | {case} | {verdict} | {cpu}% | {gpu}% | "
            "{memory} MB | {power} mW | {temp} C | {fps} | [{name}]({link}) |".format(
                host=manifest.get("hostname", "unknown"),
                board=manifest.get("board_model", "unknown").replace("|", "/"),
                case=case.get("case_id", "unknown"),
                verdict=data.get("verdict", "unknown"),
                cpu=fmt(nested(data, "system", "cpu_percent", "p95")),
                gpu=fmt(nested(data, "tegrastats", "gpu_percent", "p95")),
                memory=fmt(nested(data, "system", "memory_available_mb", "min"), 0),
                power=fmt(nested(data, "tegrastats", "power_mw", "max"), 0),
                temp=fmt(nested(data, "tegrastats", "max_temperature_c")),
                fps=fmt(data.get("topic_rates", {}).get("/camera/camera/color/image_raw"), 2),
                name=report.parent.name,
                link=report_link.as_posix(),
            )
        )
    lines.extend(["", f"共汇总 {len(summaries)} 次测试。", ""])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
