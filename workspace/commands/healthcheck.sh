#!/usr/bin/env bash
# healthcheck — system health check with ping, disk, memory, CPU, and uptime
#
# Usage:
#   ./healthcheck.sh                        # quick summary
#   ./healthcheck.sh --verbose              # detailed output
#   ./healthcheck.sh --ping-target 1.1.1.1  # custom ping host
#
# Exit codes:
#   0 — all checks pass
#   1 — one or more checks in warning state
#   2 — one or more checks in critical state
#
# Targets: macOS, Linux

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────
PING_TARGET="${PING_TARGET:-8.8.8.8}"
DISK_WARN=80
DISK_CRIT=90
MEM_WARN=80
MEM_CRIT=90
PING_COUNT=2
PING_TIMEOUT=5

EXIT_CODE=0

# ── Colors (noop if not a tty) ──────────────────────────────────────
if [[ -t 1 ]]; then
    RED='\033[0;31m'; YELLOW='\033[1;33m'
    GREEN='\033[0;32m'; BOLD='\033[1m'; NC='\033[0m'
else
    RED=''; YELLOW=''; GREEN=''; BOLD=''; NC=''
fi

# ── Helpers ─────────────────────────────────────────────────────────
pass() { echo -e "  ${GREEN}✔${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; EXIT_CODE=1; }
crit() { echo -e "  ${RED}✘${NC} $1"; EXIT_CODE=2; }
header() { echo -e "\n${BOLD}$1${NC}"; }

# ── Parse args ──────────────────────────────────────────────────────
VERBOSE=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --verbose|-v) VERBOSE=true; shift ;;
        --ping-target) PING_TARGET="$2"; shift 2 ;;
        --help|-h) sed -n '2,10p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "============================================"
echo "  Healthcheck — $(date '+%Y-%m-%d %H:%M:%S')"
echo "  Host: $(uname -n)"
echo "============================================"

# ── 1. Uptime ───────────────────────────────────────────────────────
header "── Uptime ──"
ok=0
if [[ "$(uname)" == "Darwin" ]]; then
    boot=$(sysctl -n kern.boottime 2>/dev/null | awk '{print $4}' | tr -d ',' || true)
    if [[ -n "${boot:-}" ]]; then
        now=$(date +%s)
        uptime_sec=$(( now - boot ))
        d=$(( uptime_sec / 86400 ))
        h=$(( (uptime_sec % 86400) / 3600 ))
        m=$(( (uptime_sec % 3600) / 60 ))
        printf "  Uptime:       %d days, %d hours, %d minutes\n" "$d" "$h" "$m"
        ok=1
    fi
fi
if [[ "$ok" != 1 ]]; then
    uptime_str=$(uptime -p 2>/dev/null || uptime | sed 's/.*up //' | sed 's/,.*//' || true)
    echo "  Uptime:       ${uptime_str:-unknown}"
fi
pass "uptime"

# ── 2. CPU Load ─────────────────────────────────────────────────────
header "── CPU Load ──"
load=$( (uptime 2>/dev/null || echo "") | awk -F'load averages?:' '{print $2}' | cut -d',' -f1 | tr -d ' ' || echo "")
load="${load:-0}"
cpus=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 1)
load_pct=0
if command -v bc &>/dev/null; then
    load_pct=$(echo "scale=0; $load * 100 / $cpus" | bc 2>/dev/null || echo 0)
fi

if [ "${load_pct:-0}" -gt 90 ]; then
    crit "CPU load: ${load} (${load_pct}% of ${cpus} cores) — CRITICAL"
elif [ "${load_pct:-0}" -gt 70 ]; then
    warn "CPU load: ${load} (${load_pct}% of ${cpus} cores) — WARNING"
else
    pass "CPU load: ${load} (${load_pct}% of ${cpus} cores)"
fi

# ── 3. Memory ───────────────────────────────────────────────────────
header "── Memory ──"
mem_total=0; mem_used=0; mem_pct=0

if [[ "$(uname)" == "Darwin" ]] && command -v vm_stat &>/dev/null; then
    raw=$(vm_stat 2>/dev/null || true)
    mem_total=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
    page_size=$(echo "$raw" | awk '/page size of/ {print $8}' | tr -d '.' || echo 4096)
    page_size="${page_size:-4096}"
    pages_active=$(echo "$raw" | awk '/^Pages active/ {print $3}' | tr -d '.' || echo 0)
    pages_wired=$(echo "$raw" | awk '/wired down/ {print $4}' | tr -d '.' || echo 0)
    pages_active="${pages_active:-0}"
    pages_wired="${pages_wired:-0}"
    mem_used=$(( (pages_active + pages_wired) * page_size ))
    if [ "${mem_total:-0}" -gt 0 ]; then
        mem_pct=$(( mem_used * 100 / mem_total ))
    fi
elif [[ -f /proc/meminfo ]]; then
    mem_total=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)
    mem_avail=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)
    mem_total="${mem_total:-0}"; mem_avail="${mem_avail:-0}"
    if [ "${mem_total:-0}" -gt 0 ] && [ "${mem_avail:-0}" -gt 0 ]; then
        mem_used=$(( mem_total - mem_avail ))
        mem_pct=$(( mem_used * 100 / mem_total ))
    fi
