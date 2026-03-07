#!/usr/bin/env bash
# AutoRepro Flame Graph Profiler for macOS.
#
# Uses the native macOS `sample` profiler plus Brendan Gregg's FlameGraph
# helpers to capture a uvicorn run and render it to SVG.
#
# Usage:
#   ./flamegraph.sh       # Profile for 60 seconds (default)
#   ./flamegraph.sh 120   # Profile for 120 seconds
#   ./flamegraph.sh 0     # Profile until Ctrl+C

set -euo pipefail

cd "$(dirname "$0")"

DURATION="${1:-60}"
PORT="${AUTOREPRO_FLAMEGRAPH_PORT:-8000}"
OUTPUT="${AUTOREPRO_FLAMEGRAPH_OUTPUT:-autorepro_flamegraph.svg}"
RAW_OUTPUT="${AUTOREPRO_SAMPLE_OUTPUT:-autorepro_sample.output}"
SERVER_LOG="${AUTOREPRO_FLAMEGRAPH_SERVER_LOG:-autorepro_flamegraph_server.log}"
SAMPLE_LOG="${AUTOREPRO_FLAMEGRAPH_SAMPLE_LOG:-autorepro_flamegraph_sample.log}"
MODULES="${AUTOREPRO_FLAMEGRAPH_MODULES:-1}"
USE_SUDO="${AUTOREPRO_FLAMEGRAPH_USE_SUDO:-1}"
FLAMEGRAPH_DIR="${AUTOREPRO_FLAMEGRAPH_DIR:-}"

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SERVER_PID=""
SAMPLE_PID=""

echo -e "${CYAN}===============================================${NC}"
echo -e "${CYAN}   AutoRepro Flame Graph Profiler (macOS)${NC}"
echo -e "${CYAN}===============================================${NC}"

die() {
    echo -e "${RED}ERROR:${NC} $*" >&2
    exit 1
}

