#!/usr/bin/env python3
"""
Generate and optionally run the first RH GCMC-MD input from prepared LAMMPS data.
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

def first_rh(case_cfg: Dict[str, Any]) -> float:
    rh_path = get_nested(case_cfg, ["gcmc", "rh_path"], [0.90])
    if not isinstance(rh_path, list) or not rh_path:
        raise ValueError("gcmc.rh_path must contain at least one RH value")
    return float(rh_path[0])


def build_paths(
    case_cfg: Dict[str, Any],
    case_path: Path,
    repo_root: Path,
    rh: float,
    run_dir_override: Path | None = None,
) -> Dict[str, Path]:
    base_dir = case_path.parent.resolve()
    paths_cfg = case_cfg.get("paths", {})
    if not isinstance(paths_cfg, dict):
        paths_cfg = {}

    example_dir = resolve_path(paths_cfg.get("example_dir", "examples/Mt_Oct050_Na"), base_dir)
    prepared_dir = resolve_path(paths_cfg.get("prepared_dir", example_dir / "inputs"), base_dir)
    model = str(get_nested(case_cfg, ["structure", "claycode_model"], "MyMont-1_5_4"))
    tag = generate_gcmc_input.rh_to_tag(rh)

    default_run_dir = example_dir / tag.replace("rh", "rh_")
    run_dir = resolve_path(run_dir_override, repo_root) if run_dir_override is not None else default_run_dir

    equil_cfg = case_cfg.get("equilibration", {})
    if not isinstance(equil_cfg, dict):
        equil_cfg = {}

    return {
        "example_dir": example_dir,
        "prepared_dir": prepared_dir,
        "prepared_data": prepared_dir / f"{model}_prepared.data",
        "groups_regions": prepared_dir / f"{model}_groups_regions.inc",
        "equilibrated_data": resolve_path(
            equil_cfg.get("output_data", prepared_dir / f"{model}_equilibrated.data"),
            base_dir,
        ),
        "equilibration_restart": resolve_path(
            equil_cfg.get("output_restart", prepared_dir / "restart.pre_gcmc.final"),
            base_dir,
        ),
        "run_dir": run_dir,
        "input": run_dir / f"in.gcmc_{tag}_initial",
    }


def select_start_source(paths: Dict[str, Path]) -> tuple[str, Path, List[str]]:
    warnings: List[str] = []
    if paths["equilibration_restart"].exists():
        return "equilibration_restart", paths["equilibration_restart"], warnings
    if paths["equilibrated_data"].exists():
        return "equilibrated_data", paths["equilibrated_data"], warnings
    warnings.append("Pre-GCMC equilibration output not found; falling back to prepared.data.")
    return "prepared_data", paths["prepared_data"], warnings


def validate_inputs(paths: Dict[str, Path], molecule_template: Path, start_source: Path) -> None:
    for label, path in [
        ("initial start source", start_source),
        ("groups/regions include", paths["groups_regions"]),
        ("water molecule template", molecule_template),
    ]:
        if not path.exists():
            raise FileNotFoundError(f"Missing {label}: {path}")
        if not path.is_file():
            raise FileNotFoundError(f"Expected {label} to be a file: {path}")


def generate_initial_input(
    case_cfg: Dict[str, Any],
    repo_root: Path,
    run_dir: Path,
    start_source: Path,
    start_source_kind: str,
    groups_regions: Path,
    molecule_template: Path,
    rh: float,
    segment_steps_override: int | None = None,
) -> tuple[str, int, int, int, int]:
    temp = float(get_nested(case_cfg, ["case", "temperature"], 300.0))
    gcmc_interval = int(get_nested(case_cfg, ["gcmc", "interval"], 1000))
    exchange_attempts = int(get_nested(case_cfg, ["gcmc", "exchange_attempts"], 100))
    translation_attempts = int(get_nested(case_cfg, ["gcmc", "translation_attempts"], 0))
    rotation_attempts = int(get_nested(case_cfg, ["gcmc", "rotation_attempts"], 0))
    mu = float(get_nested(case_cfg, ["gcmc", "mu"], -8.1))
    disp = float(get_nested(case_cfg, ["gcmc", "displacement"], 0.5))
    tfac = float(get_nested(case_cfg, ["gcmc", "tfac_insert"], 1.6666666667))
    restart_interval = int(get_nested(case_cfg, ["md", "restart_interval"], get_nested(case_cfg, ["gcmc", "restart_interval"], 100000)))
    initial_relax_steps = int(
        get_nested(case_cfg, ["md", "initial_relax_steps"], get_nested(case_cfg, ["initial", "initial_relax_steps"], 10000))
    )
    tdamp = float(get_nested(case_cfg, ["md", "tdamp"], get_nested(case_cfg, ["initial", "tdamp"], 100.0)))
    velocity_seed = int(get_nested(case_cfg, ["md", "velocity_seed"], get_nested(case_cfg, ["initial", "velocity_seed"], 4928459)))
    reinitialize_velocity_on_restart = bool(get_nested(case_cfg, ["md", "reinitialize_velocity_on_restart"], False))
    original_segment_steps = int(get_nested(case_cfg, ["gcmc", "segment_steps"], 500000))
    segment_steps = segment_steps_override if segment_steps_override is not None else original_segment_steps

    pair_style = str(get_nested(case_cfg, ["md", "pair_style"], "lj/cut/coul/long 12.0"))
    kspace_style = str(get_nested(case_cfg, ["md", "kspace_style"], "pppm 1.0e-4"))
    timestep_fs = float(get_nested(case_cfg, ["md", "timestep_fs"], 1.0))
    thermo_interval = int(get_nested(case_cfg, ["md", "thermo_interval"], 5000))
    monitor_interval = int(get_nested(case_cfg, ["md", "monitor_interval"], 1000))
    dump_interval = int(get_nested(case_cfg, ["md", "dump_interval"], 50000))
    neigh_modify = generate_gcmc_input.neighbor_modify_line(case_cfg)

    water_oxygen_type = int(get_nested(case_cfg, ["water", "oxygen_type"], 8))
    p_h2o = generate_gcmc_input.atm_pressure_from_rh(case_cfg, rh)
    tag = generate_gcmc_input.rh_to_tag(rh)
    region_line = generate_gcmc_input.gcmc_region_line(case_cfg)

    start_for_lammps = lammps_path(start_source)
    groups_for_lammps = lammps_path(groups_regions)
    molecule_for_lammps = lammps_path(molecule_template)
    topology_extra = topology_extra_settings(case_cfg)
    using_restart = start_source_kind in {"equilibration_restart", "archived_restart", "restart"}
    if using_restart:
        read_command_line = f"read_restart {start_for_lammps}"
    else:
        read_command_line = read_data_with_topology_extra(start_source, topology_extra)
    should_initialize_velocity = (not using_restart) or reinitialize_velocity_on_restart
    velocity_create_line = (
        f"velocity mobile create ${{temp}} {velocity_seed} mom yes rot yes dist gaussian loop geom"
        if should_initialize_velocity
        else "# Existing mobile velocities are preserved from read_restart."
    )

    text = f"""# Auto-generated initial GCMC input
