from __future__ import annotations

import signal
import subprocess
import time
from pathlib import Path

from mengerflock.config import MengerFlockConfig
from mengerflock.state import (
    init_state_dir,
    read_results,
    write_shutdown_flag,
    is_shutdown_requested,
    is_phase1_complete,
    is_phase2_complete,
    is_phase3_complete,
)
from mengerflock.worktree import create_branch, create_worktree, remove_worktree, ref_exists


def is_seed_url(seed_path: str) -> bool:
    """Return True if seed_path looks like a remote git URL."""
    return seed_path.startswith(("http://", "https://", "git@"))


def init_project(project_dir: Path, config: MengerFlockConfig) -> None:
    """Initialize project directory: clone seed if needed and set up state."""
    # Clone seed if URL
    if is_seed_url(config.project.seed_path):
        seed_dir = project_dir / "seed"
        if not seed_dir.exists():
            subprocess.run(
                ["git", "clone", config.project.seed_path, str(seed_dir)],
                check=True,
            )
            config.project.seed_path = str(seed_dir)

    state_dir = project_dir / "state"
    init_state_dir(state_dir)


def check_stopping_conditions(
    state_dir: Path,
    config: MengerFlockConfig,
    start_time: float,
) -> tuple[bool, str]:
    """Return (triggered, reason) based on current results and config limits."""
    sc = config.stopping_conditions
    results = read_results(state_dir)

    # Max iterations
    if len(results) >= sc.max_total_iterations:
        return True, f"Max iterations reached ({sc.max_total_iterations})"

    # Max hours
    elapsed_hours = (time.time() - start_time) / 3600
    if elapsed_hours >= sc.max_hours:
        return True, f"Max hours reached ({sc.max_hours}h)"

    # Target improvement
    # NOTE: Uses the first "keep" result as the baseline rather than baseline_holdout.
    # This is a rough heuristic — it measures improvement within the research loop,
    # not against the true pre-experiment baseline. The strategist performs the
    # definitive holdout comparison in Phase 3.
    keep_results = [r for r in results if r["status"] == "keep"]
    # Filter to numeric metric values only (agents sometimes log non-numeric values)
    numeric_keeps = []
    for r in keep_results:
        try:
            float(r["metric_avg"])
            numeric_keeps.append(r)
        except (ValueError, TypeError):
            pass
    if numeric_keeps:
        best_avg = min(float(r["metric_avg"]) for r in numeric_keeps)
        first_keep = numeric_keeps[0]
        baseline = float(first_keep["metric_avg"])
        improvement = baseline - best_avg
        if improvement >= sc.target_improvement:
            return True, f"Target improvement reached ({improvement:.4f} >= {sc.target_improvement})"

    # Stagnation
    if len(results) >= sc.stagnation_window:
        recent = results[-sc.stagnation_window:]
        if not any(r["status"] == "keep" for r in recent):
            return True, f"Stagnation: no improvement in last {sc.stagnation_window} iterations"

    return False, ""


def _safe_symlink(link: Path, target: Path) -> None:
    """Create a symlink, ignoring if it already exists."""
    try:
        link.symlink_to(target)
    except FileExistsError:
        pass


