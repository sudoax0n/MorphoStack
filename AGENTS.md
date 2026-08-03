# Repository Guidelines

MorphoStack is a local morphometry toolkit for microscopy Z-stacks (vesicle/GUV, RBC, experimental `active_surfaces`). Python core powers a CLI, FastAPI backend, and Vite browser UI. Prefer fixing science and pipeline logic in `core/`; keep CLI/API/UI as thin layers.

## Project Structure & Module Organization

| Path | Role |
| --- | --- |
| `src/morphostack/core/` | Analysis engine (I/O, segmentation, metrics, mesh, pipeline, export) |
| `src/morphostack/cli/` | `morphostack` / `mst` entry points |
| `src/morphostack/api/` | FastAPI app |
| `apps/web/` | TypeScript + Vite UI (`src/main.ts`, `dist/` for packaging) |
| `tests/` | pytest suite (`test_*.py`) |
| `validation/` | Intentional runs, reports, reference metrics (tracked) |
| `docs/` | User docs (`docs/README.md` index; assets in `docs/public/`) |
| `scripts/` | Validation and release helpers |
| `improvements.md` | Living product checklist and known gaps |
| `graphify-out/` | Optional knowledge graph for agent navigation (see below) |

Do not treat `mcps/`, `scratch/`, `terminals/`, or `.clones/` as product source (see `REFERENCE_FOLDERS.md`).

## Build, Test, and Development Commands

```bash
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"   # or ".[all]" for analysis+api
.\.venv\Scripts\morphostack doctor                  # env diagnostics
.\.venv\Scripts\morphostack init --web              # optional deps + web install
.\.venv\Scripts\pytest                              # full unit suite
.\.venv\Scripts\morphostack serve                   # API only
.\.venv\Scripts\morphostack dev                     # API + web together
cd apps\web && npm install && npm run build         # typecheck + static dist
```

Canonical CLI is `morphostack`; `mst` is the short alias. Analysis examples: `inspect`, `threshold`, `sweep`, `analyze`, `batch`, `validate`.

## Coding Style & Naming Conventions

- **Python ≥3.11**, package under `src/`. Prefer type hints and frozen dataclasses for public data (`VoxelSize`, ROI, seeds).
- Naming: modules/functions `snake_case`; classes `PascalCase`; tests `test_<area>.py` / `test_<behavior>`.
- Physical units: metrics in µm with explicit `VoxelSize`; never silently treat default 1×1×1 µm as calibrated biology.
- **Web**: TypeScript, 2-space indent in existing UI files. No project-wide ruff/black/eslint config—match surrounding style.
- Profiles: `vesicle`, `rbc`, `active_surfaces` (do not resurrect old LimeSeg naming).

## Testing Guidelines

- Framework: **pytest** (`pythonpath = ["src"]` in `pyproject.toml`).
- Run: `pytest` or `pytest tests/test_core_metrics.py`. Mark heavy real-stack tests `@pytest.mark.slow`.
- Add/adjust tests with core changes. Prefer synthetic fixtures over huge binaries in unit tests; put lab regression artifacts under `validation/runs/`.

## Commit & Pull Request Guidelines

History mixes conventional prefixes (`feat:`, `fix:`, `docs:`, `chore:`, `validation:`) and plain imperative sentences (“Add frame exclusion…”). Prefer short, focused commits: what changed and why.

PRs should state user-visible impact, note CLI/API/UI surface changes, link issues if any, and include validation evidence (pytest, script output, or preview notes) for science/export changes. Screenshots help for web UI.

## Agent-Specific Instructions

- Read `improvements.md` and `docs/limitations.md` before expanding scope.
- Do not add Cellpose/StarDist as required deps or rewrite the frontend from scratch without need.
- Keep calibration warnings and manifests honest; document assumptions in reports.
- Avoid destructive git ops and do not commit secrets or local tooling noise.

## Agent orchestration

