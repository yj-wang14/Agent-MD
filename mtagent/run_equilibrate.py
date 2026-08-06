#!/usr/bin/env python3
"""
Generate and optionally run pre-GCMC equilibration from prepared LAMMPS data.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mtagent import generate_gcmc_input, local_runner


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_case_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"case.yaml not found: {path}")
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise SystemExit("PyYAML is required to read case.yaml") from exc
    with path.open("r") as f:
        data = yaml.safe_load(f)
    return data or {}


def get_nested(cfg: Dict[str, Any], keys: list[str], default: Any) -> Any:
    cur: Any = cfg
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def resolve_path(path_value: str | Path, base_dir: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def lammps_path(path: Path) -> str:
    return str(path.resolve())


def topology_extra_settings(case_cfg: Dict[str, Any]) -> Dict[str, int]:
    equil_cfg = case_cfg.get("equilibration", {})
    if not isinstance(equil_cfg, dict):
        equil_cfg = {}
    return {
        "extra_bond_per_atom": int(equil_cfg.get("extra_bond_per_atom", 2)),
        "extra_angle_per_atom": int(equil_cfg.get("extra_angle_per_atom", 1)),
        "extra_special_per_atom": int(equil_cfg.get("extra_special_per_atom", 2)),
    }


def read_data_with_topology_extra(data_path: Path, topology_extra: Dict[str, int]) -> str:
    return (
        f"read_data {lammps_path(data_path)} &\n"
        f"  extra/bond/per/atom {topology_extra['extra_bond_per_atom']} &\n"
        f"  extra/angle/per/atom {topology_extra['extra_angle_per_atom']} &\n"
        f"  extra/special/per/atom {topology_extra['extra_special_per_atom']}"
    )


def bool_setting(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def build_paths(case_cfg: Dict[str, Any], case_path: Path, run_dir_override: Path | None = None) -> Dict[str, Path]:
    base_dir = case_path.parent.resolve()
    paths_cfg = case_cfg.get("paths", {})
    if not isinstance(paths_cfg, dict):
        paths_cfg = {}
    equil_cfg = case_cfg.get("equilibration", {})
    if not isinstance(equil_cfg, dict):
        equil_cfg = {}

    example_dir = resolve_path(paths_cfg.get("example_dir", "examples/Mt_Oct050_Na"), base_dir)
    prepared_dir = resolve_path(paths_cfg.get("prepared_dir", example_dir / "inputs"), base_dir)
    model = str(get_nested(case_cfg, ["structure", "claycode_model"], "MyMont-1_5_4"))
    run_dir = (
        resolve_path(run_dir_override, base_dir)
        if run_dir_override is not None
        else resolve_path(equil_cfg.get("run_dir", example_dir / "equilibration"), base_dir)
    )
    output_data = resolve_path(equil_cfg.get("output_data", prepared_dir / f"{model}_equilibrated.data"), base_dir)
    output_restart = resolve_path(equil_cfg.get("output_restart", prepared_dir / "restart.pre_gcmc.final"), base_dir)

    return {
        "example_dir": example_dir,
        "prepared_dir": prepared_dir,
        "prepared_data": prepared_dir / f"{model}_prepared.data",
        "groups_regions": prepared_dir / f"{model}_groups_regions.inc",
        "run_dir": run_dir,
        "input": run_dir / "in.equilibrate_pre_gcmc",
        "monitor": run_dir / "monitor_equilibrate_basal.dat",
        "output_data": output_data,
        "output_restart": output_restart,
        "diagnostics": example_dir / "generated" / f"{model}.run_equilibrate_diagnostics.json",
    }


def validate_inputs(paths: Dict[str, Path]) -> None:
    for label, path in [
        ("prepared LAMMPS data", paths["prepared_data"]),
        ("groups/regions include", paths["groups_regions"]),
    ]:
        if not path.exists():
            raise FileNotFoundError(f"Missing {label}: {path}")
        if not path.is_file():
            raise FileNotFoundError(f"Expected {label} to be a file: {path}")


def generate_equilibration_input(
    case_cfg: Dict[str, Any],
    prepared_data: Path,
    groups_regions: Path,
    output_data: Path,
    output_restart: Path,
    steps_override: int | None = None,
    soft_steps_override: int | None = None,
) -> tuple[str, int, int, Dict[str, int], bool]:
    equil_cfg = case_cfg.get("equilibration", {})
    if not isinstance(equil_cfg, dict):
        equil_cfg = {}

    temp = float(get_nested(case_cfg, ["case", "temperature"], get_nested(case_cfg, ["md", "temperature"], 300.0)))
    timestep_fs = float(get_nested(case_cfg, ["md", "timestep_fs"], 1.0))
    tdamp = float(equil_cfg.get("tdamp", get_nested(case_cfg, ["md", "tdamp"], 100.0)))
    velocity_seed = int(equil_cfg.get("velocity_seed", get_nested(case_cfg, ["md", "velocity_seed"], 4928459)))
    nve_limit = float(equil_cfg.get("nve_limit", 0.05))
    soft_start_steps = int(equil_cfg.get("soft_start_steps", 5000))
    nvt_steps = int(equil_cfg.get("nvt_steps", 100000))
    hold_clay_z = bool_setting(equil_cfg.get("hold_clay_z_during_soft_start"), True)
    if soft_steps_override is not None:
        soft_start_steps = soft_steps_override
    if steps_override is not None:
        nvt_steps = steps_override

    pair_style = str(get_nested(case_cfg, ["md", "pair_style"], "lj/cut/coul/long 12.0"))
    kspace_style = str(get_nested(case_cfg, ["md", "kspace_style"], "pppm 1.0e-4"))
    neigh_modify = generate_gcmc_input.neighbor_modify_line(case_cfg)
    thermo_interval = int(get_nested(case_cfg, ["md", "thermo_interval"], 5000))
    monitor_interval = int(get_nested(case_cfg, ["md", "monitor_interval"], 1000))
    topology_extra = topology_extra_settings(case_cfg)
    read_data_line = read_data_with_topology_extra(prepared_data, topology_extra)
    if hold_clay_z:
        rigid_soft_lines = (
            "# Rigid clay sheets during soft-start: hold z fixed while mobile close contacts relax.\n"
            "fix rigid_clay_soft clay rigid/nve molecule force * off off off torque * off off off"
        )
    else:
        rigid_soft_lines = (
            "# Rigid clay sheets during soft-start: legacy behavior, z-translation allowed.\n"
            "fix rigid_clay_soft clay rigid/nve molecule force * off off on torque * off off off"
        )

    text = f"""# Auto-generated pre-GCMC equilibration input
