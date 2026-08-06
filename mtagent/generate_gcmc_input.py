#!/usr/bin/env python3
"""
Generate LAMMPS GCMC continuation input for MD-GCMC Agent.

First-version function:
  - read case.yaml
  - read manager_decision.json
  - infer RH and segment index from run directory
  - find latest restart file
  - generate a continuation LAMMPS input file

Usage:
  python3 mtagent/generate_gcmc_input.py \
    --run-dir examples/Mt_Oct050_Na/rh_0p90 \
    --case case.yaml \
    --decision examples/Mt_Oct050_Na/rh_0p90/manager_decision.json

Output example:
  examples/Mt_Oct050_Na/rh_0p90/in.gcmc_rh0p90_segment_002
  examples/Mt_Oct050_Na/rh_0p90/input_generation_status.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    return json.loads(path.read_text())


def load_case_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"case.yaml not found: {path}")

    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "PyYAML is required. Install it with:\n"
            "  pip install pyyaml\n"
            "or:\n"
            "  sudo apt install python3-yaml"
        ) from exc

    with path.open("r") as f:
        data = yaml.safe_load(f)
    return data or {}


def rh_from_dir(run_dir: Path) -> float:
    """
    Extract RH from folder name like:
      rh_0p90
      rh_0.90
      rh0p90
    """
    name = run_dir.name
    m = re.search(r"rh_?([0-9]+(?:p|\.)([0-9]+))", name)
    if not m:
        raise ValueError(f"Cannot infer RH from run directory name: {name}")

    raw = m.group(1).replace("p", ".")
    return float(raw)


def rh_to_tag(rh: float) -> str:
    return f"rh{rh:.2f}".replace(".", "p")


def restart_step_number(path: Path) -> int:
    for token in reversed(path.name.split(".")):
        if token.isdigit():
            return int(token)
    return -1


def restart_kind(path: Path) -> str:
    if restart_step_number(path) >= 0:
        return "numeric"
    if path.name.endswith(".final"):
        return "final"
    return "unknown"


def find_latest_restart(run_dir: Path, tag: str | None = None) -> tuple[Optional[Path], bool]:
    """
    Find latest restart file. Prefer matching-RH numeric timestep restarts.
    If no matching numeric restart exists, accept matching final restart from
    run_initial.py. Fall back to latest numeric restart from other RH tags.
    """
    candidates = [p for p in run_dir.glob("restart.*") if p.is_file()]
    if not candidates:
        return None, False

    if tag is not None:
        tagged = [p for p in candidates if tag in p.name]
        numeric_tagged = [p for p in tagged if restart_kind(p) == "numeric"]
        if numeric_tagged:
            return sorted(numeric_tagged, key=restart_step_number)[-1], True

        final_tagged = sorted(p for p in tagged if restart_kind(p) == "final")
        if final_tagged:
            return final_tagged[-1], True

    numeric_candidates = [p for p in candidates if restart_kind(p) == "numeric"]
    if not numeric_candidates:
        return None, False

    latest = sorted(numeric_candidates, key=restart_step_number)[-1]
    return latest, False


def next_segment_index(run_dir: Path, tag: str) -> int:
    existing = list(run_dir.glob(f"in.gcmc_{tag}_segment_*"))
    max_idx = 0
    for p in existing:
        m = re.search(r"segment_(\d+)$", p.name)
        if m:
            max_idx = max(max_idx, int(m.group(1)))
    return max_idx + 1


def get_nested(cfg: Dict[str, Any], keys: list[str], default: Any) -> Any:
    x: Any = cfg
    for k in keys:
        if not isinstance(x, dict) or k not in x:
            return default
        x = x[k]
    return x


def normalize_neighbor_check(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value).lower()


def neighbor_settings(case_cfg: Dict[str, Any]) -> Dict[str, Any]:
    md_cfg = case_cfg.get("md", {})
    if not isinstance(md_cfg, dict):
        md_cfg = {}

    if any(key in md_cfg for key in ("neighbor_every", "neighbor_delay", "neighbor_check")):
        return {
            "every": int(md_cfg.get("neighbor_every", 2)),
            "delay": int(md_cfg.get("neighbor_delay", 0)),
            "check": normalize_neighbor_check(md_cfg.get("neighbor_check", "yes")),
        }

    legacy = md_cfg.get("neigh_modify")
    if legacy is not None:
        return {"neigh_modify": str(legacy)}

    return {"every": 2, "delay": 0, "check": "yes"}


def neighbor_modify_line(case_cfg: Dict[str, Any]) -> str:
    settings = neighbor_settings(case_cfg)
    if "neigh_modify" in settings:
        return str(settings["neigh_modify"])
    return f"every {settings['every']} delay {settings['delay']} check {settings['check']}"


def atm_pressure_from_rh(case_cfg: Dict[str, Any], rh: float) -> float:
    psat_pa = float(get_nested(case_cfg, ["gcmc", "psat_pa"], 1011.71))
    patm_pa = float(get_nested(case_cfg, ["gcmc", "patm_pa"], 101325.0))
    return rh * psat_pa / patm_pa

def gcmc_region_line(case_cfg: Dict[str, Any]) -> str:
    """
    Generate LAMMPS GCMC region command from case.yaml.

    Expected case.yaml:
      regions:
        gcmc:
          style: block
          xlo: 0.1
          xhi: 25.7
          ylo: 0.1
          yhi: 35.7
          zlo: 20.0
          zhi: 65.0
          units: box
    """
    region_cfg = get_nested(case_cfg, ["regions", "gcmc"], None)
    if not isinstance(region_cfg, dict):
        raise ValueError(
            "Missing regions.gcmc in case.yaml. "
            "Please define regions.gcmc block xlo/xhi/ylo/yhi/zlo/zhi."
        )

    style = region_cfg.get("style", "block")
    if style != "block":
        raise ValueError(f"Only block-style GCMC region is supported now, got: {style}")

    required = ["xlo", "xhi", "ylo", "yhi", "zlo", "zhi"]
    missing = [k for k in required if k not in region_cfg]
    if missing:
        raise ValueError(f"Missing keys in regions.gcmc: {missing}")

    xlo = float(region_cfg["xlo"])
    xhi = float(region_cfg["xhi"])
    ylo = float(region_cfg["ylo"])
    yhi = float(region_cfg["yhi"])
    zlo = float(region_cfg["zlo"])
    zhi = float(region_cfg["zhi"])
    units = region_cfg.get("units", "box")

    if not (xlo < xhi and ylo < yhi and zlo < zhi):
        raise ValueError(
            f"Invalid GCMC region bounds: "
            f"x=({xlo},{xhi}), y=({ylo},{yhi}), z=({zlo},{zhi})"
        )

    return (
        f"region rgmc block {xlo:g} {xhi:g} {ylo:g} {yhi:g} "
        f"{zlo:g} {zhi:g} units {units}"
    )

def generate_input(
    case_cfg: Dict[str, Any],
    decision: Dict[str, Any],
    run_dir: Path,
    restart_file: Path,
    output_input: Path,
    rh: float,
    segment_steps_override: int | None = None,
) -> str:
    temp = float(get_nested(case_cfg, ["case", "temperature"], 300.0))

    gcmc_interval = int(get_nested(case_cfg, ["gcmc", "interval"], 1000))
    exchange_attempts = int(get_nested(case_cfg, ["gcmc", "exchange_attempts"], 100))
    translation_attempts = int(get_nested(case_cfg, ["gcmc", "translation_attempts"], 0))
    rotation_attempts = int(get_nested(case_cfg, ["gcmc", "rotation_attempts"], 0))
    mu = float(get_nested(case_cfg, ["gcmc", "mu"], -8.1))
    disp = float(get_nested(case_cfg, ["gcmc", "displacement"], 0.5))
    tfac = float(get_nested(case_cfg, ["gcmc", "tfac_insert"], 1.6666666667))
    restart_interval = int(get_nested(case_cfg, ["gcmc", "restart_interval"], 100000))

    original_segment_steps = int(decision.get("next_segment_steps", get_nested(case_cfg, ["gcmc", "segment_steps"], 500000)))
    segment_steps = segment_steps_override if segment_steps_override is not None else original_segment_steps
    timestep_fs = float(get_nested(case_cfg, ["md", "timestep_fs"], 1.0))
    thermo_interval = int(get_nested(case_cfg, ["md", "thermo_interval"], 5000))
    monitor_interval = int(get_nested(case_cfg, ["md", "monitor_interval"], 1000))
    dump_interval = int(get_nested(case_cfg, ["md", "dump_interval"], 50000))
    neigh_modify = neighbor_modify_line(case_cfg)

    p_h2o = atm_pressure_from_rh(case_cfg, rh)
    tag = rh_to_tag(rh)

    water_template = str(get_nested(case_cfg, ["water", "molecule_template"], "templates/SPCEH2O_types_8_10_gcmc.txt"))
    region_line = gcmc_region_line(case_cfg)

    # Use a path relative to run_dir if possible.
    repo_root = Path.cwd()
    try:
        water_template_path = Path(water_template).resolve().relative_to(run_dir.resolve())
        water_template_for_lammps = str(water_template_path)
    except Exception:
        # For typical usage from run_dir, relative path back to repo root is safer.
        water_template_for_lammps = str(Path("../../..") / water_template)

    input_text = f"""# Auto-generated GCMC continuation input
