# AdaCoM — Learning Agent-Compatible Context Management for Long-Horizon Tasks
> Paper: arXiv 2605.30785v1 | May 2026 | Renmin University of China × Tongyi Lab (Alibaba)

---

## 🧩 The Problem — A Story Worth Telling

Imagine you hired a brilliant researcher to answer a very hard question.
You give them a desk, a search engine, and tell them: *"Keep digging until you find the answer."*

After 20 search rounds, something breaks.
The desk is **covered in paper**.
Old dead-end notes are stacked on top of fresh clues.
The researcher starts forgetting what constraints the question even had.
They repeat searches they already ran.
Eventually they just give up — not because the answer doesn't exist, but because **the desk got too messy**.

This is *exactly* what happens to LLM agents on long-horizon tasks.

### What is a "Long-Horizon Task"?
Tasks like:
- **Web research** — "Find the person who won X award in Y year and also wrote Z paper."
- **Deep research reports** — Multi-step Wikipedia traversal to synthesize a structured report.

These require **35+ tool calls** chained across many reasoning steps, with each step appending new context (actions + observations) to a growing message window.

### The Core Failure Mode: Long-Context Degradation
As the context window fills up:
| Problem | What happens |
|---|---|
| **Constraint forgetting** | Agent forgets part of the original task requirements |
| **Premature abandonment** | Agent gives up early after a few failed searches |
| **Redundant exploration** | Agent issues identical tool calls it already tried (42.6% of Kimi's steps were repetitive!) |
| **Positional bias** | Relevant clues buried in the middle get ignored |

---

## 💡 Prior Solutions and Why They Fall Short

Before AdaCoM, people tried:

| Approach | How it works | Why it's limited |
|---|---|---|
| **SumAgent / MEM1** | Agent summarizes its own trajectory each step | Requires the agent to change its own behavior → needs agent retraining |
| **MemAct** | Agent invokes a "prune" tool manually | Agent must learn new tool-use protocols → needs agent retraining |
| **ReSum** | Summarize when context hits token limit | Fixed operation — same strategy for every agent regardless of capability |

**The fundamental flaw in all prior work:**
> They ask the *agent itself* to manage its own memory.
> But if the agent is a closed-source model (GPT-4o, Claude, Gemini), you can't retrain it.
> And even if you can, one-size-fits-all summarization ignores the fact that **different agents need different strategies**.

---

## 🚀 The Solution — AdaCoM (Adaptive Context Management)

### Two Core Principles

**1. Architectural Decoupling**
An *external* smaller LLM (Qwen3-4B-Instruct) acts as a **Context Manager** sitting between the environment and the frozen agent.
The agent never changes. The manager intercepts and edits the context before every step.

**2. Operation-Level Flexibility**
Instead of locking in "summarization" as the only operation, the manager outputs a **JSON modification plan** that can:
- `rewrite` — compress/rephrase selected messages
- `delete` — remove stale/irrelevant content (empty `new_content`)
- `merge` — combine multiple messages into one
- `no-op` — leave everything unchanged when fidelity matters

```json
{
  "modifications": [
    {
      "ids": ["msg_3", "msg_4"],
      "role": "user",
      "justification": "Merge redundant search results into a single clue summary",
      "new_content": "Search for 'X' returned doc_42 (relevant: mentions Y) and doc_99 (irrelevant)."
    },
    {
      "ids": ["msg_7"],
      "role": "user",
      "justification": "Remove stale dead-end result",
      "new_content": ""
    }
  ]
}
```

### How Training Works

```
Step 1 — SFT Warm-up
  GPT-5 / Claude Opus 4.6 generate expert edit trajectories
  Qwen3-4B learns the JSON output FORMAT only (not strategy)

Step 2 — Reinforcement Learning (GRPO)
  Agent is FROZEN. Only manager weights update.
  Reward = final task correctness (binary for web search, rubric for deep research)
  
  Process rewards (rule-based, no LLM judge needed):
  ├── Token penalty       → if managed context exceeds 32K limit
  ├── Redundant penalty   → if agent issues duplicate tool calls back-to-back
  └── Format penalty      → JSON parse errors / bad message IDs

Step 3 — Two-Level Advantage Estimation
  Task-level:  Normalize outcome reward across rollout group
  Step-level:  Normalize process rewards across all steps
  Combined:    A_final = A_outcome + α × A_process   (α = 0.1)
```

---

## 🔬 The Key Discovery — Fidelity–Reliability Trade-off

After training separate managers for 4 agents, they found a **consistent pattern** across all of them:

```
Agent Capability (ReAct baseline)  →  Manager Strategy
─────────────────────────────────────────────────────────
GLM-4.5-Air   (strongest, 32.6%)  →  Tiered: let context grow, batch compress rarely
                                       Mean post-context: ~7,000 tokens
Qwen3-Max     (27.8%)             →  Tiered: similar, slightly more compression
                                       Mean post-context: ~5,200 tokens
Kimi-K2       (18.6%)             →  Eager distillation: compress almost every round
                                       Mean post-context: ~3,400 tokens
DeepSeek-V3   (weakest, 17.8%)    →  Eager distillation: most aggressive
                                       Mean post-context: ~1,900 tokens
```

**The insight:**
> Stronger agents can exploit longer raw contexts → preserve more.
> Weaker agents are hurt by long contexts → compress more aggressively.
> There is an *effective context length* for each agent beyond which raw content becomes harmful.

This directly explains why `SumCoM` (always summarize) degrades GLM — it forces an eager-distillation strategy on an agent that thrives on raw detail.

---

## 📊 Results — Does It Actually Work?

### BrowseComp-Plus (Web Search, 150 test tasks)
| Agent | ReAct (baseline) | AdaCoM | Gain |
|---|---|---|---|
| Qwen3-Max | 27.78% | **36.67%** | +32% |
| Kimi-K2-Instruct | 18.56% | **36.20%** | **+95%** |
| GLM-4.5-Air | 32.56% | **35.33%** | +8.5% |
| DeepSeek-V3 | 17.78% | **26.19%** | +47% |
| **Average** | **24.17%** | **33.60%** | **+39%** |

All competitors (SumAgent, MemAct, SumCoM, no-training baseline) fail to beat ReAct consistently across all agents. AdaCoM is the only one with **no regressions**.

### MCP-Bench-Wiki (Deep Research)
| Agent | ReAct | AdaCoM | Gain |
|---|---|---|---|
| Kimi-K2-Instruct | 55.05 | **60.01** | +9% |
| DeepSeek-V3 | 47.51 | **58.09** | +22.3% |

### Cross-Agent Transfer
- 23 of 28 cross-agent pairs achieve positive gains
- Average 22.1% relative gain even when transferring to *unseen* agents
- **Best cross-agent result:** Kimi under DeepSeek-trained manager → +79.6% (vs 95% self-trained)

**Practical rule:** Match managers by capability tier. Stronger agents → use strong-agent-trained managers. Weaker agents → use weak-agent-trained managers.

---

## ✨ Why It Is Unique

| Property | AdaCoM | All Prior Work |
|---|---|---|
| Agent stays frozen | ✅ Works with any closed-source API | ❌ Most require agent retraining |
| Flexible action space | ✅ Rewrite / delete / merge / no-op | ❌ Only summarization |
| Agent-specific strategy | ✅ Learns per-agent via RL | ❌ One-size-fits-all |
| Transferable | ✅ Capability-proximity transfer | ❌ Not studied |
| Manager size | ✅ 4B params (cheap) | Varies |
| No LLM judge at training time | ✅ Rule-based process rewards | Some use LLM judges |

---

## 🛠️ Is It Possible to Implement? — YES, and Here's How

### Minimal Viable Implementation Plan

#### Architecture (3 components)

```
┌─────────────────────────────────────────────────┐
│                   TASK LOOP                     │
│                                                 │
│  User Query ──► [Context Buffer]                │
│                      │                          │
│                 (each step)                     │
│                      ▼                          │
│  ┌─────────────────────────┐                   │
│  │  CONTEXT MANAGER (4B)   │  ◄── You train    │
│  │  Qwen3-4B-Instruct      │      this part    │
│  │  Input: full context    │                   │
│  │  Output: JSON mod plan  │                   │
│  └─────────────────────────┘                   │
│                      │                          │
│            apply modifications                  │
│                      ▼                          │
│  ┌─────────────────────────┐                   │
│  │   FROZEN AGENT (any)    │  ◄── Never touch  │
│  │   GPT-4o / Claude /     │      this part    │
│  │   Qwen3-Max / local LLM │                   │
│  └─────────────────────────┘                   │
│                      │                          │
│                 tool call                       │
│                      ▼                          │
│           [Environment / Tools]                 │
└─────────────────────────────────────────────────┘
```

#### What You Need

| Component | Recommended Option | Notes |
|---|---|---|
| Manager model | `Qwen/Qwen3-4B-Instruct` | Open source, ~8GB VRAM |
| RL Framework | `Trinity-RFT` (Apache 2.0) | Paper uses this exactly |
| Agent Framework | `AgentScope` (Apache 2.0) | Paper uses this |
| Frozen Agent | Any API model | GPT-4o, Claude, Qwen3-Max, local |
| Training task | BrowseComp-style Q&A or custom | Need 500-1000 training instances |
| Context budget | 32K tokens for manager input | Paper's exact setting |

#### Implementation Steps (Ordered)

```
Phase 1 — Scaffold (1-2 days)
  ✅ Build context buffer with message IDs
  ✅ Build manager inference wrapper (input context → JSON plan → apply edits)
  ✅ Build agent wrapper (any target LLM API)
  ✅ Build tool environment (even just web search / Wikipedia API)

Phase 2 — SFT Warm-up (1-2 days)
  ✅ Generate ~200 example trajectories using GPT-4o as manager
  ✅ Fine-tune Qwen3-4B on (context, edit_plan) pairs
  ✅ Goal: teach JSON output format ONLY

Phase 3 — RL Training (the hard part, 2-7 days GPU time)
  ✅ Set up GRPO with Trinity-RFT
  ✅ Implement process rewards (token limit penalty, repetition penalty, format penalty)
  ✅ Run rollouts: sample 8 trajectories per query, score, update manager
  ✅ Context budget: cap agent context at 32K tokens

Phase 4 — Evaluation
  ✅ Compare frozen agent alone vs agent + trained manager
  ✅ Track: correct answers, early give-ups, redundant tool calls
```

#### Minimal "No-Training" Prototype (Can Build TODAY)

Even without RL, you can test the concept with a prompted manager:

```python
import openai

MANAGER_SYSTEM = """You are a Context Manager. Given the agent's conversation history 
as JSON messages with IDs, output a JSON modification plan to:
- Remove stale/irrelevant tool results
- Compress verbose observations
- Preserve task constraints and found clues
- Preserve document IDs

Return: {"modifications": [{"ids": [...], "role": "user", "justification": "...", "new_content": "..."}]}
Return {"modifications": []} if no changes needed."""

def manage_context(messages_with_ids: list, token_count: int) -> list:
    context_str = json.dumps(messages_with_ids)
    ratio = f"{token_count / 32000:.0%}"
    
    response = openai.chat.completions.create(
        model="gpt-4o-mini",  # cheap manager
        messages=[
            {"role": "system", "content": MANAGER_SYSTEM},
            {"role": "user", "content": f"Token usage: {ratio}\n\nContext:\n{context_str}"}
        ]
    )
    plan = json.loads(response.choices[0].message.content)
    return apply_modifications(messages_with_ids, plan["modifications"])
```

This gives you AdaCoM *without training* — weaker than the RL version but demonstrable in a weekend.

---

## 📌 Key Limitations to Know Before Implementing

| Limitation | Impact | Mitigation |
|---|---|---|
| Extra inference per step | ~2x token cost + latency | Invoke manager only every N steps or when context > threshold |
| KV cache invalidation | Re-computation when context changes | Use tiered strategy (compress rarely for strong agents) |
| 4B manager capacity | May lossy-compress for very strong agents | Use larger manager (7B/8B) for GPT-4o class targets |
| Only tested on search/research | May not generalize to code agents | Adapt process rewards for the new domain |
| RL training cost | GPU-hours on GRPO | Start with the no-training prompted version |

---

## 🗺️ Summary in One Paragraph

**AdaCoM solves the "messy desk" problem for LLM agents.** When an agent accumulates 30+ tool calls worth of context, it starts forgetting constraints, repeating itself, and giving up. AdaCoM inserts a small trained external LLM as a context editor — it sits between the environment and the frozen agent, surgically trimming, rewriting, and organizing the context window before each step. Trained with reinforcement learning (agent frozen, only manager learns), it discovers that strong agents need their context preserved faithfully while weak agents need aggressive compression — a principle the paper calls the **Fidelity–Reliability Trade-off**. The result: +39% average gain on web search, +15% on deep research, and the trained manager transfers to unseen agents with similar capability. The full system is implementable today using open-source tools (Qwen3-4B, Trinity-RFT, AgentScope), and even a zero-training prompted version can demonstrate the core idea in a weekend.

---

*Paper: arXiv 2605.30785v1 — Lu Yi, Runlin Lei et al., May 29 2026*
*Code: https://anonymous.4open.science/r/AdaCoM-8864/*
