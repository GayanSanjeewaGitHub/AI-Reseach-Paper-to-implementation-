from __future__ import annotations

import csv
import fcntl
from datetime import datetime, timezone
from pathlib import Path

import yaml

RESULTS_HEADER = [
    "timestamp", "researcher", "module", "commit",
    "metric_avg", "metric_best", "status", "hypothesis", "description",
]

STRATEGIST_LOG_HEADER = ["timestamp", "action", "details"]


def init_state_dir(state_dir: str | Path) -> None:
    """Create state directory structure and initialize empty TSV files."""
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "assignments").mkdir(exist_ok=True)
    (state_dir / "interrupts").mkdir(exist_ok=True)

    results_path = state_dir / "results.tsv"
    if not results_path.exists():
        results_path.write_text("\t".join(RESULTS_HEADER) + "\n")

    log_path = state_dir / "strategist_log.tsv"
    if not log_path.exists():
        log_path.write_text("\t".join(STRATEGIST_LOG_HEADER) + "\n")


def _append_tsv(path: Path, row: list[str]) -> None:
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write("\t".join(str(v) for v in row) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path) as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader)


def append_result(state_dir: str | Path, result: dict) -> None:
    """Append a researcher result row to results.tsv."""
    state_dir = Path(state_dir)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    row = [
        ts, result["researcher"], result["module"], result["commit"],
        result["metric_avg"], result["metric_best"], result["status"],
        result["hypothesis"], result["description"],
    ]
    _append_tsv(state_dir / "results.tsv", row)


def read_results(state_dir: str | Path) -> list[dict[str, str]]:
    """Return all rows from results.tsv as a list of dicts."""
    return _read_tsv(Path(state_dir) / "results.tsv")


def append_strategist_log(state_dir: str | Path, action: str, details: str) -> None:
    """Append an action entry to the strategist log."""
    state_dir = Path(state_dir)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    _append_tsv(state_dir / "strategist_log.tsv", [ts, action, details])


def read_strategist_log(state_dir: str | Path) -> list[dict[str, str]]:
    """Return all rows from strategist_log.tsv as a list of dicts."""
    return _read_tsv(Path(state_dir) / "strategist_log.tsv")


def write_assignment(state_dir: str | Path, researcher_id: str, assignment: dict) -> None:
    """Write a researcher assignment YAML file."""
    path = Path(state_dir) / "assignments" / f"{researcher_id}.yaml"
    path.write_text(yaml.dump(assignment, default_flow_style=False))


def read_assignment(state_dir: str | Path, researcher_id: str) -> dict | None:
    """Read and return the assignment for researcher_id, or None if absent."""
    path = Path(state_dir) / "assignments" / f"{researcher_id}.yaml"
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text()) or {}


def write_phase1_complete(state_dir: str | Path) -> None:
    """Signal that Phase 1 is complete."""
    (Path(state_dir) / "phase1_complete").touch()


def is_phase1_complete(state_dir: str | Path) -> bool:
    """Return True if the Phase 1 completion flag exists."""
    return (Path(state_dir) / "phase1_complete").exists()


def write_phase2_complete(state_dir: str | Path) -> None:
    """Signal that Phase 2 is complete."""
    (Path(state_dir) / "phase2_complete").touch()


def is_phase2_complete(state_dir: str | Path) -> bool:
    """Return True if the Phase 2 completion flag exists."""
    return (Path(state_dir) / "phase2_complete").exists()


def write_phase3_complete(state_dir: str | Path) -> None:
    """Signal that Phase 3 is complete."""
    (Path(state_dir) / "phase3_complete").touch()


def is_phase3_complete(state_dir: str | Path) -> bool:
    """Return True if the Phase 3 completion flag exists."""
    return (Path(state_dir) / "phase3_complete").exists()


def write_shutdown_flag(state_dir: str | Path) -> None:
    """Write the shutdown sentinel file to signal all agents to stop."""
    (Path(state_dir) / "shutdown").touch()


def is_shutdown_requested(state_dir: str | Path) -> bool:
    """Return True if the shutdown sentinel file exists."""
    return (Path(state_dir) / "shutdown").exists()


def write_interrupt(state_dir: str | Path, researcher_id: str, content: str) -> None:
    """Write an interrupt message for the given researcher."""
    path = Path(state_dir) / "interrupts" / f"{researcher_id}.md"
    path.write_text(content)


def read_interrupt(state_dir: str | Path, researcher_id: str) -> str | None:
    """Read and return the pending interrupt for researcher_id, or None."""
    path = Path(state_dir) / "interrupts" / f"{researcher_id}.md"
    if path.exists():
        return path.read_text()
    return None


def acknowledge_interrupt(state_dir: str | Path, researcher_id: str) -> None:
    """Rename the interrupt file to mark it as acknowledged."""
    src = Path(state_dir) / "interrupts" / f"{researcher_id}.md"
    dst = Path(state_dir) / "interrupts" / f"{researcher_id}.ack.md"
    if src.exists():
        src.rename(dst)


def write_objectives(state_dir: str | Path, content: str) -> None:
    """Write the experiment objectives to objectives.md."""
    path = Path(state_dir) / "objectives.md"
    path.write_text(content)


def read_objectives(state_dir: str | Path) -> str | None:
    """Read and return the experiment objectives, or None if not set."""
    path = Path(state_dir) / "objectives.md"
    if path.exists():
        return path.read_text()
    return None


BASELINE_HOLDOUT_FILE = "baseline_holdout.tsv"


def _init_baseline_holdout(state_dir: Path) -> None:
    path = state_dir / BASELINE_HOLDOUT_FILE
    if not path.exists():
        path.write_text("\t".join(RESULTS_HEADER) + "\n")


def append_baseline_holdout(state_dir: str | Path, result: dict) -> None:
    """Append a baseline holdout result row to baseline_holdout.tsv."""
    state_dir = Path(state_dir)
    path = state_dir / BASELINE_HOLDOUT_FILE
    if not path.exists():
        _init_baseline_holdout(state_dir)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    row = [
        ts, result["researcher"], result["module"], result["commit"],
        result["metric_avg"], result["metric_best"], result["status"],
        result["hypothesis"], result["description"],
    ]
    _append_tsv(path, row)


def read_baseline_holdout(state_dir: str | Path) -> list[dict[str, str]]:
    """Return all rows from baseline_holdout.tsv as a list of dicts."""
    return _read_tsv(Path(state_dir) / BASELINE_HOLDOUT_FILE)


INITIAL_SEED_HOLDOUT_FILE = "initial_seed_holdout.tsv"


def append_initial_seed_holdout(state_dir: str | Path, result: dict) -> None:
    """Append a row to the initial seed holdout TSV."""
    state_dir = Path(state_dir)
    path = state_dir / INITIAL_SEED_HOLDOUT_FILE
    if not path.exists():
        path.write_text("\t".join(RESULTS_HEADER) + "\n")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    row = [
        ts, result["researcher"], result["module"], result["commit"],
        result["metric_avg"], result["metric_best"], result["status"],
        result["hypothesis"], result["description"],
    ]
    _append_tsv(path, row)


def read_initial_seed_holdout(state_dir: str | Path) -> list[dict[str, str]]:
    """Read the initial seed holdout TSV."""
    return _read_tsv(Path(state_dir) / INITIAL_SEED_HOLDOUT_FILE)