# Generated by mtagent/generate_gcmc_input.py
# RH = {rh:.2f}
# Restart source = {restart_file.name}
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

pair_style lj/cut/coul/long 12.0
pair_modify mix arithmetic
bond_style harmonic
angle_style harmonic
special_bonds lj/coul 0.0 0.0 0.5

read_restart {restart_file.name}

kspace_style pppm 1.0e-4

neighbor 2.0 bin
neigh_modify {neigh_modify}

timestep {timestep_fs}

# Molecule template for GCMC insertion.
molecule h2omol {water_template_for_lammps}

# Groups should already exist if saved in restart, but redefine critical groups if possible.
# If these group names are missing in a future workflow, generator/manager should catch it.
group clay union clay_lower clay_upper

# Rigid clay sheets: z-translation only, no x/y motion, no rotation.
velocity clay set 0.0 0.0 0.0
fix rigid_clay clay rigid/nve molecule force * off off on torque * off off off

# Exclude only intra-sheet nonbonded interactions.
neigh_modify exclude group clay_lower clay_lower
neigh_modify exclude group clay_upper clay_upper

# Mobile phase.
fix wshake water shake 1.0e-4 50 0 b 1 a 1 mol h2omol
fix nvt_water water nvt temp ${{temp}} ${{temp}} 100.0
fix nvt_ions sodium nvt temp ${{temp}} ${{temp}} 100.0

