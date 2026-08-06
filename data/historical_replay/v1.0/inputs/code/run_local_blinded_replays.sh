#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CASE_ROOT="${SCRIPT_DIR}/cases"
PROMPT="${SCRIPT_DIR}/benchmark_prompt.md"
SCHEMA="${SCRIPT_DIR}/decision_schema.json"
RESULT_ROOT="${SCRIPT_DIR}/runs"
TMP_ROOT="${TMPDIR:-/tmp}/md_gcmc_historical_event_replay"

PRIMARY_CASES=(
  "k_rh03_absolute_timestep_budget"
  "stale_rh07_smoke_artifact"
)

MAX_CODEX_CALLS=2

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

json_quote() {
  python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"
}

write_blocker() {
  local bin_dir="$1"
  mkdir -p "$bin_dir"
  for name in lmp lmp_serial lmp_mpi lammps mpirun mpiexec qsub sbatch srun; do
    cat > "${bin_dir}/${name}" <<'BLOCK'
#!/usr/bin/env bash
echo "Simulation or scheduler command is blocked in blinded replay workspace: ${0}" >&2
exit 126
BLOCK
    chmod +x "${bin_dir}/${name}"
  done
}

scan_case_for_leakage() {
  local case_dir="$1"
  local case_id="$2"
  local scan_pattern='(/home/[^\s"'"'"']+|sk-[A-Za-z0-9_-]+|OPENAI_API_KEY|api[_-]?key|token|password|passwd|secret|Bearer [A-Za-z0-9._-]+|ghp_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|AKIA[0-9A-Z]{16})'
  if grep -RInE "${scan_pattern}" "${case_dir}" "${PROMPT}" "${SCHEMA}" >${HISTORICAL_TMP}/blinded_replay_leakage_hits.txt 2>/dev/null; then
    cat ${HISTORICAL_TMP}/blinded_replay_leakage_hits.txt >&2
    fail "confidentiality scan failed for ${case_id}"
  fi
  if grep -RInE '(ground_truth|true_incident_class|correct_root_cause)' "${case_dir}/agent_event.json" "${case_dir}/evidence_bundle.json" "${case_dir}/evidence" "${PROMPT}" "${SCHEMA}" >${HISTORICAL_TMP}/blinded_replay_answer_hits.txt 2>/dev/null; then
    cat ${HISTORICAL_TMP}/blinded_replay_answer_hits.txt >&2
    fail "answer-leakage scan failed for ${case_id}"
  fi
}

preflight() {
  command -v codex >/dev/null 2>&1 || fail "codex CLI not found in PATH"
  command -v python3 >/dev/null 2>&1 || fail "python3 not found in PATH"
  [[ -f "${PROMPT}" ]] || fail "missing benchmark prompt: ${PROMPT}"
  [[ -f "${SCHEMA}" ]] || fail "missing decision schema: ${SCHEMA}"
  [[ "${#PRIMARY_CASES[@]}" -eq "${MAX_CODEX_CALLS}" ]] || fail "case count does not match MAX_CODEX_CALLS"

  for case_id in "${PRIMARY_CASES[@]}"; do
    local case_dir="${CASE_ROOT}/${case_id}"
    [[ -d "${case_dir}" ]] || fail "missing case directory: ${case_dir}"
    [[ -f "${case_dir}/agent_event.json" ]] || fail "missing agent_event.json for ${case_id}"
    [[ -f "${case_dir}/evidence_bundle.json" ]] || fail "missing evidence_bundle.json for ${case_id}"
    [[ -d "${case_dir}/evidence" ]] || fail "missing evidence directory for ${case_id}"
    if find "${case_dir}" -type l | grep -q .; then
      find "${case_dir}" -type l >&2
      fail "symlinks are not allowed in blinded case bundle: ${case_id}"
    fi
    scan_case_for_leakage "${case_dir}" "${case_id}"
  done
}

copy_case_bundle() {
  local case_id="$1"
  local work_dir="$2"
  local case_dir="${CASE_ROOT}/${case_id}"

  mkdir -p "${work_dir}"
  cp "${case_dir}/agent_event.json" "${work_dir}/agent_event.json"
  cp "${case_dir}/evidence_bundle.json" "${work_dir}/evidence_bundle.json"
  cp -R "${case_dir}/evidence" "${work_dir}/evidence"
  cp "${PROMPT}" "${work_dir}/benchmark_prompt.md"
  cp "${SCHEMA}" "${work_dir}/decision_schema.json"
  write_blocker "${work_dir}/blocked_bin"

  if find "${work_dir}" -type l | grep -q .; then
    find "${work_dir}" -type l >&2
    fail "isolated workspace contains symlinks: ${work_dir}"
  fi
  if find "${work_dir}" -iname '*ground_truth*' -o -iname '*score*' -o -name 'case_manifest.json' | grep -q .; then
    find "${work_dir}" -iname '*ground_truth*' -o -iname '*score*' -o -name 'case_manifest.json' >&2
    fail "isolated workspace contains forbidden benchmark files: ${work_dir}"
  fi
}

