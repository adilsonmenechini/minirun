---
name: healthcheck
description: "System healthcheck — checks uptime, load average, memory, and disk usage"
type: shell
---
# System Healthcheck

Performs basic system health checks and reports status.

```sh
#!/usr/bin/env bash
# Usage: ./healthcheck.sh [--verbose]

set -eo pipefail

VERBOSE=false
if [[ "${1:-}" == "--verbose" ]]; then
    VERBOSE=true
fi

echo "========================================"
echo "   System Healthcheck"
echo "========================================"

# Uptime
uptime_str=$(uptime | sed 's/.*up //' | sed 's/,.*//')
echo "  Uptime:       ${uptime_str}"

# Load average (macOS)
if command -v sysctl >/dev/null 2>&1; then
    load_str=$(sysctl -n vm.loadavg 2>/dev/null || echo "")
fi
if [ -n "${load_str:-}" ]; then
    echo "  Load Avg:     ${load_str}"
fi

# Memory (macOS)
if command -v vm_stat >/dev/null 2>&1; then
    mem_free=$(vm_stat | awk '/Pages free/ {print $3}' | tr -d '.')
    mem_active=$(vm_stat | awk '/^Pages active/ {print $3}' | tr -d '.')
    mem_wired=$(vm_stat | awk '/^Pages wired/ {print $3}' | tr -d '.')
    if [ -n "${mem_free}" ] && [ -n "${mem_active}" ] && [ -n "${mem_wired}" ]; then
        total=$(( mem_active + mem_wired + mem_free ))
        if [ "$total" -gt 0 ]; then
            pct=$(( (total - mem_free) * 100 / total ))
            if [ "$pct" -gt 90 ]; then
                echo "  Memory:       ${pct}% used (HIGH)"
            else
                echo "  Memory:       ${pct}% used"
            fi
        fi
    fi
fi

# Disk
df_out=$(df -h / 2>/dev/null | tail -1)
disk_pct=$(echo "${df_out}" | awk '{print $(NF-1)}' | tr -cd '0-9')
if [ -n "${disk_pct}" ]; then
    if [ "$disk_pct" -gt 90 ]; then
        echo "  Disk (/):      ${disk_pct}% used (HIGH)"
    elif [ "$disk_pct" -gt 80 ]; then
        echo "  Disk (/):      ${disk_pct}% used (WARN)"
    else
        echo "  Disk (/):      ${disk_pct}% used"
    fi
fi

# Verbose
if [ "${VERBOSE}" = true ]; then
    echo
    echo "--- Disk mounts ---"
    df -h | grep -v "^Filesystem"
fi

echo
echo "========================================"
echo "  Healthcheck complete."
echo "========================================"
```
