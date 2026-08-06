from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from mtagent import run_claycode


def write_case(tmp_path: Path, command: list[str] | None = None, output_dir: str | None = "MyMont1") -> Path:
    work_dir = tmp_path / "assets" / "claycode"
    work_dir.mkdir(parents=True)
    (work_dir / "MyMont1.yaml").write_text("csv: exp_clay.csv\n")
    (work_dir / "exp_clay.csv").write_text("name,value\n")
    raw_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "raw"
    command = command or [sys.executable, "fake_claycode.py"]
    command_yaml = "\n".join(f"    - {item}" for item in command)
    output_line = f"  output_dir: {output_dir}\n" if output_dir is not None else ""
    case_path = tmp_path / "case.yaml"
    case_path.write_text(
        f"""claycode:
  work_dir: assets/claycode
  input_yaml: MyMont1.yaml
  exp_csv: exp_clay.csv
{output_line}  selected_prefix: MyMont-1_5_4
  command:
{command_yaml}
paths:
  raw_dir: {raw_dir}
structure:
  claycode_model: MyMont-1_5_4
"""
    )
    return case_path


def write_fake_command(work_dir: Path, body: str | None = None) -> None:
    body = body or """
from pathlib import Path
out = Path('MyMont1')
out.mkdir(exist_ok=True)
(out / 'MyMont-1_5_4.gro').write_text('selected gro\\n')
(out / 'MyMont-1_5_4.top').write_text('selected top\\n')
(out / 'OtherVariant.gro').write_text('ignore gro\\n')
(out / 'MyMont-dry.top').write_text('ignore top\\n')
"""
    (work_dir / "fake_claycode.py").write_text(body)


def run_cli(monkeypatch, tmp_path: Path, args: list[str]) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_claycode.py", *args])
    run_claycode.main()


def test_dry_run_validates_inputs_and_writes_preview_status(tmp_path, monkeypatch) -> None:
    case_path = write_case(tmp_path)

    run_cli(monkeypatch, tmp_path, ["--case", str(case_path), "--dry-run"])

    status_path = tmp_path / "examples" / "Mt_Oct050_Na" / "raw" / "claycode_status.preview.json"
    status = json.loads(status_path.read_text())
    assert status["status"] == "dry_run"
    assert status["dry_run"] is True
    assert status["input_yaml"].endswith("assets/claycode/MyMont1.yaml")
    assert status["exp_csv"].endswith("assets/claycode/exp_clay.csv")
    assert status["expected_selected_gro"].endswith("assets/claycode/MyMont1/MyMont-1_5_4.gro")
    assert status["expected_selected_top"].endswith("assets/claycode/MyMont1/MyMont-1_5_4.top")
    assert status["copied_raw_gro"] is None
    assert not (tmp_path / "examples" / "Mt_Oct050_Na" / "raw" / "MyMont-1_5_4.gro").exists()


def test_dry_run_uses_claycode_work_dir_as_cwd(tmp_path, monkeypatch) -> None:
    case_path = write_case(tmp_path)

    run_cli(monkeypatch, tmp_path, ["--case", str(case_path), "--dry-run"])

    status = json.loads((tmp_path / "examples" / "Mt_Oct050_Na" / "raw" / "claycode_status.preview.json").read_text())
    assert status["cwd"] == str((tmp_path / "assets" / "claycode").resolve())


def test_normal_mode_fake_command_copies_only_selected_outputs(tmp_path, monkeypatch) -> None:
    case_path = write_case(tmp_path)
    write_fake_command(tmp_path / "assets" / "claycode")

    run_cli(monkeypatch, tmp_path, ["--case", str(case_path)])

    raw_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "raw"
    assert (raw_dir / "MyMont-1_5_4.gro").read_text() == "selected gro\n"
    assert (raw_dir / "MyMont-1_5_4.top").read_text() == "selected top\n"
    assert not (raw_dir / "OtherVariant.gro").exists()
    assert not (raw_dir / "MyMont-dry.top").exists()
    status = json.loads((raw_dir / "claycode_status.json").read_text())
    assert status["status"] == "completed"
    assert status["return_code"] == 0
    assert status["copied_raw_gro"].endswith("MyMont-1_5_4.gro")
    assert status["copied_raw_top"].endswith("MyMont-1_5_4.top")


def test_existing_destination_files_not_overwritten_without_force(tmp_path, monkeypatch) -> None:
    case_path = write_case(tmp_path)
    write_fake_command(tmp_path / "assets" / "claycode")
    raw_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "raw"
    raw_dir.mkdir(parents=True)
    dest = raw_dir / "MyMont-1_5_4.gro"
    dest.write_text("existing\n")

    with pytest.raises(SystemExit, match="Use --force"):
        run_cli(monkeypatch, tmp_path, ["--case", str(case_path)])

    assert dest.read_text() == "existing\n"
    status = json.loads((raw_dir / "claycode_status.json").read_text())
    assert status["status"] == "failed"


def test_existing_destination_files_overwritten_with_force(tmp_path, monkeypatch) -> None:
    case_path = write_case(tmp_path)
    write_fake_command(tmp_path / "assets" / "claycode")
    raw_dir = tmp_path / "examples" / "Mt_Oct050_Na" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "MyMont-1_5_4.gro").write_text("existing\n")

    run_cli(monkeypatch, tmp_path, ["--case", str(case_path), "--force"])

    assert (raw_dir / "MyMont-1_5_4.gro").read_text() == "selected gro\n"


def test_missing_selected_gro_or_top_fails_clearly(tmp_path, monkeypatch) -> None:
    case_path = write_case(tmp_path)
    write_fake_command(
        tmp_path / "assets" / "claycode",
        """
from pathlib import Path
out = Path('MyMont1')
out.mkdir(exist_ok=True)
(out / 'MyMont-1_5_4.gro').write_text('selected gro\\n')
""",
    )

    with pytest.raises(SystemExit, match="selected ClayCode .top output"):
        run_cli(monkeypatch, tmp_path, ["--case", str(case_path)])

    status = json.loads((tmp_path / "examples" / "Mt_Oct050_Na" / "raw" / "claycode_status.json").read_text())
    assert status["status"] == "failed"


def test_output_dir_defaults_to_yaml_stem(tmp_path, monkeypatch) -> None:
    case_path = write_case(tmp_path, output_dir=None)
    write_fake_command(tmp_path / "assets" / "claycode")

    run_cli(monkeypatch, tmp_path, ["--case", str(case_path)])

    status = json.loads((tmp_path / "examples" / "Mt_Oct050_Na" / "raw" / "claycode_status.json").read_text())
    assert status["output_dir"].endswith("assets/claycode/MyMont1")
    assert (tmp_path / "examples" / "Mt_Oct050_Na" / "raw" / "MyMont-1_5_4.top").exists()