- The current Codex session is the **orchestrator, planner, reviewer, and integrator**.
- Executors must use independent technical judgment at every task and step. They must inspect evidence, reason about consequences, and challenge incorrect or incomplete packet assumptions instead of blindly following the orchestrator. Any deviation must be explained in the execution report.
- Implementation packets should normally ask the executor to parallelize genuinely independent scouting, analysis, testing, and review work with multiple subagents when doing so materially saves time without lowering quality. Do not create subagents for tiny or sequential work, and never give subagents overlapping write ownership.
- The selected executor remains the sole owner of the implementation and shared working tree. Subagent output is advisory until the executor personally reviews it, checks any proposed diff, resolves conflicts, and reruns the relevant validation. Never pass unreviewed subagent work to the orchestrator as complete.
- Every executor must return a compact execution report containing: reasoning and decisions; subagents used and what each did; changed files; validation commands and results; unresolved risks; and any deviations from the packet. The orchestrator then reviews the actual diff and evidence and gives an accept / needs-correction / reject verdict with a rating.
- **Strict simplicity rule:** for a direct file or text edit, edit only the requested file and stop. Do not introduce or discuss Git status, diffs, staging, commits, branches, merges, pushes, agents, plans, audits, tests, or other workflow unless the user explicitly asks for them or they are strictly required for safety or correctness.
- At the beginning of **every new implementation task**, before editing code or invoking another agent/CLI, ask:

  > Choose the executor for this task:  
  > 1. Grok 4.5 High - preferred external executor  
  > 2. Gemini 3.5 High - fast executor, especially for broad code changes  
  > 3. Codex Executor - Terra Medium  
  > 4. Main Codex session  
  >
  > Choose repository scouting:  
  > A. Gemini 3.5 High - preferred external scout  
  > B. Codex Repo Scout - Luna High, read-only  
  > C. No scout

- Wait for the user's choice. Never silently choose or invoke an external CLI.
- User preferences are: Grok 4.5 High, Gemini 3.5 High, or Codex Executor for execution; Gemini 3.5 High or Codex Repo Scout for scouting.
- Route high-reasoning, ambiguous, scientific, architectural, or otherwise "high-IQ" tasks to **Grok 4.5 High** by default when the user selects external execution. Route straightforward implementation, broad mechanical edits, and other simple executable tasks to **Gemini 3.5 High** by default. These are routing preferences, not authorization; still ask for the executor and scout at the start of every implementation task.
- Treat these as preferences, not automatic authorization: ask every time before choosing an executor or scout.
- External execution is not limited to Grok; use whichever executor the user selects.
- Do not configure or assume unsupported CLI commands. Detect installed tools before invoking them.

### External-harness command reference

- **Grok harness (`grok`):** first run the bounded availability check `grok models` when available. Use the exact returned model ID in the same invocation: one-shot direct prompt `grok --model <MODEL_ID> --single "<TASK_PACKET>"`; interactive initial prompt `grok --model <MODEL_ID> "<TASK_PACKET>"`. A bounded isolated-worktree invocation may add `--worktree=<NAME> --max-turns <N> --permission-mode acceptEdits --single`.
- `grok build` is not a distinct supported build subcommand and must not be prescribed. Do not hardcode `grok-4.5-high`: the local scout observed only cached `grok-build`; if the preferred exact model is unavailable, ask the user before substituting.
- **Antigravity/Gemini harness (`agy`):** first run the bounded availability check `agy models` when available. Use the exact returned model ID in the same invocation: one-shot direct prompt `agy --model <MODEL_ID> --mode accept-edits --print "<TASK_PACKET>"`; interactive initial prompt `agy --model <MODEL_ID> --prompt-interactive "<TASK_PACKET>"`.
- Do not hardcode Gemini 3.5 High: local `agy models` could not verify eligibility/login because of proxy/network errors. If the preferred exact model is unavailable, ask the user before substituting. `--dangerously-skip-permissions` requires explicit user approval.

### External executor failure policy

- **Current local-harness status (2026-07-11):** Grok 4.5 and Gemini scouting/execution are not working reliably through their local CLIs on this machine. Until the user says the harnesses are fixed, do not invoke either CLI. Prepare bounded, reusable artifacts and exact prompts under `.agent-runs/<task>/` for the user to run manually in the selected external model instead. Use Codex Repo Scout (Luna High, read-only) only when the user selects scouting option B.
- If the selected Grok or Gemini/Antigravity executor is blocked, denied, unavailable, or fails to start, STOP and inform the user.
- Never substitute Codex Executor, Codex subagents, or the main session without explicit user approval.
- Never create extra implementation passes to compensate for the blocked agent.
- Do not retry or attempt to bypass a security denial.
- Preserve the task packet and provide the exact plan for the user to run manually in an external CLI.
- After the external run finishes, review the existing diff; do not independently reimplement the task unless the user explicitly requests it.

