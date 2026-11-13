#!/usr/bin/env python3

"""Fast, non-mutating validation for the JC04 resource-test tooling."""

from __future__ import annotations

import csv
import os
import re
import subprocess
import tempfile
from pathlib import Path

import generate_report


TEST_DIR = Path(__file__).resolve().parent


def test_tegrastats_parser(directory: Path) -> None:
    nx_log = directory / "nx.log"
    nx_log.write_text(
        "RAM 1024/15655MB CPU [10%@1000,20%@1000] GR3D_FREQ 33% "
        "cpu@55.5C gpu@52C VDD_IN 9000mW/8800mW\n",
        encoding="utf-8",
    )
    nx = generate_report.parse_tegrastats(nx_log)
    assert nx["power_rail"] == "VDD_IN"
    assert nx["gpu_percent"]["max"] == 33.0
    assert nx["max_temperature_c"] == 55.5

    nano_log = directory / "nano.log"
    nano_log.write_text(
        "RAM 2048/3964MB CPU [90%@1200,80%@1200] GR3D_FREQ 75% "
        "CPU@65C GPU@61C POM_5V_IN 12000mW/11500mW\n",
        encoding="utf-8",
    )
    nano = generate_report.parse_tegrastats(nano_log)
    assert nano["power_rail"] == "POM_5V_IN"
    assert nano["power_mw"]["max"] == 12000.0


def test_system_parser(directory: Path) -> None:
    path = directory / "system_metrics.csv"
    fieldnames = [
        "timestamp", "user", "nice", "system", "idle", "iowait", "irq",
        "softirq", "steal", "mem_total_kb", "mem_available_kb",
        "swap_total_kb", "swap_free_kb", "pswpin", "pswpout", "load1",
        "load5", "load15",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index in range(4):
            writer.writerow({
                "timestamp": 1000 + index,
                "user": index * 40,
                "nice": 0,
                "system": index * 10,
                "idle": index * 50,
                "iowait": 0,
                "irq": 0,
                "softirq": 0,
                "steal": 0,
                "mem_total_kb": 4 * 1024 * 1024,
                "mem_available_kb": (3000 - index * 10) * 1024,
                "swap_total_kb": 2 * 1024 * 1024,
                "swap_free_kb": 2 * 1024 * 1024,
                "pswpin": 0,
                "pswpout": 0,
                "load1": 1,
                "load5": 1,
                "load15": 1,
            })
    result = generate_report.parse_system(path)
    assert result["sample_count"] == 4
    assert result["cpu_percent"]["avg"] == 50.0
    assert result["memory_available_mb"]["min"] == 2970.0
    assert result["memory_growth_mb_per_hour"] is not None


def test_case_dry_runs() -> None:
    for path in sorted((TEST_DIR / "cases").glob("T*.sh")):
        subprocess.run([str(path), "--dry-run"], check=True, stdout=subprocess.DEVNULL)


def test_automatic_suite_contract() -> None:
    suite = subprocess.run(
        [str(TEST_DIR / "run_suite.sh"), "--dry-run"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert not re.search(r"^=== T1[45] ", suite.stdout, re.MULTILINE)

    hand = subprocess.run(
        [str(TEST_DIR / "cases" / "T04.sh"), "--dry-run"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "手势识别" in hand.stdout
    assert "测试后输出" in hand.stdout


def test_sudo_keepalive_does_not_inherit_case_lock(directory: Path) -> None:
    if os.geteuid() == 0:
        return

    lock_file = directory / "case.lock"
    script = r'''
source "$1/lib/common.sh"
exec 9>"$2"
flock -n 9 || exit 1
SUDO=(true)
SUDO_KEEPALIVE_INTERVAL_SECONDS=30
start_sudo_keepalive >/dev/null
exec 9>&-

status=1
for _ in {1..20}; do
    if flock -n "$2" true; then
        status=0
        break
    fi
    sleep 0.05
done
stop_sudo_keepalive
exit "$status"
'''
    subprocess.run(
        ["bash", "-c", script, "bash", str(TEST_DIR), str(lock_file)],
        check=True,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="jc04-vision-self-test-") as temp:
        directory = Path(temp)
        test_tegrastats_parser(directory)
        test_system_parser(directory)
        test_sudo_keepalive_does_not_inherit_case_lock(directory)
    test_case_dry_runs()
    test_automatic_suite_contract()
    print("JC04 vision resource-test self-check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
