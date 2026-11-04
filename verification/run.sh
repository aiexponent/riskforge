#!/usr/bin/env bash
# RiskForge independent verification: one command.
#
#   verification/run.sh                 run in Docker with the pinned versions
#   verification/run.sh --no-docker     same, in a throwaway venv (needs Python 3.11+ and,
#                                       for PDF export, the WeasyPrint system libraries)
#   verification/run.sh --version X.Y.Z test another released version (no hash pins)
#   verification/run.sh --smoke         use the made-up inputs in tests/fixtures/smoke-inputs
#   verification/run.sh --out DIR       where to write everything (default: a new temp dir)
#   verification/run.sh --update        copy the results into verification/results/ (also
#                                       after a failed check, which is a result too; the
#                                       baseline rmf.normalised.json only when all pass)
#
# Nothing is written into the checkout unless --update is given.
# Exit codes: 0 every check passed (and the RMF matches results/rmf.normalised.json if committed),
#             1 every check passed, but the RMF differs from results/rmf.normalised.json,
#             2 a check failed (install, a command, digest, repeatability, tamper, export),
#             3 inputs/decisions.yaml is missing: the risk list is printed so it can be written.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_TAG="riskforge-verification:local"

docker_mode=1
inside=0
update=0
force=0
smoke=0
version=""
out=""

while [ $# -gt 0 ]; do
  case "$1" in
    --no-docker) docker_mode=0 ;;
    --inside) inside=1 ;;
    --update) update=1 ;;
    --force) force=1 ;;
    --smoke) smoke=1 ;;
    --version) version="${2:-}"; shift ;;
    --out) out="${2:-}"; shift ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "Error: unknown option $1 (see --help)" >&2; exit 2 ;;
  esac
  shift
done

if [ -n "$version" ] && ! [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+((a|b|rc)[0-9]+)?$ ]]; then
  echo "Error: --version must look like 1.2.3, got '$version'" >&2
  exit 2
fi
if [ "$smoke" -eq 1 ] && [ "$update" -eq 1 ]; then
  echo "Error: --update keeps results of the real inputs only, not --smoke" >&2
  exit 2
fi

if [ "$smoke" -eq 1 ]; then
  inputs="$HERE/tests/fixtures/smoke-inputs"
else
  inputs="$HERE/inputs"
  if [ ! -f "$inputs/system.yaml" ]; then
    echo "Error: no verification/inputs/system.yaml yet; use --smoke for the made-up inputs" >&2
    exit 2
  fi
fi

if [ -z "$out" ]; then
  out="$(mktemp -d "${TMPDIR:-/tmp}/riskforge-verification.XXXXXX")"
elif [ -e "$out" ] && [ -n "$(ls -A "$out" 2>/dev/null)" ] && [ "$inside" -eq 0 ]; then
  if [ "$force" -eq 0 ]; then
    echo "Error: $out is not empty; pass --force to empty it and reuse it" >&2
    exit 2
  fi
  find "$out" -mindepth 1 -delete
fi
mkdir -p "$out"
# An absolute path, so Docker bind-mounts the folder and never creates a named volume.
out="$(cd "$out" && pwd)"

run_checks() {
  # Build an isolated environment beside $out, install, replay, compare.
  # Called as `run_checks || status=$?`, so set -e is off in here: check each step.
  local venv
  venv="$(mktemp -d "${TMPDIR:-/tmp}/riskforge-venv.XXXXXX")"
  python3 -m venv "$venv" || { echo "Error: could not create the venv" >&2; return 2; }
  if [ -n "$version" ]; then
    echo "Testing riskforge==$version (not hash-pinned; the lock pins the published version)."
    PIP_DISABLE_PIP_VERSION_CHECK=1 "$venv/bin/pip" install --quiet --no-cache-dir "riskforge==$version" "pypdf==6.21.4" \
      || { echo "Error: install of riskforge==$version failed" >&2; return 2; }
  else
    PIP_DISABLE_PIP_VERSION_CHECK=1 "$venv/bin/pip" install --quiet --no-cache-dir --require-hashes -r "$HERE/requirements.lock" \
      || { echo "Error: install from requirements.lock failed" >&2; return 2; }
  fi
  local baseline=()
  if [ "$smoke" -eq 0 ] && [ -f "$HERE/results/rmf.normalised.json" ]; then
    baseline=(--baseline "$HERE/results/rmf.normalised.json")
  fi
  local rc=0
  "$venv/bin/python" -I "$HERE/replay.py" --inputs "$inputs" --out "$out" \
    --riskforge "$venv/bin/riskforge" ${baseline[@]+"${baseline[@]}"} || rc=$?
  rm -rf "$venv"
  return "$rc"
}

smoke_flag=""
[ "$smoke" -eq 1 ] && smoke_flag="--smoke"

status=0
if [ "$inside" -eq 1 ] || [ "$docker_mode" -eq 0 ]; then
  run_checks || status=$?
else
  command -v docker >/dev/null || { echo "Error: docker not found; use --no-docker" >&2; exit 2; }
  # Built with no context: the Dockerfile copies nothing in.
  docker build --quiet -t "$IMAGE_TAG" - < "$HERE/Dockerfile" >/dev/null \
    || { echo "Error: docker build failed" >&2; exit 2; }
  docker run --rm \
    --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$HERE:/verification:ro" -v "$out:/out" \
    "$IMAGE_TAG" bash /verification/run.sh --inside --out /out \
      ${version:+--version "$version"} ${smoke_flag:+"$smoke_flag"} \
    || status=$?
fi

echo "Results: $out/results.json"
# A failed check is a result too, so --update keeps its evidence and the exit code still
# reports it. Only a run where every check passed (exit 0, or 1 for an RMF that changed)
# replaces the baseline, rmf.normalised.json, so a failed run never becomes the expected one.
# A file this run did not produce is removed from results/, so no file from an older run is
# left beside the new results.json.
if [ "$update" -eq 1 ] && [ "$status" -le 2 ] && [ -f "$out/results.json" ]; then
  mkdir -p "$HERE/results"
  for f in results.json run-a/export/rmf.json run-a/export/rmf.md run-a/export/rmf.pdf \
           run-a/risk-list.txt; do
    if [ -f "$out/$f" ]; then
      cp "$out/$f" "$HERE/results/"
    else
      rm -f "$HERE/results/$(basename "$f")"
    fi
  done
  if [ "$status" -le 1 ] && [ -f "$out/rmf.normalised.json" ]; then
    cp "$out/rmf.normalised.json" "$HERE/results/"
    echo "Updated verification/results/, including the baseline rmf.normalised.json"
    status=0
  else
    echo "Updated verification/results/ with the failed run; the baseline is unchanged"
  fi
fi
exit "$status"