# Generated by mtagent/run_initial.py
# RH = {rh:.2f}
# Start source ({start_source_kind}) = {start_for_lammps}
# Segment steps = {segment_steps}

variable temp        equal {temp}
variable rh          equal {rh:.6f}
variable p_h2o       equal {p_h2o:.12g}
variable mu          equal {mu}
variable disp        equal {disp}
variable tfac        equal {tfac}

units real
atom_style full
boundary p p p

pair_style {pair_style}
pair_modify mix arithmetic
bond_style harmonic
angle_style harmonic
special_bonds lj/coul 0.0 0.0 0.5

{read_command_line}
include {groups_for_lammps}

kspace_style {kspace_style}

neighbor 2.0 bin
neigh_modify {neigh_modify}

timestep {timestep_fs}

# Molecule template for GCMC insertion.
molecule h2omol {molecule_for_lammps}

group clay union clay_lower clay_upper
group mobile union water sodium

# Rigid clay sheets: z-translation only, no x/y motion, no rotation.
# clay molecule IDs are normalized: lower=1, upper=2
velocity clay set 0.0 0.0 0.0
fix rigid_clay clay rigid/nve molecule force * off off on torque * off off off

# Exclude only intra-sheet nonbonded interactions.
neigh_modify exclude group clay_lower clay_lower
neigh_modify exclude group clay_upper clay_upper

