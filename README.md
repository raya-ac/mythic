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
- reflective records for blocked/failed tasks and plugin failures
- resumable session snapshots
- supervised plugin runner with manifest-based capability discovery
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
      -> plugin host
      -> reflection records
      -> event stream
      -> runtime store
          -> sqlite / json / engram
```

The long-term target is persistent cognition rather than passive recall:

- persistent sessions
- planner-addressable memory
- memory activation during execution
- adaptive reinforcement
- plugin-capable supervised runtimes
- realtime cognition streams
- drift and contradiction checks

## development

```bash
PYTHONPATH=src python3 -m pytest -q
PYTHONPATH=src python3 -m mythic --version
```
