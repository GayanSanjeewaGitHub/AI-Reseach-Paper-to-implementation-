# MengerFlock Architecture

## High-Level System Overview

```
+------------------------------------------------------------------+
|                        YOUR INPUTS                               |
|                                                                  |
|   config.yaml        seed/ (your repo)     datasets/holdout/    |
|   (project config)   (algorithm code)      (benchmarks)         |
+---------------------------+--------------------------------------+
                            |
                            v
+------------------------------------------------------------------+
|                      ORCHESTRATOR                                |
|                                                                  |
|   - Reads config.yaml                                            |
|   - Launches tmux session (one window per agent)                 |
|   - Creates git worktrees for each researcher                    |
|   - Monitors stopping conditions (max hours / iterations)        |
|   - Controls Phase 1 → 2 → 3 transitions                        |
+---+----------+----------+----------+----------+-----------------+
    |          |          |          |          |
    v          v          v          v          v
+-------+ +-------+ +-------+ +-------+ +----------+
|  STR  | |  R1   | |  R2   | |  R3   | |  WILD    |
|ATEGIST| |module | |module | |module | |  CARD    |
|       | |  A    | |  B    | |  C    | |          |
+---+---+ +---+---+ +---+---+ +---+---+ +----+-----+
    |          |          |          |          |
    |          +----------+----------+          |
    |                     |                     |
    |          +----------v----------+          |
    |          |    SHARED STATE     |          |
    +--------> |                     | <--------+
               |  state/             |
               |  ├── results.tsv    |
               |  ├── assignments/   |
               |  │   ├── r1.yaml   |
               |  │   ├── r2.yaml   |
               |  │   └── r3.yaml   |
               |  ├── interrupts/    |
               |  ├── objectives.md  |
               |  └── shutdown       |
               +---------------------+
```

---

## Agent Roles

```
+---------------------+      +-----------------------------+
|     STRATEGIST      |      |        RESEARCHER (x N)     |
|---------------------|      |-----------------------------|
| - Web search domain |      | - Owns one module           |
| - Read papers       |      | - Works in git worktree     |
| - Decompose modules |      | - Loop forever:             |
| - Assign work       |      |   1. Hypothesize            |
| - Read results.tsv  |      |   2. Implement              |
| - Compose best keeps|      |   3. git commit             |
| - Redirect agents   |      |   4. Build                  |
| - Write final report|      |   5. Evaluate               |
+---------------------+      |   6. Keep or Revert         |
                             +-----------------------------+

+------------------------------+
|          WILDCARD            |
|------------------------------|
| - Reads ONLY original-seed/  |
| - No access to other results |
| - No strategist guidance     |
| - Forces novel ideas         |
| - One variable changed/run   |
| - Writes to results.tsv only |
+------------------------------+
```

---

## Phase Lifecycle

```
                         START
                           |
                           v
          +----------------+----------------+
          |           PHASE 1               |
          |         Initialize              |
          |                                 |
          |  Strategist:                    |
          |  1. Web search domain           |
          |  2. Read reference paper        |
          |  3. Analyze seed/ codebase      |
          |  4. Present plan to USER        |
          |  5. WAIT for approval  <------USER MUST APPROVE
          |  6. Write objectives.md         |
          |  7. Run baseline benchmark      |
          |  8. Generate train/val datasets |
          |  9. Create researcher assigns   |
          +----------------+----------------+
                           |
                           v
          +----------------+----------------+
          |           PHASE 2               |
          |        Research Loop            |
          |                                 |
          |  Researchers run in parallel:   |
          |  hypothesize → build → eval     |
          |                                 |
          |  Strategist monitors:           |
          |  - Composes "keep" results      |
          |  - Redirects stagnant agents    |
          |  - Updates assignments          |
          |                                 |
          |  Stops when:                    |
          |  - Max iterations reached  OR   |
          |  - Max hours reached       OR   |
          |  - Target improvement hit       |
          +----------------+----------------+
                           |
                           v
          +----------------+----------------+
          |           PHASE 3               |
          |       Evaluate & Report         |
          |                                 |
          |  1. Run holdout benchmarks      |
          |  2. Compare vs original-seed/   |
          |        |                        |
          |   BETTER?                       |
          |   YES -----> Write research     |
          |              paper              |
          |   NO  -----> Ask user to        |
          |              re-enter Phase 2   |
          +----------------+----------------+
                           |
                           v
                          DONE
                  report/ folder written
```

---

## Researcher Experiment Loop (Detail)

```
          +---------------------------+
          |   Check state/interrupts/ | <----- Strategist can redirect
          +------------+--------------+        at any time via this file
                       |
                       v
          +---------------------------+
          |       HYPOTHESIZE         |
          |  Form one-line hypothesis |
          +------------+--------------+
                       |
                       v
          +---------------------------+
          |  git checkout -b          |
          |  hypothesis/<name>        |
          |  origin/main              |  <--- always starts from clean main
          +------------+--------------+
                       |
                       v
          +---------------------------+
          |        IMPLEMENT          |
          |   Edit assigned files     |
          +------------+--------------+
                       |
                       v
          +---------------------------+
          |     BUILD & EVALUATE      |
          |   Run eval.sh → metric    |
          +------------+--------------+
                       |
              +--------+--------+
              |                 |
           BETTER?           WORSE?
              |                 |
              v                 v
   +------------------+  +------------------+
   |  Regression Gate |  |  git revert      |
   |  (test on main)  |  |  log "discard"   |
   +--------+---------+  +------------------+
            |
     PASS?  |  FAIL?
       |         |
       v         v
  +--------+  +------------------+
  |  KEEP  |  |  git revert      |
  |  log   |  |  log "discard"   |
  |"keep"  |  +------------------+
  +---+----+
      |
      v
  Strategist sees it in results.tsv
  and cherry-picks onto main
```

---

## Git Worktree Layout

```
project-dir/
├── config.yaml
├── eval.sh
├── datasets/
│   └── holdout/          <-- your benchmarks (never touched by agents)
├── seed/                 <-- main branch (evolving codebase)
├── original-seed/        <-- NEVER modified (baseline reference)
├── state/
│   ├── results.tsv       <-- all experiment logs
│   ├── objectives.md     <-- approved research goals
│   ├── assignments/
│   │   ├── r1.yaml
│   │   └── r2.yaml
│   └── interrupts/
├── worktrees/
│   ├── r1/               <-- Researcher 1 isolated git worktree
│   ├── r2/               <-- Researcher 2 isolated git worktree
│   └── wildcard/         <-- Wildcard isolated git worktree
└── report/
    ├── experimentation-report.md   <-- always written
    └── research-report.md          <-- only if evolved beats baseline
```