# Mobile phase.
fix wshake water shake 1.0e-4 50 0 b 1 a 1 mol h2omol
fix mom_water water momentum 100 linear 1 1 1
fix mom_ions sodium momentum 100 linear 1 1 1
compute_modify thermo_temp dynamic/dof yes

# Initial NVT relaxation
{velocity_create_line}
fix nvt_mobile mobile nvt temp ${{temp}} ${{temp}} {tdamp}
run {initial_relax_steps}
unfix nvt_mobile

# RH GCMC-MD segment
fix nvt_water water nvt temp ${{temp}} ${{temp}} 100.0
fix nvt_ions sodium nvt temp ${{temp}} ${{temp}} 100.0
compute_modify nvt_water_temp dynamic/dof yes

# GCMC insertion region from case.yaml.
{region_line}

fix mygcmc water gcmc {gcmc_interval} {exchange_attempts} {translation_attempts} {rotation_attempts} 54341 ${{temp}} ${{mu}} ${{disp}} mol &
             h2omol tfac_insert ${{tfac}} region rgmc group water shake wshake &
             pressure ${{p_h2o}}

# ---------- monitors ----------
variable nwater_atoms equal count(water)
variable nwater_mol   equal count(water)/3.0
variable nexchangeable_ions equal count(sodium)

compute zlow clay_lower reduce ave z
compute zup  clay_upper reduce ave z

variable zlow_now equal c_zlow
variable zup_now  equal c_zup

variable basal_proxy equal v_zup_now-v_zlow_now
variable zcenter equal 0.5*(v_zup_now+v_zlow_now)

# Dynamic water counting based on mineral mass centers.
variable is_bottom_ow atom (type=={water_oxygen_type})&&(z<v_zlow_now)
variable is_inter_ow  atom (type=={water_oxygen_type})&&(z>=v_zlow_now)&&(z<=v_zup_now)
variable is_top_ow    atom (type=={water_oxygen_type})&&(z>v_zup_now)

compute nw_bottom all reduce sum v_is_bottom_ow
compute nw_inter  all reduce sum v_is_inter_ow
compute nw_top    all reduce sum v_is_top_ow

variable nwat_bottom equal c_nw_bottom
variable nwat_inter  equal c_nw_inter
variable nwat_top    equal c_nw_top
variable nwat_ext    equal v_nwat_bottom+v_nwat_top

variable tacc equal f_mygcmc[2]/(f_mygcmc[1]+0.1)
variable iacc equal f_mygcmc[4]/(f_mygcmc[3]+0.1)
variable dacc equal f_mygcmc[6]/(f_mygcmc[5]+0.1)
variable racc equal f_mygcmc[8]/(f_mygcmc[7]+0.1)

variable temp_inst equal temp
variable pe_inst equal pe

thermo {thermo_interval}
thermo_style custom step temp pe ke etotal press atoms &
  v_nwater_mol v_nwat_inter v_nwat_bottom v_nwat_top v_nwat_ext v_nexchangeable_ions &
  v_iacc v_dacc v_tacc v_racc &
  v_zlow_now v_zup_now v_basal_proxy v_zcenter v_p_h2o cpu

fix mon all ave/time {monitor_interval} 1 {monitor_interval} &
  v_nwater_mol v_nwat_inter v_nwat_bottom v_nwat_top v_nwat_ext &
  v_basal_proxy v_zcenter v_iacc v_dacc v_tacc v_racc v_temp_inst v_pe_inst &
  append monitor_gcmc_{tag}.dat