cleanup() {
    set +e
    if [[ -n "${SAMPLE_PID}" ]] && kill -0 "${SAMPLE_PID}" 2>/dev/null; then
        kill -INT "${SAMPLE_PID}" 2>/dev/null || true
        wait "${SAMPLE_PID}" 2>/dev/null || true
    fi
    if [[ -n "${SERVER_PID}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
        kill "${SERVER_PID}" 2>/dev/null || true
        wait "${SERVER_PID}" 2>/dev/null || true
    fi
}

interrupt_sampling() {
    echo ""
    echo -e "${YELLOW}Stopping sampler and generating flame graph...${NC}"
    if [[ -n "${SAMPLE_PID}" ]] && kill -0 "${SAMPLE_PID}" 2>/dev/null; then
        kill -INT "${SAMPLE_PID}" 2>/dev/null || true
    fi
}

find_flamegraph_dir() {
    local candidates=()

    if [[ -n "${FLAMEGRAPH_DIR}" ]]; then
        candidates+=("${FLAMEGRAPH_DIR}")
    fi

    candidates+=(
        "./tools/FlameGraph"
        "../FlameGraph"
        "$HOME/FlameGraph"
    )

    local candidate
    for candidate in "${candidates[@]}"; do
        if [[ -f "${candidate}/flamegraph.pl" && -f "${candidate}/stackcollapse-sample.awk" ]]; then
            printf '%s\n' "${candidate}"
            return 0
        fi
    done

    return 1
}

wait_for_server() {
    local attempts=0

    while [[ "${attempts}" -lt 30 ]]; do
        if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
            echo -e "${RED}uvicorn exited before profiling started.${NC}" >&2
            if [[ -f "${SERVER_LOG}" ]]; then
                echo -e "${YELLOW}Server log:${NC} ${SERVER_LOG}" >&2
                sed -n '1,120p' "${SERVER_LOG}" >&2 || true
            fi
            return 1
        fi

        if command -v curl >/dev/null 2>&1; then
            if curl -fsS "http://127.0.0.1:${PORT}/" >/dev/null 2>&1; then
                return 0
            fi
        else
            sleep 2
            return 0
        fi

        sleep 1
        attempts=$((attempts + 1))
    done

    echo -e "${YELLOW}Server did not become reachable within 30 seconds.${NC}" >&2
    echo -e "${YELLOW}Continuing anyway; if profiling fails, inspect ${SERVER_LOG}.${NC}" >&2
    return 0
}

[[ "${OSTYPE:-}" == darwin* ]] || die "This script uses macOS 'sample' and only works on macOS."
command -v sample >/dev/null 2>&1 || die "'sample' is missing. Install Xcode Command Line Tools with: xcode-select --install"
command -v awk >/dev/null 2>&1 || die "'awk' is required."
command -v perl >/dev/null 2>&1 || die "'perl' is required."

if [[ ! "${DURATION}" =~ ^[0-9]+$ ]]; then
    die "Duration must be a non-negative integer number of seconds."
fi

FLAMEGRAPH_DIR="$(find_flamegraph_dir)" || die "FlameGraph helpers not found. Set AUTOREPRO_FLAMEGRAPH_DIR or use ./tools/FlameGraph."
STACKCOLLAPSE="${FLAMEGRAPH_DIR}/stackcollapse-sample.awk"
FLAMEGRAPH="${FLAMEGRAPH_DIR}/flamegraph.pl"

if [[ -f "./venv/bin/activate" ]]; then
    echo -e "${GREEN}Activating virtual environment${NC}"
    # shellcheck disable=SC1091
    source "./venv/bin/activate"
fi

PYTHON_BIN="$(command -v python || true)"
if [[ -z "${PYTHON_BIN}" ]]; then
    PYTHON_BIN="$(command -v python3 || true)"
fi
[[ -n "${PYTHON_BIN}" ]] || die "Could not find python or python3 in PATH."

if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    die "Port ${PORT} is already in use. Stop the existing server or set AUTOREPRO_FLAMEGRAPH_PORT."
fi

rm -f "${OUTPUT}" "${RAW_OUTPUT}" "${SERVER_LOG}" "${SAMPLE_LOG}"

trap cleanup EXIT

echo -e "${GREEN}Starting uvicorn on http://127.0.0.1:${PORT}${NC}"
"${PYTHON_BIN}" -m uvicorn api.main:app --host 127.0.0.1 --port "${PORT}" >"${SERVER_LOG}" 2>&1 &
SERVER_PID="$!"

wait_for_server

echo -e "${GREEN}uvicorn PID:${NC} ${SERVER_PID}"
echo -e "${GREEN}FlameGraph helpers:${NC} ${FLAMEGRAPH_DIR}"
echo -e "${YELLOW}Submit bug reports at http://127.0.0.1:${PORT} while sampling is active.${NC}"

SAMPLE_DURATION="${DURATION}"
if [[ "${DURATION}" == "0" ]]; then
    SAMPLE_DURATION="999999"
    echo -e "${YELLOW}Sampling until Ctrl+C. Press Ctrl+C once to stop and render the graph.${NC}"
    trap interrupt_sampling INT TERM
else
    echo -e "${YELLOW}Sampling for ${DURATION} seconds...${NC}"
fi

SAMPLE_CMD=(sample "${SERVER_PID}" "${SAMPLE_DURATION}" 1 -mayDie -file "${RAW_OUTPUT}")
if [[ "${USE_SUDO}" == "1" && "$(id -u)" -ne 0 ]]; then
    echo -e "${YELLOW}macOS often requires sudo to sample Python processes. You may be prompted for your password.${NC}"
    sudo -v || die "sudo authentication failed."
    SAMPLE_CMD=(sudo -n "${SAMPLE_CMD[@]}")
fi

"${SAMPLE_CMD[@]}" >"${SAMPLE_LOG}" 2>&1 &
SAMPLE_PID="$!"

wait "${SAMPLE_PID}" || {
    echo -e "${RED}Sampling failed.${NC}" >&2
    echo -e "${YELLOW}Sample log:${NC} ${SAMPLE_LOG}" >&2
    sed -n '1,120p' "${SAMPLE_LOG}" >&2 || true
    die "Sampling did not complete."
}

trap - INT TERM
SAMPLE_PID=""

[[ -s "${RAW_OUTPUT}" ]] || die "No sample output was generated. Inspect ${SAMPLE_LOG}."

echo -e "${GREEN}Collapsing stacks and rendering SVG...${NC}"
if ! awk -v MODULES="${MODULES}" -f "${STACKCOLLAPSE}" "${RAW_OUTPUT}" \
    | perl "${FLAMEGRAPH}" \
        --title "AutoRepro Flame Graph" \
        --subtitle "uvicorn api.main:app sampled on port ${PORT}" \
        --countname "samples" \
        > "${OUTPUT}"; then
    echo -e "${YELLOW}FlameGraph rendering failed.${NC}" >&2
    echo -e "${YELLOW}The sample likely captured an idle server or no meaningful stacks.${NC}" >&2
    die "Trigger a reproduction during sampling and try again."
fi

[[ -s "${OUTPUT}" ]] || die "SVG generation failed."

echo ""
echo -e "${CYAN}===============================================${NC}"
echo -e "${GREEN}Flame graph saved to:${NC} ${OUTPUT}"
echo -e "${GREEN}Raw sample output:${NC} ${RAW_OUTPUT}"
echo -e "${GREEN}Server log:${NC} ${SERVER_LOG}"
echo -e "${GREEN}Sample log:${NC} ${SAMPLE_LOG}"
echo -e "${CYAN}===============================================${NC}"

if command -v open >/dev/null 2>&1; then
    open "${OUTPUT}" >/dev/null 2>&1 || true
fi