run_one_case() {
  local case_id="$1"
  local run_dir="$2"
  local call_index="$3"
  local work_dir="${TMP_ROOT}/${case_id}"
  local out_dir="${run_dir}/${case_id}"
  local start_epoch end_epoch rc runtime_sec decision_valid prompt_text

  rm -rf "${work_dir}"
  copy_case_bundle "${case_id}" "${work_dir}"
  prompt_text="$(cat "${work_dir}/benchmark_prompt.md")"

  start_epoch="$(date +%s)"
  set +e
  (
    cd "${work_dir}"
    PATH="${work_dir}/blocked_bin:${PATH}" \
      codex exec \
        --skip-git-repo-check \
        --ignore-rules \
        --ephemeral \
        --sandbox workspace-write \
        --output-schema "${work_dir}/decision_schema.json" \
        --output-last-message "${work_dir}/child_last_message.txt" \
        "${prompt_text}" \
        > "${work_dir}/child_stdout.txt" \
        2> "${work_dir}/child_stderr.txt"
  )
  rc=$?
  set -e
  end_epoch="$(date +%s)"
  runtime_sec="$((end_epoch - start_epoch))"

  mkdir -p "${out_dir}"
  cp -R "${work_dir}/." "${out_dir}/"
  rm -rf "${work_dir}"

  decision_valid="false"
  if [[ -f "${out_dir}/agent_decision.json" ]]; then
    if python3 -m json.tool "${out_dir}/agent_decision.json" >/dev/null 2>&1; then
      decision_valid="true"
    fi
  fi

  {
    printf '{'
    printf '"case_id":%s,' "$(json_quote "${case_id}")"
    printf '"call_index":%s,' "$(json_quote "${call_index}")"
    printf '"return_code":%s,' "$(json_quote "${rc}")"
    printf '"runtime_seconds":%s,' "$(json_quote "${runtime_sec}")"
    printf '"decision_json_present":%s,' "$(json_quote "$([[ -f "${out_dir}/agent_decision.json" ]] && echo true || echo false)")"
    printf '"decision_json_valid":%s,' "$(json_quote "${decision_valid}")"
    printf '"output_dir":%s' "$(json_quote "${out_dir}")"
    printf '}\n'
  } >> "${run_dir}/run_records.jsonl"
}

main() {
  preflight

  local run_id run_dir calls
  run_id="$(date -u +%Y%m%dT%H%M%SZ)"
  run_dir="${RESULT_ROOT}/${run_id}"
  calls=0

  rm -rf "${TMP_ROOT}"
  mkdir -p "${TMP_ROOT}" "${run_dir}"
  : > "${run_dir}/run_records.jsonl"

  for case_id in "${PRIMARY_CASES[@]}"; do
    if [[ "${calls}" -ge "${MAX_CODEX_CALLS}" ]]; then
      fail "maximum child Codex call cap reached before all primary cases completed"
    fi
    calls="$((calls + 1))"
    run_one_case "${case_id}" "${run_dir}" "${calls}"
  done

  [[ "${calls}" -eq "${MAX_CODEX_CALLS}" ]] || fail "expected exactly ${MAX_CODEX_CALLS} child Codex calls, got ${calls}"
  rm -rf "${TMP_ROOT}"
  rm -f "${RESULT_ROOT}/latest"
  ln -s "${run_dir}" "${RESULT_ROOT}/latest"

  python3 - <<PY > "${run_dir}/run_summary.json"
import json
from pathlib import Path
records = [json.loads(line) for line in Path("${run_dir}/run_records.jsonl").read_text().splitlines() if line.strip()]
print(json.dumps({
    "run_id": "${run_id}",
    "run_dir": "${run_dir}",
    "primary_case_count": len(records),
    "max_codex_calls": ${MAX_CODEX_CALLS},
    "codex_calls_performed": ${calls},
    "cases": records,
    "scoring_command": "python3 ${SCRIPT_DIR}/score_local_replays.py --run-dir ${run_dir}",
}, indent=2, sort_keys=True))
PY

  echo "Blinded replay run complete: ${run_dir}"
  echo "Scoring command:"
  echo "python3 ${SCRIPT_DIR}/score_local_replays.py --run-dir ${run_dir}"
}

main "$@"