fi

if [ "${mem_total:-0}" -gt 0 ]; then
    mem_total_mb=$(( mem_total / 1024 / 1024 ))
    mem_used_mb=$(( mem_used / 1024 / 1024 ))
    if [ "${mem_pct:-0}" -gt "$MEM_CRIT" ]; then
        crit "Memory:       ${mem_used_mb}MB / ${mem_total_mb}MB (${mem_pct}%) — CRITICAL"
    elif [ "${mem_pct:-0}" -gt "$MEM_WARN" ]; then
        warn "Memory:       ${mem_used_mb}MB / ${mem_total_mb}MB (${mem_pct}%) — WARNING"
    else
        pass "Memory:       ${mem_used_mb}MB / ${mem_total_mb}MB (${mem_pct}%)"
    fi
else
    warn "Memory:       unknown"
fi

# ── 4. Disk ─────────────────────────────────────────────────────────
header "── Disk ──"
while IFS= read -r line; do
    mnt=$(echo "$line" | awk '{print $NF}' || true)
    pct=$(echo "$line" | awk '{print $(NF-1)}' | tr -cd '0-9' || true)
    used=$(echo "$line" | awk '{print $(NF-3)}' || true)
    total=$(echo "$line" | awk '{print $(NF-4)}' || true)
    if [[ -n "${pct:-}" && "${pct:-0}" -gt 0 ]] 2>/dev/null; then
        if [ "${pct:-0}" -gt "$DISK_CRIT" ]; then
            crit "Disk ${mnt}: ${used} / ${total} (${pct}%) — CRITICAL"
        elif [ "${pct:-0}" -gt "$DISK_WARN" ]; then
            warn "Disk ${mnt}: ${used} / ${total} (${pct}%) — WARNING"
        else
            pass "Disk ${mnt}: ${used} / ${total} (${pct}%)"
        fi
    fi
done < <(df -h 2>/dev/null | tail -n +2 | grep '^/' || true)

if [ "$VERBOSE" = true ]; then
    while IFS= read -r line; do
        mnt=$(echo "$line" | awk '{print $NF}' || true)
        pct=$(echo "$line" | awk '{print $(NF-1)}' | tr -cd '0-9' || true)
        used=$(echo "$line" | awk '{print $(NF-3)}' || true)
        total=$(echo "$line" | awk '{print $(NF-4)}' || true)
        if [[ -n "${pct:-}" && "${pct:-0}" -gt 0 ]] 2>/dev/null; then
            if [ "${pct:-0}" -gt "$DISK_CRIT" ]; then
                crit "Disk ${mnt}: ${used} / ${total} (${pct}%) — CRITICAL"
            elif [ "${pct:-0}" -gt "$DISK_WARN" ]; then
                warn "Disk ${mnt}: ${used} / ${total} (${pct}%) — WARNING"
            else
                pass "Disk ${mnt}: ${used} / ${total} (${pct}%)"
            fi
        fi
    done < <(df -h 2>/dev/null | tail -n +2 | grep -v '^/' || true)
fi

# ── 5. Ping (network reachability) ──────────────────────────────────
header "── Network ──"
if command -v ping &>/dev/null; then
    if [[ "$(uname)" == "Darwin" ]]; then
        ping_extra="-t ${PING_TIMEOUT}"
    else
        ping_extra="-W ${PING_TIMEOUT}"
    fi
    ping_output=$(ping -c "$PING_COUNT" $ping_extra "$PING_TARGET" 2>&1 || true)
    ping_exit=$?

    if [ "$ping_exit" -eq 0 ]; then
        latency=$(echo "$ping_output" | tail -1 | awk -F'/' '{print $5}' || true)
        if [[ -n "${latency:-}" ]]; then
            lat_int="${latency%.*}"
            lat_int="${lat_int:-0}"
            if [ "$lat_int" -gt 200 ]; then
                warn "Ping ${PING_TARGET}: ${latency}ms — HIGH LATENCY"
            elif [ "$lat_int" -gt 100 ]; then
                warn "Ping ${PING_TARGET}: ${latency}ms — elevated"
            else
                pass "Ping ${PING_TARGET}: ${latency}ms"
            fi
        else
            pass "Ping ${PING_TARGET}: reachable"
        fi
    else
        crit "Ping ${PING_TARGET}: unreachable — CRITICAL"
    fi
else
    warn "Ping: command not found"
fi

# ── Summary ─────────────────────────────────────────────────────────
echo
echo "============================================"
if [ "$EXIT_CODE" -eq 0 ]; then
    echo -e "  ${GREEN}All checks passed${NC}"
elif [ "$EXIT_CODE" -eq 1 ]; then
    echo -e "  ${YELLOW}Warning(s) detected${NC}"
else
    echo -e "  ${RED}Critical issue(s) found${NC}"
fi
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"

exit "$EXIT_CODE"