# Generated by mtagent/run_equilibrate.py
# Prepared data = {lammps_path(prepared_data)}

variable temp equal {temp}
variable seed equal {velocity_seed}

units real
atom_style full
boundary p p p

pair_style {pair_style}
pair_modify mix arithmetic
bond_style harmonic
angle_style harmonic
special_bonds lj/coul 0.0 0.0 0.5

{read_data_line}
include {lammps_path(groups_regions)}

kspace_style {kspace_style}

neighbor 2.0 bin
neigh_modify {neigh_modify}

timestep {timestep_fs}

group clay union clay_lower clay_upper
group mobile union water sodium

# clay molecule IDs are normalized: lower=1, upper=2
velocity clay set 0.0 0.0 0.0

# Exclude only intra-sheet nonbonded interactions.
neigh_modify exclude group clay_lower clay_lower
neigh_modify exclude group clay_upper clay_upper

# Mobile phase only: water + exchangeable ions through the sodium-compatible alias.
fix wshake water shake 1.0e-4 50 0 b 1 a 1
fix mom_water water momentum 100 linear 1 1 1
fix mom_ions sodium momentum 100 linear 1 1 1
compute_modify thermo_temp dynamic/dof yes

compute zlow clay_lower reduce ave z
compute zup clay_upper reduce ave z
variable zlow_now equal c_zlow
variable zup_now equal c_zup
variable basal_proxy equal v_zup_now-v_zlow_now
variable zcenter equal 0.5*(v_zlow_now+v_zup_now)
variable temp_inst equal temp
variable pe_inst equal pe