compute_modify thermo_temp dynamic/dof yes
compute_modify nvt_water_temp dynamic/dof yes

fix mom_water water momentum 100 linear 1 1 1
fix mom_ions sodium momentum 100 linear 1 1 1

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
variable is_bottom_ow atom (type==8)&&(z<v_zlow_now)
variable is_inter_ow  atom (type==8)&&(z>=v_zlow_now)&&(z<=v_zup_now)
variable is_top_ow    atom (type==8)&&(z>v_zup_now)

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

write_data after_gcmc_{tag}_segment.data
"""

    return input_text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--case", type=Path, default=Path("case.yaml"))
    parser.add_argument("--decision", type=Path, default=None)
    parser.add_argument("--restart", type=Path, default=None)
    parser.add_argument("--rh", type=float, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Preview generation without writing the LAMMPS input.")
    parser.add_argument("--force", action="store_true", help="Allow overwriting an existing output input file.")
    parser.add_argument("--segment-steps-override", type=int, default=None, help="Override only the next generated segment length for testing.")
    parser.add_argument("--status", type=Path, default=None, help="Status JSON path. Dry-run defaults to input_generation_status.preview.json.")
    args = parser.parse_args()

    run_dir = args.run_dir
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    case_cfg = load_case_yaml(args.case)
    molecule_template = get_nested(case_cfg, ["water", "molecule_template"], None)
    if molecule_template is None:
        raise SystemExit("Missing water.molecule_template in case.yaml")

    molecule_template_path = Path(molecule_template)
    if not molecule_template_path.exists():
        raise SystemExit(
            f"Molecule template not found: {molecule_template_path}\n"
            "Please check water.molecule_template in case.yaml."
        )

    if args.segment_steps_override is not None and args.segment_steps_override <= 0:
        raise SystemExit("--segment-steps-override must be a positive integer.")

    if args.decision is None:
        decision_path = run_dir / "manager_decision.json"
    else:
        decision_path = args.decision
    decision = load_json(decision_path)

    if decision.get("action") != "continue_current_rh":
        raise SystemExit(
            f"Manager action is {decision.get('action')}; no continuation input generated."
        )

    rh = args.rh if args.rh is not None else rh_from_dir(run_dir)
    tag = rh_to_tag(rh)

    restart_warning = None
    restart_tag_matched = False
    if args.restart is not None:
        restart_file = args.restart
        restart_tag_matched = tag in restart_file.name
    else:
        restart_file, restart_tag_matched = find_latest_restart(run_dir, tag=tag)
        if restart_file is not None and not restart_tag_matched:
            restart_warning = (
                f"WARNING: No restart file matching {tag} found in {run_dir}; "
                "falling back to latest restart.* file."
            )
            print(restart_warning)

    selected_restart_kind = restart_kind(restart_file) if restart_file is not None else None
    if restart_file is not None and selected_restart_kind == "final" and restart_warning is None:
        restart_warning = (
            f"WARNING: No numeric restart matching {tag} found in {run_dir}; "
            f"using final restart {restart_file.name}."
        )
        print(restart_warning)

    if restart_file is None:
        raise FileNotFoundError(
            f"No restart.* file found in {run_dir}. Cannot generate continuation input."
        )

    # Make restart path relative to run_dir for LAMMPS input.
    restart_file = restart_file.resolve()
    try:
        restart_for_input = restart_file.relative_to(run_dir.resolve())
    except ValueError:
        raise SystemExit(
            "Restart file should be inside run-dir for this first generator version."
        )

    seg_idx = next_segment_index(run_dir, tag)
    if args.out is None:
        out_path = run_dir / f"in.gcmc_{tag}_segment_{seg_idx:03d}"
    else:
        out_path = args.out

    if out_path.exists() and not args.force and not args.dry_run:
        raise SystemExit(f"Refusing to overwrite existing input file: {out_path}. Use --force to overwrite.")

    original_segment_steps = int(decision.get("next_segment_steps", get_nested(case_cfg, ["gcmc", "segment_steps"], 500000)))
    effective_segment_steps = args.segment_steps_override if args.segment_steps_override is not None else original_segment_steps

    status = {
        "status": "dry_run" if args.dry_run else "generated",
        "run_dir": str(run_dir),
        "rh": rh,
        "tag": tag,
        "rh_tag": tag,
        "input_file": str(out_path),
        "input_file_written": False,
        "restart_file": str(restart_file),
        "selected_restart": str(restart_file),
        "selected_restart_kind": selected_restart_kind,
        "restart_tag_matched": restart_tag_matched,
        "decision_file": str(decision_path),
        "segment_steps": effective_segment_steps,
        "original_segment_steps": original_segment_steps,
        "effective_segment_steps": effective_segment_steps,
        "segment_steps_override": args.segment_steps_override,
        "run_line": f"run {effective_segment_steps}",
        "neighbor_settings": neighbor_settings(case_cfg),
        "neigh_modify": neighbor_modify_line(case_cfg),
        "force": args.force,
        "dry_run": args.dry_run,
        "warnings": [restart_warning] if restart_warning else [],
    }

    if not args.dry_run:
        text = generate_input(
            case_cfg=case_cfg,
            decision=decision,
            run_dir=run_dir,
            restart_file=Path(restart_for_input),
            output_input=out_path,
            rh=rh,
            segment_steps_override=args.segment_steps_override,
        )
        out_path.write_text(text)
        status["input_file_written"] = True

    if args.status is not None:
        status_path = args.status
    elif args.dry_run:
        status_path = run_dir / "input_generation_status.preview.json"
    else:
        status_path = run_dir / "input_generation_status.json"

    status["status_file"] = str(status_path)
    status_path.write_text(json.dumps(status, indent=2))

    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