class Orchestrator:
    def __init__(self, project_dir: Path, config: MengerFlockConfig):
        self.project_dir = project_dir.resolve()
        self.config = config
        self.state_dir = project_dir / "state"
        self.start_time = None  # set when Phase 2 begins
        self._shutdown = False

    def _ensure_clean_tmux_session(self) -> None:
        """Kill any existing mengerflock tmux session, then create a fresh one."""
        subprocess.run(
            ["tmux", "kill-session", "-t", "mengerflock"],
            capture_output=True, check=False,
        )
        result = subprocess.run(
            ["tmux", "new-session", "-d", "-s", "mengerflock"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create tmux session: {result.stderr}")

    def _handle_signal(self, signum, frame) -> None:
        self._shutdown = True
        write_shutdown_flag(self.state_dir)

    def setup_signal_handlers(self) -> None:
        """Register SIGINT and SIGTERM handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _setup_worktree_symlinks(self, wt_path: Path, names: list[str]) -> None:
        """Create symlinks from worktree to project root for the given file/dir names."""
        for name in names:
            src = self.project_dir / name
            if src.exists():
                _safe_symlink(wt_path / name, src.resolve())

    def _launch_tmux_window(self, name: str, cwd: Path, tool_cmd: str, prompt: str) -> None:
        """Create a tmux window and send the initial prompt."""
        try:
            subprocess.run([
                "tmux", "new-window", "-t", "mengerflock",
                "-n", name, "-c", str(cwd), tool_cmd,
            ], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to launch {name}: {e.stderr}") from e

        time.sleep(3)

        try:
            subprocess.run([
                "tmux", "send-keys", "-t", f"mengerflock:{name}",
                prompt, "Enter",
            ], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to send prompt to {name}: {e.stderr}") from e

    def launch_strategist(self) -> None:
        """Launch the strategist agent in a new tmux window."""
        tool = self.config.agents.tool
        model_flags = self.config.agents.strategist.model_flags
        tool_cmd = f"{tool} {model_flags} --allowedTools 'Edit,Write,Bash,Read,Glob,Grep,WebSearch,WebFetch'"
        prompt = (
            "Read strategist.md and follow its instructions. "
            "This is the project root directory. "
            "State files are in state/. Benchmarks in datasets/. "
            "Eval script is eval.sh. "
            "After initialization, enter Phase 2 and monitor continuously."
        )
        self._launch_tmux_window("strategist", self.project_dir, tool_cmd, prompt)

    def launch_researcher(self, researcher_id: str, module_name: str) -> None:
        """Launch a researcher agent in its own git worktree and tmux window."""
        wt_path = self.project_dir / ".worktrees" / researcher_id
        branch = f"researcher/{researcher_id}"

        # Each researcher gets its own branch (even when sharing a module)
        create_branch(self.project_dir, branch)
        if not wt_path.exists():
            create_worktree(self.project_dir, wt_path, branch)

        # State dir symlink (always present)
        _safe_symlink(wt_path / "state", self.state_dir.resolve())

        # Shared resources from project root
        self._setup_worktree_symlinks(wt_path, ["eval.sh", "datasets", "researcher.md"])

        tool = self.config.agents.tool
        model_flags = self.config.agents.researchers.model_flags
        tool_cmd = f"{tool} {model_flags} --allowedTools 'Edit,Write,Bash,Read,Glob,Grep,WebSearch,WebFetch'"
        prompt = (
            f"Read researcher.md and follow its instructions. "
            f"Your researcher ID is {researcher_id}. "
            f"State, datasets, and eval.sh are symlinked in your working directory."
        )
        self._launch_tmux_window(researcher_id, wt_path, tool_cmd, prompt)

    def monitor_phase2(self, poll_interval: float = 30.0) -> str:
        """Monitor Phase 2. Returns reason for exit: 'stopping', 'phase2_complete', 'shutdown', 'exited'."""
        while not self._shutdown:
            # Check if strategist signaled Phase 2 complete (ready for Phase 3)
            if is_phase2_complete(self.state_dir):
                print("Strategist signaled Phase 2 complete. Entering Phase 3.")
                return "phase2_complete"

            # Check stopping conditions
            triggered, reason = check_stopping_conditions(
                self.state_dir, self.config, self.start_time,
            )
            if triggered:
                print(f"Stopping condition met: {reason}")
                write_shutdown_flag(self.state_dir)  # tell researchers to stop
                return "stopping"

            if is_shutdown_requested(self.state_dir):
                return "shutdown"

            # Check if tmux session still has windows
            result = subprocess.run(
                ["tmux", "list-windows", "-t", "mengerflock"],
                capture_output=True, check=False
            )
            if result.returncode != 0:
                print("All sessions have exited")
                return "exited"

            time.sleep(poll_interval)
        return "shutdown"

    def wait_for_phase3(self, poll_interval: float = 10.0) -> str:
        """Wait for strategist to complete Phase 3.
        Returns: 'complete', 'reenter_phase2', or 'shutdown'."""
        print("Phase 3: Strategist is evaluating holdout and writing reports...")
        while not self._shutdown:
            if is_phase3_complete(self.state_dir):
                print("Phase 3 complete. Experiment finished.")
                return "complete"

            # Check if strategist requests Phase 2 re-entry
            reentry_path = self.state_dir / "reenter_phase2"
            if reentry_path.exists():
                reentry_path.unlink()  # consume the signal
                print("Strategist requests Phase 2 re-entry.")
                return "reenter_phase2"

            # Check if strategist window still alive
            result = subprocess.run(
                ["tmux", "list-windows", "-t", "mengerflock", "-F", "#{window_name}"],
                capture_output=True, text=True, check=False
            )
            if result.returncode != 0 or "strategist" not in result.stdout:
                print("WARNING: Strategist exited before completing Phase 3.")
                return "complete"  # don't block forever

            time.sleep(poll_interval)
        return "shutdown"

    def stop_researchers(self) -> None:
        """Stop researcher and wildcard windows, keep strategist alive."""
        write_shutdown_flag(self.state_dir)

        result = subprocess.run(
            ["tmux", "list-windows", "-t", "mengerflock", "-F", "#{window_name}"],
            capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            for window in result.stdout.strip().split('\n'):
                if window and window != "strategist":
                    subprocess.run([
                        "tmux", "send-keys", "-t", f"mengerflock:{window}",
                        "/exit", "Enter"
                    ], check=False)

    def relaunch_researchers(self) -> None:
        """Relaunch researchers for Phase 2 re-entry. Clean up old worktrees first."""
        # Remove shutdown flag so researchers don't immediately exit
        shutdown_path = self.state_dir / "shutdown"
        if shutdown_path.exists():
            shutdown_path.unlink()

        # Clear phase signals
        for f in ["phase2_complete", "phase3_complete"]:
            p = self.state_dir / f
            if p.exists():
                p.unlink()

        count = self._determine_researcher_count()
        print(f"  Relaunching {count} researcher(s)")

        for i in range(count):
            rid = f"r{i + 1}"
            module = self.config.modules[i % len(self.config.modules)]
            wt_path = self.project_dir / ".worktrees" / rid
            if wt_path.exists():
                remove_worktree(self.project_dir, wt_path)
            self.launch_researcher(rid, module.name)

        if self.config.agents.wildcard:
            wt_path = self.project_dir / ".worktrees" / "w1"
            if wt_path.exists():
                remove_worktree(self.project_dir, wt_path)
            self.launch_wildcard()

    def shutdown(self, keep_strategist: bool = False) -> None:
        """Send /exit to all (or non-strategist) tmux windows and set shutdown flag."""
        self._shutdown = True
        write_shutdown_flag(self.state_dir)

        result = subprocess.run(
            ["tmux", "list-windows", "-t", "mengerflock", "-F", "#{window_name}"],
            capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            for window in result.stdout.strip().split('\n'):
                if window and (not keep_strategist or window != "strategist"):
                    subprocess.run([
                        "tmux", "send-keys", "-t", f"mengerflock:{window}",
                        "/exit", "Enter"
                    ], check=False)

    def wait_for_phase1(self, poll_interval: float = 10.0) -> bool:
        """Wait for strategist to complete Phase 1 (user approval gate).
        Returns True if Phase 1 completed, False if shutdown was requested."""
        print("Waiting for strategist to complete Phase 1 (user approval)...")
        print("  The strategist is researching the domain and preparing a plan.")
        print("  Approve it in tmux:  tmux attach -t mengerflock")
        print("")
        while not self._shutdown:
            if is_phase1_complete(self.state_dir):
                print("Phase 1 complete. Launching researchers.")
                return True
            if is_shutdown_requested(self.state_dir):
                print("Shutdown requested during Phase 1.")
                return False
            time.sleep(poll_interval)
        return False

    def _determine_researcher_count(self) -> int:
        """Determine how many researchers to launch.

        Priority:
        1. Explicit count in config (agents.researchers.count)
        2. Number of assignment files written by strategist (state/assignments/r*.yaml)
        3. Number of modules in config
        """
        if self.config.agents.researchers.count is not None:
            return self.config.agents.researchers.count

        # Count assignment files the strategist created
        assignments_dir = self.state_dir / "assignments"
        if assignments_dir.exists():
            assignment_files = sorted(assignments_dir.glob("r*.yaml"))
            if assignment_files:
                return len(assignment_files)

        return len(self.config.modules)

    def launch_all_researchers(self) -> None:
        """Launch all researcher and wildcard windows."""
        count = self._determine_researcher_count()
        print(f"  Launching {count} researcher(s)")

        for i in range(count):
            rid = f"r{i + 1}"
            module = self.config.modules[i % len(self.config.modules)]
            self.launch_researcher(rid, module.name)

        if self.config.agents.wildcard:
            self.launch_wildcard()

    def _clear_stale_signals(self) -> None:
        """Remove stale phase signals and shutdown flag from a previous run."""
        for name in ["shutdown", "phase1_complete", "phase2_complete",
                      "phase3_complete", "reenter_phase2"]:
            path = self.state_dir / name
            if path.exists():
                path.unlink()
                print(f"  Cleared stale signal: {name}")

    def run(self) -> None:
        """Run the full MengerFlock experiment loop (Phases 1, 2, 3)."""
        self.setup_signal_handlers()
        max_reentries = self.config.stopping_conditions.max_reentries
        reentry_count = 0

        # Clear stale signals from any previous run
        self._clear_stale_signals()

        # Create tmux session (kill any stale session first to avoid collision)
        self._ensure_clean_tmux_session()

        # === Phase 1: Strategist researches, presents plan, waits for user approval ===
        print("=== Phase 1: Strategist initialization ===")
        self.launch_strategist()

        if not self.wait_for_phase1():
            return

        # === Phase 2: Researchers evolve the codebase ===
        while True:
            self.start_time = time.time()
            print(f"=== Phase 2: Research loop (attempt {reentry_count + 1}) ===")
            print("  Researchers are evolving the codebase autonomously.")
            dashboard_path = Path(__file__).resolve().parent / "dashboard.sh"
            print("  Monitor progress:")
            print(f"    Dashboard:  bash {dashboard_path} state 15")
            print("    tmux:       tmux attach -t mengerflock")
            print("    Status:     mengerflock status")
            print("    Stop:       mengerflock stop")
            print("")
            self.launch_all_researchers()

            exit_reason = self.monitor_phase2()

            # Stop researchers, keep strategist alive for Phase 3
            self.stop_researchers()

            # Nudge strategist to enter Phase 3
            try:
                subprocess.run([
                    "tmux", "send-keys", "-t", "mengerflock:strategist",
                    "The shutdown flag has been set and all researchers have stopped. Enter Phase 3 now: run holdout evaluation, compare against baselines, and write both reports.",
                    "Enter"
                ], check=False, capture_output=True, text=True)
            except Exception:
                pass

            if exit_reason == "exited":
                print("All sessions exited unexpectedly.")
                return

            # === Phase 3: Strategist evaluates holdout and writes reports ===
            # Triggered by: stopping conditions, shutdown signal, or strategist's phase2_complete
            print("=== Phase 3: Evaluation and reporting ===")
            print("  Strategist is running holdout evaluation and writing reports.")
            print("  Watch progress:  tmux attach -t mengerflock")
            print("")
            phase3_result = self.wait_for_phase3()

            if phase3_result == "complete":
                print("Experiment complete. Shutting down.")
                self.shutdown()
                return

            if phase3_result == "reenter_phase2":
                reentry_count += 1
                if reentry_count >= max_reentries:
                    print(f"Max re-entries reached ({max_reentries}). Finishing.")
                    self.shutdown()
                    return
                print(f"Re-entering Phase 2 (attempt {reentry_count + 1}/{max_reentries + 1})...")
                self.relaunch_researchers()
                continue

            # shutdown or unexpected
            self.shutdown()
            return

    def launch_wildcard(self) -> None:
        """Launch the wildcard agent in its own git worktree and tmux window."""
        wt_path = self.project_dir / ".worktrees" / "w1"
        branch = "wildcard/w1"

        # Wildcard works from original seed — use baseline tag if it exists, else HEAD
        start = "baseline" if ref_exists(self.project_dir, "baseline") else "HEAD"
        create_branch(self.project_dir, branch, start_point=start)
        if not wt_path.exists():
            create_worktree(self.project_dir, wt_path, branch)

        # Restricted state: only results.tsv for writing, no full state/ access
        wt_state = wt_path / "state"
        wt_state.mkdir(exist_ok=True)

        _safe_symlink(wt_state / "results.tsv", (self.state_dir / "results.tsv").resolve())

        # Shutdown detection — symlink the shutdown flag location
        # (wildcard checks if state/shutdown exists)

        objectives_src = self.state_dir / "objectives.md"
        if objectives_src.exists():
            _safe_symlink(wt_path / "objectives.md", objectives_src.resolve())

        self._setup_worktree_symlinks(wt_path, ["eval.sh", "datasets", "wildcard.md"])

        tool = self.config.agents.tool
        wildcard_cfg = self.config.agents.wildcard
        model_flags = wildcard_cfg.model_flags
        tool_cmd = f"{tool} {model_flags} --allowedTools 'Edit,Write,Bash,Read,Glob,Grep'"
        prompt = (
            "Read wildcard.md and follow its instructions. "
            "Read objectives.md for the experiment's high-level goals. "
            "Your ID is w1. "
            "Datasets and eval.sh are in your working directory."
        )
        self._launch_tmux_window("w1", wt_path, tool_cmd, prompt)
