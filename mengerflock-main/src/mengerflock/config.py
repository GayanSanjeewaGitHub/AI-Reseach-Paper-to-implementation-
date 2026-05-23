"""Configuration loading and validation for MengerFlock."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Optional

import yaml


class ConfigError(Exception):
    """Raised when the configuration is invalid or missing required fields."""


def _require(raw: dict[str, Any], key: str, context: str = "") -> Any:
    """Return raw[key], raising ConfigError if the key is absent."""
    if key not in raw:
        ctx = f" in {context}" if context else ""
        raise ConfigError(f"Missing required field '{key}'{ctx}")
    return raw[key]


@dataclasses.dataclass
class ProjectConfig:
    name: str
    seed_path: str
    original_seed_path: str
    language: str
    paper: str | None = None


@dataclasses.dataclass
class ModuleConfig:
    name: str
    files: list[str]
    description: str


@dataclasses.dataclass
class BuildConfig:
    command: str
    binary: str


@dataclasses.dataclass
class TrainingConfig:
    train: str | None = None
    validation: str | None = None
    data_source: str | None = None        # "split" | "generate" | "download" | "manual"
    split_source: str | None = None       # directory to split (if data_source="split")
    split_ratios: list[float] | None = None  # [train, validation, holdout]
    stratify_by: str | None = None        # optional grouping key for stratified splits


@dataclasses.dataclass
class BenchmarkConfig:
    small: list[str]
    medium: list[str] = dataclasses.field(default_factory=list)
    large: list[str] = dataclasses.field(default_factory=list)
    baseline_results: Optional[str] = None


@dataclasses.dataclass
class EvaluationConfig:
    metric: str
    progressive: bool = True
    runs_per_instance: int = 5
    random_seeds: list[int] = dataclasses.field(default_factory=lambda: [42, 123, 456, 789, 1024])
    pre_check: str | None = None


@dataclasses.dataclass
class StrategistConfig:
    model_flags: str = ""


@dataclasses.dataclass
class ResearcherConfig:
    count: Optional[int] = None  # None = strategist decides (default: one per module)
    model_flags: str = ""
    max_iterations_per_assignment: int = 20


@dataclasses.dataclass
class WildcardConfig:
    model_flags: str = ""


@dataclasses.dataclass
class AgentsConfig:
    tool: str
    strategist: StrategistConfig
    researchers: ResearcherConfig
    wildcard: Optional[WildcardConfig] = None


@dataclasses.dataclass
class TimeoutsConfig:
    build: int = 30
    eval_per_instance: int = 30


@dataclasses.dataclass
class StoppingConditions:
    max_total_iterations: int = 500
    max_hours: float = 24
    target_improvement: float = 0.5
    stagnation_window: int = 50
    max_reentries: int = 2


@dataclasses.dataclass
class MengerFlockConfig:
    project: ProjectConfig
    modules: list[ModuleConfig]
    build: BuildConfig
    benchmarks: BenchmarkConfig
    evaluation: EvaluationConfig
    training: TrainingConfig
    agents: AgentsConfig
    timeouts: TimeoutsConfig
    stopping_conditions: StoppingConditions


def load_config(path: str | Path) -> MengerFlockConfig:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ConfigError("Config must be a YAML mapping")

    # Project
    proj_raw = _require(raw, "project")

    project = ProjectConfig(
        name=_require(proj_raw, "name", "project"),
        seed_path=_require(proj_raw, "seed_path", "project"),
        original_seed_path=_require(proj_raw, "original_seed_path", "project"),
        language=proj_raw.get("language", ""),
        paper=proj_raw.get("paper"),
    )

    # Modules
    modules_raw = _require(raw, "modules")
    if not modules_raw:
        raise ConfigError("modules list must not be empty")
    modules = []
    for m in modules_raw:
        files = _require(m, "files", "modules[]")
        if not files:
            raise ConfigError(f"modules[].files must not be empty for module '{m.get('name', '?')}'")
        modules.append(ModuleConfig(
            name=_require(m, "name", "modules[]"),
            files=files,
            description=_require(m, "description", "modules[]"),
        ))

    # Build
    build_raw = _require(raw, "build")
    build = BuildConfig(
        command=_require(build_raw, "command", "build"),
        binary=_require(build_raw, "binary", "build"),
    )

    # Benchmarks
    bench_raw = _require(raw, "benchmarks")
    small = _require(bench_raw, "small", "benchmarks")
    if not small:
        raise ConfigError("benchmarks.small must not be empty")
    benchmarks = BenchmarkConfig(
        small=small,
        medium=bench_raw.get("medium", []),
        large=bench_raw.get("large", []),
        baseline_results=bench_raw.get("baseline_results"),
    )

    # Evaluation
    eval_raw = _require(raw, "evaluation")
    runs_per_instance = eval_raw.get("runs_per_instance", 5)
    if runs_per_instance < 1:
        raise ConfigError("evaluation.runs_per_instance must be >= 1")
    random_seeds = eval_raw.get("random_seeds", [42, 123, 456, 789, 1024])
    if not random_seeds:
        raise ConfigError("evaluation.random_seeds must not be empty")
    evaluation = EvaluationConfig(
        metric=_require(eval_raw, "metric", "evaluation"),
        progressive=eval_raw.get("progressive", True),
        runs_per_instance=runs_per_instance,
        random_seeds=random_seeds,
        pre_check=eval_raw.get("pre_check"),
    )

    # Training (optional — strategist generates if missing)
    train_raw = raw.get("training", {})
    split_ratios = train_raw.get("split_ratios")
    if split_ratios is not None and abs(sum(split_ratios) - 1.0) > 0.01:
        raise ConfigError("training.split_ratios must sum to 1.0")
    training = TrainingConfig(
        train=train_raw.get("train"),
        validation=train_raw.get("validation"),
        data_source=train_raw.get("data_source"),
        split_source=train_raw.get("split_source"),
        split_ratios=split_ratios,
        stratify_by=train_raw.get("stratify_by"),
    )

    # Agents
    agents_raw = _require(raw, "agents")
    strat_raw = _require(agents_raw, "strategist", "agents")
    res_raw = _require(agents_raw, "researchers", "agents")
    count = res_raw.get("count")  # None = strategist decides based on modules
    if count is not None and count < 1:
        raise ConfigError("agents.researchers.count must be >= 1")

    # Wildcard (optional)
    wildcard = None
    wildcard_raw = agents_raw.get("wildcard")
    if wildcard_raw:
        wildcard = WildcardConfig(model_flags=wildcard_raw.get("model_flags", ""))

    agents = AgentsConfig(
        tool=_require(agents_raw, "tool", "agents"),
        strategist=StrategistConfig(model_flags=strat_raw.get("model_flags", "")),
        researchers=ResearcherConfig(
            count=count,
            model_flags=res_raw.get("model_flags", ""),
            max_iterations_per_assignment=res_raw.get("max_iterations_per_assignment", 20),
        ),
        wildcard=wildcard,
    )

    # Timeouts
    timeouts_raw = raw.get("timeouts", {})
    timeouts = TimeoutsConfig(
        build=timeouts_raw.get("build", 30),
        eval_per_instance=timeouts_raw.get("eval_per_instance", 30),
    )

    # Stopping conditions
    stop_raw = raw.get("stopping_conditions", {})
    max_total_iterations = stop_raw.get("max_total_iterations", 500)
    max_hours = stop_raw.get("max_hours", 24)
    stagnation_window = stop_raw.get("stagnation_window", 50)
    max_reentries = stop_raw.get("max_reentries", 2)
    if max_total_iterations < 1:
        raise ConfigError("stopping_conditions.max_total_iterations must be >= 1")
    if max_hours <= 0:
        raise ConfigError("stopping_conditions.max_hours must be > 0")
    if stagnation_window < 1:
        raise ConfigError("stopping_conditions.stagnation_window must be >= 1")
    if max_reentries < 0:
        raise ConfigError("stopping_conditions.max_reentries must be >= 0")
    stopping = StoppingConditions(
        max_total_iterations=max_total_iterations,
        max_hours=max_hours,
        target_improvement=stop_raw.get("target_improvement", 0.5),
        stagnation_window=stagnation_window,
        max_reentries=max_reentries,
    )

    return MengerFlockConfig(
        project=project,
        modules=modules,
        build=build,
        benchmarks=benchmarks,
        evaluation=evaluation,
        training=training,
        agents=agents,
        timeouts=timeouts,
        stopping_conditions=stopping,
    )
