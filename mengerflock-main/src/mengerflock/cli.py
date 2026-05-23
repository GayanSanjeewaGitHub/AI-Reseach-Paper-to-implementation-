from __future__ import annotations

from pathlib import Path

import click

from mengerflock.config import load_config
from mengerflock.orchestrator import Orchestrator, init_project
from mengerflock.state import (
    is_shutdown_requested,
    read_results,
    write_shutdown_flag,
)


@click.group()
def main() -> None:
    """MengerFlock — automated algorithm discovery through multi-agent evolution."""
    pass


@main.command()
@click.argument("config_path", type=click.Path(exists=True), default="config.yaml")
def run(config_path: str) -> None:
    """Run the MengerFlock experiment (defaults to config.yaml in current directory)."""
    config = load_config(config_path)
    project_dir = Path.cwd()

    if not (project_dir / "state").exists():
        init_project(project_dir, config)

    orchestrator = Orchestrator(project_dir, config)
    click.echo(f"Starting MengerFlock: {config.project.name}")
    click.echo("")
    click.echo("Agents are running in tmux. To interact:")
    click.echo("  tmux attach -t mengerflock        # attach to the session")
    click.echo("  Ctrl+B then n/p                   # switch between agent windows")
    click.echo("  Ctrl+B then d                     # detach (agents keep running)")
    click.echo("")
    orchestrator.run()


@main.command()
def status() -> None:
    """Show current experiment progress."""
    state_dir = Path.cwd() / "state"
    if not state_dir.exists():
        click.echo("No active project. Run 'mengerflock run' first.")
        return

    results = read_results(state_dir)
    keeps = [r for r in results if r["status"] == "keep"]
    discards = [r for r in results if r["status"] == "discard"]
    crashes = [r for r in results if r["status"] == "crash"]

    click.echo(f"Total experiments: {len(results)}")
    click.echo(f"  Keep: {len(keeps)}")
    click.echo(f"  Discard: {len(discards)}")
    click.echo(f"  Crash: {len(crashes)}")

    if keeps:
        best = min(keeps, key=lambda r: float(r["metric_avg"]))
        click.echo(f"Best metric_avg: {best['metric_avg']} ({best['module']}, {best['commit']})")

    if is_shutdown_requested(state_dir):
        click.echo("Status: SHUTTING DOWN")
    else:
        click.echo("Status: RUNNING")


@main.command()
def stop() -> None:
    """Gracefully stop the experiment."""
    state_dir = Path.cwd() / "state"
    if not state_dir.exists():
        click.echo("No active project.")
        return

    write_shutdown_flag(state_dir)
    click.echo("Shutdown signal sent. Sessions will finish current iteration and stop.")


@main.command()
@click.option("--force", is_flag=True, help="Skip confirmation")
def clean(force: bool) -> None:
    """Remove all experiment state (state/, .worktrees/, report/, experiment branches)."""
    import shutil

    project_dir = Path.cwd()

    if not force:
        click.confirm("This will delete state/, .worktrees/, report/, and experiment branches. Continue?", abort=True)

    for d in ["state", ".worktrees", "report"]:
        p = project_dir / d
        if p.exists():
            shutil.rmtree(p)
            click.echo(f"Removed {d}/")

    # Remove experiment branches
    from mengerflock.worktree import _git
    result = _git(project_dir, "branch", "--list", check=False)
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            branch = line.strip().lstrip("* ")
            if branch.startswith(("wildcard/", "researcher/", "crosspollin/")):
                _git(project_dir, "branch", "-D", branch, check=False)
                click.echo(f"Deleted branch {branch}")

    click.echo("Clean complete.")


@main.command()
@click.argument("template", type=click.Path(exists=True))
@click.argument("experiment_name")
@click.option("--seed-from", type=click.Path(exists=True), help="Copy evolved seed from a previous experiment instead of using template seed")
def new(template: str, experiment_name: str, seed_from: str | None) -> None:
    """Create a new experiment from a template.

    TEMPLATE is the path to the template folder (e.g., projects/tsp/).
    EXPERIMENT_NAME is the name for the new experiment folder.
    """
    import shutil
    import subprocess

    template_path = Path(template).resolve()
    experiment_path = template_path.parent / experiment_name

    if experiment_path.exists():
        click.echo(f"Error: {experiment_path} already exists.")
        return

    experiment_path.mkdir(parents=True)

    try:
        # Copy seed (from previous experiment or from template)
        if seed_from:
            seed_src = Path(seed_from).resolve() / "seed"
            if not seed_src.exists():
                click.echo(f"Error: {seed_src} does not exist.")
                shutil.rmtree(experiment_path)
                return
            shutil.copytree(seed_src, experiment_path / "seed")
            click.echo(f"Seed: copied evolved seed from {seed_from}")
        else:
            seed_src = template_path / "seed"
            if seed_src.exists():
                shutil.copytree(seed_src, experiment_path / "seed")
                click.echo("Seed: copied from template (seed/)")
            elif (template_path / "original-seed").exists():
                shutil.copytree(template_path / "original-seed", experiment_path / "seed")
                click.echo("Seed: copied from template (original-seed/ — no seed/ found)")
            else:
                click.echo("Warning: no seed/ or original-seed/ found in template — seed not copied")

        # Copy eval.sh
        eval_src = template_path / "eval.sh"
        if eval_src.exists():
            shutil.copy2(eval_src, experiment_path / "eval.sh")
        else:
            click.echo(f"Warning: eval.sh not found in template ({template_path}) — you must add it manually")

        # Copy prompts from the mengerflock repo (find them relative to this file)
        prompts_src = Path(__file__).resolve().parent.parent.parent / "prompts"
        if prompts_src.exists():
            shutil.copytree(prompts_src, experiment_path / "prompts")
        else:
            click.echo(f"Warning: prompts directory not found at {prompts_src} — you must copy prompts manually")

        # Read template config as base if it exists
        template_config = template_path / "config.yaml"
        if template_config.exists():
            config_content = template_config.read_text()
            (experiment_path / "config.yaml").write_text(config_content)
            click.echo("Config: copied from template (review and update paths)")

        # Create .gitignore
        (experiment_path / ".gitignore").write_text("datasets/\n.worktrees/\n")

        # Init git repo
        subprocess.run(["git", "init"], cwd=experiment_path, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=experiment_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"Initial seed for {experiment_name}"],
            cwd=experiment_path,
            capture_output=True,
        )
        subprocess.run(["git", "tag", "baseline"], cwd=experiment_path, capture_output=True)

    except Exception as e:
        click.echo(f"Error: {e}")
        click.echo(f"Cleaning up partial directory: {experiment_path}")
        shutil.rmtree(experiment_path, ignore_errors=True)
        return

    click.echo(f"\nExperiment created: {experiment_path}")
    click.echo("  Git initialized with 'baseline' tag")
    click.echo("  Review config.yaml and update paths before running")
    click.echo("\nTo run:")
    click.echo(f"  cd {experiment_path}")
    click.echo(f"  mengerflock run")


if __name__ == "__main__":
    main()