- When Grok is selected, prefer Grok 4.5 High if the installed CLI/account exposes it.
- When Gemini/Antigravity is selected, prefer Gemini 3.5 High if the installed CLI/account exposes it.
- If an exact preferred model is unavailable, ask before substituting another model.
- Only **one write-capable executor** may work at a time. Never let multiple agents edit the same working tree concurrently.
- Prefer an isolated Git worktree for an external write-capable executor.
- Before scouting, inspect the current branch, `git status`, and any relevant existing diff. The scout must distinguish baseline code from user or unfinished changes and remain read-only.
- Every scout must return a **ranked evidence map** containing:
  - a must-read list of the 3-5 most relevant files, ordered by importance;
  - exact file paths, symbols, and relevant line ranges, with one sentence explaining why each item matters;
  - the relevant execution flow (for example, UI -> API -> core -> tests);
  - a supporting-file list, a complete inventory of files actually inspected, and any unproven assumptions or risks.
- Before planning or delegating implementation, the orchestrator must directly read the scout's must-read source sections. Use the evidence map for surgical verification; do not repeat the scout's broad search.
- Before delegation, give the executor a bounded task packet containing:
  - goal and acceptance criteria;
  - relevant files/symbols already known;
  - constraints and files that must not change;
  - targeted validation commands.
- The orchestrator must review the resulting diff and test results before accepting the work.
- Do not use the OpenAI Agents SDK for this workflow unless the user explicitly requests separately billed API orchestration.

## Repository and context budget

- Never scan or read the full repository at session start.
- Start with paths, symbols, errors, and modules named in the task.
- Never run unbounded `find`, `tree`, recursive listings, or repository-wide `rg` output.
- Prefer scoped `git ls-files`, `rg -l`, symbol searches, and bounded line ranges.
- Do not print entire large files, arrays, test logs, metadata dumps, generated files, build output, environments, dependencies, binaries, datasets, or lockfiles unless required.
- Run the narrowest relevant tests first.
- Save verbose external-agent output under `.agent-runs/<task>/`; return only a compact summary, changed-file list, diff path, and test-result path to the orchestrator.
- Do not paste full external CLI transcripts into the Codex conversation.
- Use the scout only when repository location or execution flow is unclear. Do not scout again when adequate context already exists.

## Knowledge Graph (graphify) — orientation aid

When `graphify-out/graph.json` exists, use it to **orient** before broad greps on architecture questions (“how does X connect to Y?”, “what sits near active surfaces?”, “what are the hubs?”). Prefer the installed **graphify** skill (`/graphify query`, path, explain) over rebuilding the graph for every question.

| Path | Use |
| --- | --- |
| `graphify-out/GRAPH_REPORT.md` | God nodes, communities, surprising links, suggested questions |
| `graphify-out/graph.html` | Interactive map (human browsing) |
| `graphify-out/graph.json` | Queryable graph data |

**How to use it**
- Architecture / navigation first: report → graph query → then open the real source under `src/morphostack/`.
- Treat **EXTRACTED** edges as structural; **INFERRED** / **AMBIGUOUS** as hints only.
- Source of truth remains code, tests, and docs — not the graph. The graph can be stale after large refactors.
- Typical hubs in this repo: `analyze_stack()`, `VoxelSize`, `ObjectSeed`, `ZRange`, CLI/API/UI thin layers over `core/`.
- Rebuild only when asked or after large structural change: `/graphify` or `/graphify --update` on the project root. Do not commit secrets; treat `graphify-out/` as local tooling unless the user wants it tracked.

Routine one-file fixes, test green-ups, and already-documented patterns do **not** require a graph rebuild or query.

## Deep Research Protocol ("Ego-Free")

The developer has **high-level deep-research access** across **Grok DeepSearch**, **ChatGPT deep research**, and **Gemini Deep Research**. Use them for complex biological, computer-vision, meshing, or algorithmic problems instead of guessing or shipping sub-optimal solutions.

