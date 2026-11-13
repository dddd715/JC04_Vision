#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repeat_count=1
quick=0
non_interactive=0
dry_run=0
selected_cases=()
suite_status=0

usage() {
    cat <<'EOF'
Usage: run_suite.sh [options] [CASE_ID...]

By default runs the complete short-test workflow T00-T13 once, including T06, in about three hours.

Options:
  --repeat N            Repetitions for T00-T13 (default: 1).
  --quick               Use 10s warm-up and 60s capture for validation.
  --non-interactive     Compatibility option; scene setup is always automatic.
  --dry-run             Resolve all cases without changing services.
  -h, --help            Show this help.
EOF
}

while (( $# )); do
    case "$1" in
        --repeat)
            (( $# >= 2 )) || { printf '%s\n' '--repeat requires a value' >&2; exit 2; }
            repeat_count="$2"
            shift 2
            ;;
        --quick)
            quick=1
            shift
            ;;
        --non-interactive)
            non_interactive=1
            shift
            ;;
        --dry-run)
            dry_run=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        T00|T01|T02|T03|T04|T05|T06|T10|T11|T12|T13)
            selected_cases+=("$1")
            shift
            ;;
        *)
            printf 'Unknown option or case: %s\n' "$1" >&2
            exit 2
            ;;
    esac
done

[[ "$repeat_count" =~ ^[1-9][0-9]*$ ]] || { printf 'Repeat must be positive\n' >&2; exit 2; }
if (( ${#selected_cases[@]} == 0 )); then
    selected_cases=(T00 T01 T02 T03 T04 T05 T06 T10 T11 T12 T13)
fi
runner_options=()
(( non_interactive )) && runner_options+=(--non-interactive)
(( quick )) && runner_options+=(--warmup 10 --duration 60 --interval 1000)
(( dry_run )) && runner_options+=(--dry-run)

short_cases=("${selected_cases[@]}")

printf '[%s] 正在开始JC04视觉资源自动测试流程（不执行T14/T15）\n' "$(date '+%F %T')"

# Run repeated short cases round-robin so thermal/time drift is spread across
# cases instead of executing one workload repeatedly back-to-back.
for (( run=1; run<=repeat_count; run++ )); do
    for case_id in "${short_cases[@]}"; do
        printf '\n=== %s run %d/%d ===\n' "$case_id" "$run" "$repeat_count"
        if ! "$SCRIPT_DIR/cases/${case_id}.sh" "${runner_options[@]}"; then
            printf '[%s] 用例%s执行失败，继续执行后续用例\n' "$(date '+%F %T')" "$case_id" >&2
            suite_status=1
        fi
    done
done

# shellcheck disable=SC1091
if (( ! dry_run )); then
    source "$SCRIPT_DIR/config.env"
    results_root="${RESULTS_ROOT:-$SCRIPT_DIR/results}"
    if ! python3 "$SCRIPT_DIR/aggregate_reports.py" "$results_root"; then
        printf '[%s] 测试结果汇总失败\n' "$(date '+%F %T')" >&2
        suite_status=1
    fi
fi

if (( dry_run )); then
    printf '[%s] JC04视觉资源自动测试流程解析完成，未操作服务、未采集数据\n' "$(date '+%F %T')"
elif (( suite_status == 0 )); then
    printf '[%s] JC04视觉资源自动测试流程完成，所有用例均已执行并完成汇总\n' "$(date '+%F %T')"
else
    printf '[%s] JC04视觉资源自动测试流程完成，但存在失败用例，请查看各结果目录中的test.log和REPORT.md\n' "$(date '+%F %T')" >&2
fi
exit "$suite_status"