dump d1 all custom {dump_interval} dump.gcmc_{tag}.lammpstrj id mol type q x y z vx vy vz
dump_modify d1 sort id

restart {restart_interval} restart.gcmc_{tag}.*

run {segment_steps}

write_restart restart.gcmc_{tag}.final
write_data after_gcmc_{tag}_initial.data
"""
    return text, original_segment_steps, segment_steps, initial_relax_steps, restart_interval


def write_text_if_new_or_same(path: Path, text: str, force: bool = False) -> None:
    if path.exists() and path.read_text() != text and not force:
        raise FileExistsError(f"Refusing to overwrite existing input file with different content: {path}")
    path.write_text(text)


def write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, indent=2))


def find_collision_files(run_dir: Path) -> List[Path]:
    if not run_dir.exists():
        return []
    monitors = sorted(p for p in run_dir.glob("monitor_gcmc_*.dat") if p.is_file())
    restarts = sorted(p for p in run_dir.glob("restart.*") if p.is_file())
    return monitors + restarts


def run_lammps(
    case_cfg: Dict[str, Any],
    repo_root: Path,
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


def collect_output_validation(run_dir: Path, tag: str, restart_expected: bool) -> Dict[str, Any]:
    missing = []
    if not (run_dir / "log.lammps").exists():
        missing.append("log.lammps")
    if not (run_dir / f"monitor_gcmc_{tag}.dat").exists():
        missing.append(f"monitor_gcmc_{tag}.dat")
    if not (run_dir / f"after_gcmc_{tag}_initial.data").exists():
        missing.append(f"after_gcmc_{tag}_initial.data")

    final_restart_path = run_dir / f"restart.gcmc_{tag}.final"
    final_restart = str(final_restart_path) if final_restart_path.exists() else None
    if final_restart is None:
        missing.append(f"restart.gcmc_{tag}.final")

    found_restart_files = sorted(str(p) for p in run_dir.glob(f"restart.gcmc_{tag}.*") if p.is_file())
    periodic_restart_files = [p for p in found_restart_files if not p.endswith(".final")]
    warnings = []
    if restart_expected and not periodic_restart_files:
        missing.append(f"restart.gcmc_{tag}.*")
    elif not restart_expected:
        warnings.append("Restart not expected for short validation run.")

    return {
        "missing_outputs": missing,
        "found_restart_files": found_restart_files,
        "final_restart": final_restart,
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, default=Path("case.yaml"))
    parser.add_argument("--dry-run", action="store_true", help="Generate input and preview status without running LAMMPS.")
    parser.add_argument("--run", action="store_true", help="Run the generated initial input locally.")
    parser.add_argument("--run-dir", type=Path, default=None, help="Override the RH run directory.")
    parser.add_argument("--write-input", action="store_true", help="Allow dry-run mode to write the LAMMPS input file.")
    parser.add_argument("--force", action="store_true", help="Allow use of an existing run directory with monitor/restart files.")
    parser.add_argument("--np", type=int, default=None)
    parser.add_argument("--segment-steps-override", type=int, default=None)
    args = parser.parse_args()

    if args.dry_run and args.run:
        raise SystemExit("Use either --dry-run or --run, not both.")
    if args.segment_steps_override is not None and args.segment_steps_override <= 0:
        raise SystemExit("--segment-steps-override must be a positive integer.")

    repo_root = Path.cwd().resolve()
    case_path = args.case.resolve()
    case_cfg = load_case_yaml(case_path)
    rh = first_rh(case_cfg)
    tag = generate_gcmc_input.rh_to_tag(rh)
    paths = build_paths(case_cfg, case_path, repo_root, rh, run_dir_override=args.run_dir)
    molecule_template = resolve_path(
        get_nested(case_cfg, ["water", "molecule_template"], "assets/forcefields/SPCEH2O_types_8_10.txt"),
        case_path.parent.resolve(),
    )

    start_source_kind, start_source, source_warnings = select_start_source(paths)
    validate_inputs(paths, molecule_template, start_source)
    collision_files = find_collision_files(paths["run_dir"])
    collision_warning = None
    if collision_files:
        collision_warning = (
            f"Run directory contains existing monitor/restart files: {paths['run_dir']}. "
            "Use --force only when intentionally starting from this directory."
        )
        if args.run and not args.force:
            raise SystemExit(collision_warning)

    should_write_input = args.run or args.write_input
    paths["run_dir"].mkdir(parents=True, exist_ok=True)

    input_text, original_segment_steps, effective_segment_steps, initial_relax_steps, restart_interval = generate_initial_input(
        case_cfg=case_cfg,
        repo_root=repo_root,
        run_dir=paths["run_dir"],
        start_source=start_source,
        start_source_kind=start_source_kind,
        groups_regions=paths["groups_regions"],
        molecule_template=molecule_template,
        rh=rh,
        segment_steps_override=args.segment_steps_override,
    )
    input_file_written = False
    if should_write_input:
        write_text_if_new_or_same(paths["input"], input_text, force=args.force)
        input_file_written = True

    restart_expected = initial_relax_steps + effective_segment_steps >= restart_interval
    status_path = paths["run_dir"] / ("initial_status.preview.json" if args.dry_run else "initial_status.json")
    status: Dict[str, Any] = {
        "status": "dry_run" if args.dry_run else "generated",
        "dry_run": args.dry_run,
        "run_requested": args.run,
        "case": str(case_path),
        "run_dir": str(paths["run_dir"]),
        "rh": rh,
        "tag": tag,
        "rh_tag": tag,
        "input_file": str(paths["input"]),
        "input_file_written": input_file_written,
        "write_input": args.write_input,
        "force": args.force,
        "prepared_data": str(paths["prepared_data"]),
        "equilibrated_data": str(paths["equilibrated_data"]),
        "equilibration_restart": str(paths["equilibration_restart"]),
        "start_source_kind": start_source_kind,
        "start_source": str(start_source),
        "groups_regions": str(paths["groups_regions"]),
        "molecule_template": str(molecule_template),
        "original_segment_steps": original_segment_steps,
        "effective_segment_steps": effective_segment_steps,
        "initial_relax_steps": initial_relax_steps,
        "restart_interval": restart_interval,
        "restart_expected": restart_expected,
        "found_restart_files": [],
        "final_restart": None,
        "segment_steps_override": args.segment_steps_override,
        "run_line": f"run {effective_segment_steps}",
        "neighbor_settings": generate_gcmc_input.neighbor_settings(case_cfg),
        "neigh_modify": generate_gcmc_input.neighbor_modify_line(case_cfg),
        "reinitialize_velocity_on_restart": bool(
            get_nested(case_cfg, ["md", "reinitialize_velocity_on_restart"], False)
        ),
        "topology_extra": topology_extra_settings(case_cfg),
        "status_file": str(status_path),
        "started_at": now_iso(),
        "finished_at": None,
        "collision_files": [str(p) for p in collision_files],
        "warnings": source_warnings + ([collision_warning] if collision_warning else []),
    }

    if args.run:
        status["status"] = "running"
        write_json(status_path, status)
        rc = run_lammps(case_cfg, repo_root, paths["run_dir"], paths["input"], args.np, status)
        if rc == 0:
            output_validation = collect_output_validation(paths["run_dir"], tag, restart_expected)
            status["missing_outputs"] = output_validation["missing_outputs"]
            status["found_restart_files"] = output_validation["found_restart_files"]
            status["final_restart"] = output_validation["final_restart"]
            status["warnings"].extend(output_validation["warnings"])
            status["status"] = "failed_outputs_missing" if status["missing_outputs"] else "completed"
        else:
            status["status"] = "failed"
        status["finished_at"] = now_iso()
        write_json(status_path, status)
        print(json.dumps(status, indent=2))
        if rc != 0:
            raise SystemExit(rc)
        if status["status"] == "failed_outputs_missing":
            raise SystemExit("LAMMPS returned successfully but expected output files are missing.")
        return

    status["finished_at"] = now_iso()
    write_json(status_path, status)
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