**Trigger this protocol when:**
- **Algorithmic complexity** — unsure of the best lightweight tracking/association approach (Hungarian algorithm, Kalman filters, ellipse fitting, occlusion handling, watershed vs active surfaces for touching objects).
- **Biological / morphometry standards** — unsure of standard definitions or accepted formulas (sphericity, deformation index, RBC indices, vesicle deflation metrics, physical units and calibration conventions).
- **Unclear system behavior** — hit an error or dependency limitation you cannot resolve after a quick search.
- **Method choice under uncertainty** — competing approaches for mesh measurement, contour smoothing, seed tracking across Z, or profile-specific science where the wrong default would mislead lab users.

**You must:**
1. **Drop your ego** — stop guessing or writing arbitrary code for that feature.
2. **Draft a context & prompt** — write a detailed summary of the codebase state, the exact problem, constraints (local/offline-friendly, no heavy DL deps unless justified), and a structured **deep-research prompt** the user can paste into Grok, ChatGPT, or Gemini.
3. **Delegate** — present the prompt, note which engine(s) are suitable if relevant, and ask the user to run deep research and return the report (save outputs under `researches/` when provided).
4. **Pause** — wait for the report before writing implementation code for that specific feature.

Routine refactors, UI polish, test fixes, and already-documented patterns in this repo do **not** require deep research.

## Avoid overthinking

- Prefer the smallest sufficient action that directly advances the requested outcome.
- Treat straightforward, bounded tasks as straightforward; do not turn them into architecture exercises, broad audits, or extra planning passes.
- When the evidence and next action are clear, act. Do not repeatedly reconfirm, reopen settled decisions, or manufacture ambiguity.
- Start with the obvious scoped approach, verify it proportionally, and stop when the acceptance criteria are satisfied.
- Do not add files, abstractions, agents, research, dependencies, or follow-up work unless the task genuinely requires them.
- Keep investigations time-bounded. If the first focused check identifies the cause, proceed without exploring unrelated alternatives.
- “Do not overthink” means be decisive and efficient, not careless: preserve scientific correctness, user data, rollback safety, and explicit constraints.
- For reviews and audits, lead with `accept`, `needs correction`, or `reject`, followed by only the evidence necessary to justify that verdict.
- If one narrow correction is needed, request that correction only; do not redesign the surrounding system.
- Optimize for completion and clarity. The right scoped approach should make most tasks feel easy and doable.

### Continue from the current state

- Treat the newest valid artifact or user correction as authoritative. A completed replacement supersedes an earlier blocked report.
- Do not keep solving a blocker after the user has supplied the missing result.
- Before proposing another prompt, research run, scout, or task, check whether its required output already exists in the conversation, attachments, or workspace.
- Read supplied attachments and pasted reports first. Do not ask the user to summarize material the agent can access.
- Distinguish missing information from unprocessed information. If the evidence exists but has not been integrated, integrate it.
- Continue from the last completed step. Do not restart the workflow, recreate settled artifacts, or repeat completed research.
- Interpret short corrections in context. For example, “06 is complete” means use the completed Scout 06 report; “DIY” means perform the current non-implementation work in the main Codex session.
- When the user answers a pending choice, act on that choice. Do not reopen the choice unless execution reveals a concrete conflict.
- If the user provides the requested research report, move to synthesis. Do not generate another research prompt for the same question.
- Separate orchestration and document synthesis from product implementation. Executor selection is required when code implementation begins, not for reading reports, integrating evidence, or writing task packets.
- Use the simplest valid workflow transition: blocked report → replacement report → synthesis → implementation packet. Do not insert extra approval or planning stages.
- Resolve apparent contradictions by checking dates, status labels, and replacement paths. Prefer a newer `COMPLETE` report over an older `BLOCKED` report for the same scout.
- Ask a clarifying question only when different answers would materially change the action. Do not ask questions whose answers are already implied by the conversation.
- Match the user’s requested granularity. If they ask what to do next, give the single next action before discussing later steps.
- Do not make the user operate another model or task when the user has authorized the current session to perform the work.
- Once the acceptance criteria are met, report the result and stop. Do not manufacture optional follow-up work.