thermo {thermo_interval}
thermo_style custom step temp pe ke etotal press atoms v_zlow_now v_zup_now v_basal_proxy v_zcenter

fix basal_mon all ave/time {monitor_interval} 1 {monitor_interval} &
  v_zlow_now v_zup_now v_basal_proxy v_zcenter v_temp_inst v_pe_inst &
  file monitor_equilibrate_basal.dat

velocity mobile create ${{temp}} ${{seed}} mom yes rot yes dist gaussian

# Soft-start mobile atoms before NVT.
{rigid_soft_lines}
fix lim mobile nve/limit {nve_limit}
run {soft_start_steps}
unfix lim
unfix rigid_clay_soft

# Production rigid clay sheets: z-translation allowed after soft-start, no x/y motion, no rotation.
fix rigid_clay clay rigid/nve molecule force * off off on torque * off off off

# Pre-GCMC NVT equilibration for mobile atoms only.
fix nvt_mobile mobile nvt temp ${{temp}} ${{temp}} {tdamp}
run {nvt_steps}
unfix nvt_mobile
unfix basal_mon

write_data {lammps_path(output_data)}
write_restart {lammps_path(output_restart)}
"""
    return text, soft_start_steps, nvt_steps, topology_extra, hold_clay_z


def write_text_if_new_or_same(path: Path, text: str, force: bool = False) -> None:
    if path.exists() and path.read_text() != text and not force:
        raise FileExistsError(f"Refusing to overwrite existing input file with different content: {path}")
    path.write_text(text)


def write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, indent=2))


def find_collision_files(run_dir: Path, output_data: Path, output_restart: Path) -> List[Path]:
    collisions: List[Path] = []
    if run_dir.exists():
        for pattern in ["log.lammps", "restart*"]:
            collisions.extend(sorted(p for p in run_dir.glob(pattern) if p.is_file()))
    for path in [output_data, output_restart]:
        if path.exists() and path.is_file():
            collisions.append(path)
    return collisions


def run_lammps(
    case_cfg: Dict[str, Any],
    run_dir: Path,
    input_path: Path,
    np: int | None,
    status: Dict[str, Any],
) -> int:
    command = local_runner.build_command(case_cfg, np=np, input_file=input_path.name, no_mpi=False)
    stdout_path = run_dir / f"{input_path.name}.stdout"
    stderr_path = run_dir / f"{input_path.name}.stderr"

    status["runner"] = {
        "status": "running",
        "cwd": str(run_dir),
        "run_dir": str(run_dir),
        "command": command,
        "command_string": " ".join(shlex.quote(x) for x in command),
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "started_at": now_iso(),
        "finished_at": None,
        "elapsed_seconds": None,
        "return_code": None,
    }
    t0 = time.time()
    with stdout_path.open("w") as fout, stderr_path.open("w") as ferr:
        proc = subprocess.run(command, cwd=run_dir, stdout=fout, stderr=ferr, text=True)
    elapsed = time.time() - t0

    status["runner"]["finished_at"] = now_iso()
    status["runner"]["elapsed_seconds"] = elapsed
    status["runner"]["return_code"] = proc.returncode
    status["runner"]["status"] = "completed" if proc.returncode == 0 else "failed"
    return proc.returncode




def basal_from_lammps_data(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "path": str(path)}
    in_atoms = False
    lower: list[float] = []
    upper: list[float] = []
    try:
        lines = path.read_text(errors="ignore").splitlines()
    except OSError as exc:
        return {"status": "failed", "path": str(path), "error": str(exc)}
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("Atoms"):
            in_atoms = True
            continue
        if in_atoms and stripped[0].isalpha():
            break
        if not in_atoms:
            continue
        parts = stripped.split()
        if len(parts) < 7:
            continue
        try:
            mol = int(parts[1])
            z = float(parts[6])
        except ValueError:
            continue
        if mol == 1:
            lower.append(z)
        elif mol == 2:
            upper.append(z)
    if not lower or not upper:
        return {
            "status": "failed",
            "path": str(path),
            "error": "missing clay molecule 1 or 2 atoms",
            "lower_count": len(lower),
            "upper_count": len(upper),
        }
    zlow = sum(lower) / len(lower)
    zup = sum(upper) / len(upper)
    return {
        "status": "ok",
        "path": str(path),
        "lower_count": len(lower),
        "upper_count": len(upper),
        "zlow": zlow,
        "zup": zup,
        "basal_proxy": zup - zlow,
        "zcenter": 0.5 * (zlow + zup),
        "lower_min": min(lower),
        "lower_max": max(lower),
        "upper_min": min(upper),
        "upper_max": max(upper),
    }


def handoff_basal_diagnostics(
    prepared_data: Path,
    equilibrated_data: Path,
    *,
    warning_threshold: float = 3.0,
    failed_threshold: float = 10.0,
) -> Dict[str, Any]:
    prepared = basal_from_lammps_data(prepared_data)
    equilibrated = basal_from_lammps_data(equilibrated_data)
    errors: list[str] = []
    warnings: list[str] = []
    drift = None
    abs_drift = None
    status = "ok"
    if prepared.get("status") != "ok":
        errors.append("unable to compute prepared basal proxy")
    if equilibrated.get("status") != "ok":
        errors.append("unable to compute equilibrated basal proxy")
    if not errors:
        drift = float(equilibrated["basal_proxy"]) - float(prepared["basal_proxy"])
        abs_drift = abs(drift)
        if abs_drift > failed_threshold:
            status = "failed"
            errors.append(f"handoff basal drift {drift:.3f} A exceeds failed threshold {failed_threshold:.3f} A")
        elif abs_drift > warning_threshold:
            status = "warning"
            warnings.append(f"handoff basal drift {drift:.3f} A exceeds warning threshold {warning_threshold:.3f} A")
    else:
        status = "failed"
    return {
        "status": status,
        "handoff_status": status,
        "prepared": prepared,
        "equilibrated": equilibrated,
        "handoff_basal_prepared": prepared.get("basal_proxy"),
        "handoff_basal_equilibrated": equilibrated.get("basal_proxy"),
        "handoff_basal_drift": drift,
        "handoff_basal_abs_drift": abs_drift,
        "warning_threshold_A": warning_threshold,
        "failed_threshold_A": failed_threshold,
        "errors": errors,
        "warnings": warnings,
        "recommendation": "Do not use this pre-GCMC handoff for production." if status == "failed" else "Review before production use." if status == "warning" else "Pre-GCMC basal handoff is within tolerance.",
    }

def collect_output_validation(run_dir: Path, output_data: Path, output_restart: Path) -> Dict[str, Any]:
    missing = []
    if not (run_dir / "log.lammps").exists():
        missing.append("log.lammps")
    if not output_data.exists():
        missing.append(str(output_data))
    if not output_restart.exists():
        missing.append(str(output_restart))
    return {"missing_outputs": missing}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, default=Path("case.yaml"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--write-input", action="store_true")
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--np", type=int, default=None)
    parser.add_argument("--steps-override", type=int, default=None, help="Override NVT equilibration steps.")
    parser.add_argument("--soft-steps-override", type=int, default=None, help="Override soft-start steps.")
    args = parser.parse_args()

    if args.dry_run and args.run:
        raise SystemExit("Use either --dry-run or --run, not both.")
    if args.steps_override is not None and args.steps_override <= 0:
        raise SystemExit("--steps-override must be a positive integer.")
    if args.soft_steps_override is not None and args.soft_steps_override <= 0:
        raise SystemExit("--soft-steps-override must be a positive integer.")

    case_path = args.case.resolve()
    case_cfg = load_case_yaml(case_path)
    paths = build_paths(case_cfg, case_path, run_dir_override=args.run_dir)
    validate_inputs(paths)

    collision_files = find_collision_files(paths["run_dir"], paths["output_data"], paths["output_restart"])
    collision_warning = None
    if collision_files:
        collision_warning = (
            f"Equilibration outputs already exist for {paths['run_dir']}. "
            "Use --force only when intentionally replacing this validation/formal output."
        )
        if args.run and not args.force:
            raise SystemExit(collision_warning)

    should_write_input = args.run or args.write_input
    paths["run_dir"].mkdir(parents=True, exist_ok=True)
    paths["output_data"].parent.mkdir(parents=True, exist_ok=True)
    paths["output_restart"].parent.mkdir(parents=True, exist_ok=True)
    paths["diagnostics"].parent.mkdir(parents=True, exist_ok=True)

    input_text, soft_start_steps, nvt_steps, topology_extra, hold_clay_z = generate_equilibration_input(
        case_cfg=case_cfg,
        prepared_data=paths["prepared_data"],
        groups_regions=paths["groups_regions"],
        output_data=paths["output_data"],
        output_restart=paths["output_restart"],
        steps_override=args.steps_override,
        soft_steps_override=args.soft_steps_override,
    )
    input_file_written = False
    if should_write_input:
        write_text_if_new_or_same(paths["input"], input_text, force=args.force)
        input_file_written = True

    status_path = paths["run_dir"] / ("equilibration_status.preview.json" if args.dry_run else "equilibration_status.json")
    status: Dict[str, Any] = {
        "status": "dry_run" if args.dry_run else "generated",
        "dry_run": args.dry_run,
        "run_requested": args.run,
        "case": str(case_path),
        "run_dir": str(paths["run_dir"]),
        "input_file": str(paths["input"]),
        "input_file_written": input_file_written,
        "write_input": args.write_input,
        "force": args.force,
        "prepared_data": str(paths["prepared_data"]),
        "groups_regions": str(paths["groups_regions"]),
        "output_data": str(paths["output_data"]),
        "output_restart": str(paths["output_restart"]),
        "monitor_file": str(paths["monitor"]),
        "diagnostics_file": str(paths["diagnostics"]),
        "soft_start_steps": soft_start_steps,
        "hold_clay_z_during_soft_start": hold_clay_z,
        "nvt_steps": nvt_steps,
        "run_line_soft": f"run {soft_start_steps}",
        "run_line_nvt": f"run {nvt_steps}",
        "neighbor_settings": generate_gcmc_input.neighbor_settings(case_cfg),
        "neigh_modify": generate_gcmc_input.neighbor_modify_line(case_cfg),
        "topology_extra": topology_extra,
        "status_file": str(status_path),
        "started_at": now_iso(),
        "finished_at": None,
        "collision_files": [str(p) for p in collision_files],
        "warnings": [collision_warning] if collision_warning else [],
    }

    if args.run:
        status["status"] = "running"
        write_json(status_path, status)
        rc = run_lammps(case_cfg, paths["run_dir"], paths["input"], args.np, status)
        if rc == 0:
            validation = collect_output_validation(paths["run_dir"], paths["output_data"], paths["output_restart"])
            status["missing_outputs"] = validation["missing_outputs"]
            if status["missing_outputs"]:
                status["status"] = "failed_outputs_missing"
            else:
                diagnostics = handoff_basal_diagnostics(paths["prepared_data"], paths["output_data"])
                write_json(paths["diagnostics"], diagnostics)
                status["handoff_diagnostics"] = diagnostics
                status["handoff_status"] = diagnostics["handoff_status"]
                status["status"] = "failed_handoff" if diagnostics["status"] == "failed" else "completed"
        else:
            status["status"] = "failed"
        status["finished_at"] = now_iso()
        write_json(status_path, status)
        print(json.dumps(status, indent=2))
        if rc != 0:
            raise SystemExit(rc)
        if status["status"] == "failed_outputs_missing":
            raise SystemExit("LAMMPS returned successfully but expected equilibration output files are missing.")
        if status["status"] == "failed_handoff":
            raise SystemExit("LAMMPS returned successfully but pre-GCMC basal handoff sanity check failed.")
        return

    status["finished_at"] = now_iso()
    write_json(status_path, status)
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
