# mythic

next-generation cognitive memory runtime for engram.

mythic is the runtime layer above a memory store. engram remembers, retrieves,
consolidates, and verifies. mythic coordinates long-lived cognitive sessions,
planner state, memory activation, runtime events, and supervised execution loops
around that substrate.

## current status

This repo is at the first runnable runtime layer:

- Python package: `mythic`
- CLI entrypoint: `mythic`
- SQLite runtime store for durable session and event state
- optional JSON runtime store for transparent local debugging
- event bus for structured cognition events with persisted event logs
- cognitive cycles that combine planner state, memory activation, and reflection
- planner-aware memory activation request model
- memory mesh graph for sessions, goals, tasks, cycles, activations, and manual links
- adaptive memory reinforcement from activation feedback and decay
- drift reports for planner, mesh, reinforcement, cycle, and stale workflow checks
- recoverable execution records with pause, resume, retry, checkpoint, and branch semantics
- reflective records for blocked/failed tasks and plugin failures
- resumable session snapshots
- supervised plugin runner with manifest-based capability discovery
- optional bridge that publishes cycle summaries and reflections into Engram
- optional Engram integration via `mythic[engram]`

## install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

To use Engram as the backing memory system:

```bash
pip install -e ".[engram]"
```

## quick start

```bash
mythic init
mythic session start "build a persistent cognition runtime for engram"
mythic session list
mythic session cycle "$SESSION_ID"
mythic session snapshot "$SESSION_ID"
mythic events list
```

Session and event state is stored in `.mythic/runtime.db` by default.

Use JSON files instead when you want easily inspected local state:

```bash
mythic init --backend json
mythic session start "inspectable runtime state" --backend json
```

Planner tasks are part of session state:

```bash
SESSION_ID=...
mythic task add "$SESSION_ID" "wire planner memory"
mythic task ready "$SESSION_ID"
```

Cycles can publish durable memory back into Engram:

```bash
mythic session cycle "$SESSION_ID" \
  --publish \
  --bridge engram \
  --bridge-engram-config /path/to/engram/config.yaml
```

Cycle summaries are written as episodic narrative memories. Reflections are
written as procedural memories with `metadata.kind = mythic_reflection`, because
Engram does not currently expose a separate reflective layer.

Activated memories can be reinforced or penalized after a cycle:

```bash
mythic reinforcement feedback "$SESSION_ID" "$MEMORY_ID" useful \
  --cycle-id "$CYCLE_ID" \
  --note "helped choose the next task"
mythic reinforcement list
mythic reinforcement feedback-list --memory-id "$MEMORY_ID"
mythic reinforcement decay --rate 0.05
```

Reinforcement state is stored locally in the runtime database. Future activations
for the same memory carry `metadata.reinforcement` and receive an adjusted
`planner_relevance`, so repeatedly useful memory becomes more likely to shape
planning while contradicted or stale memory is down-weighted.

The memory mesh links runtime objects into a traversable graph:

```bash
mythic mesh nodes --kind memory
mythic mesh edges --kind activated
mythic mesh traverse "$SESSION_ID" --kind session --depth 2
mythic mesh link mem_a mem_b supports \
  --source-kind memory \
  --target-kind memory \
  --confidence 0.8 \
  --planner-relevance 0.6
```

Sessions, planner tasks, cognitive cycles, activated memories, reflections,
reinforcement feedback, and plugin runs are linked automatically as the runtime
executes. Manual links let agents add causal, temporal, or project-specific
relationships that Engram can later use for multi-hop continuity.

Drift inspections check runtime consistency and persist reports:

```bash
mythic drift inspect --session-id "$SESSION_ID"
mythic drift inspect --stale-after-hours 24
mythic drift reports --scope "session:$SESSION_ID"
```

The first drift pass detects blocked or failed planner tasks, missing planner
dependencies, stale active sessions, dangling mesh edges, missing mesh nodes for
persisted runtime records, contradicted/stale reinforced memories, and cycles
that are no longer linked from their sessions.

Recoverable executions persist long-running work:

```bash
mythic execution start "$SESSION_ID" workflow "index project memory" \
  --payload '{"root":"/repo"}'
mythic execution checkpoint "$EXECUTION_ID" "parsed source files"
mythic execution status "$EXECUTION_ID" paused
mythic execution status "$EXECUTION_ID" running
mythic execution retry "$EXECUTION_ID"
mythic execution branch "$EXECUTION_ID" --goal "try alternate parser"
mythic execution list --session-id "$SESSION_ID"
```

Executions are linked into the memory mesh, appear in session snapshots, and are
included in drift checks when failed, paused, or stale.

Plugins are manifest-driven and run under basic supervision:

```bash
mythic plugin list ./plugins
mythic plugin run ./plugins/example --input "payload"
mythic plugin run-capability ./plugins transform:text --input "payload"
mythic events list
```

A plugin directory contains `mythic-plugin.json`:

```json
{
  "name": "uppercase",
  "runtime": "python",
  "entrypoint": ["python", "worker.py"],
  "capabilities": ["transform:text"],
  "timeout_seconds": 5
}
```

## architecture direction

The first runtime surface is deliberately small:

```text
foundation model
  -> mythic runtime
      -> cognitive session
      -> cognitive cycle
      -> planner state
      -> memory activation
      -> memory mesh
      -> plugin host
      -> reflection records
      -> drift reports
      -> recoverable executions
      -> event stream
      -> runtime store
          -> sqlite / json / engram
```

The long-term target is persistent cognition rather than passive recall:

- persistent sessions
- planner-addressable memory
- memory activation during execution
- memory mesh traversal
- adaptive reinforcement
- plugin-capable supervised runtimes
- recoverable execution orchestration
- realtime cognition streams
- drift and contradiction checks

## development

```bash
PYTHONPATH=src python3 -m pytest -q
PYTHONPATH=src python3 -m mythic --version
```
