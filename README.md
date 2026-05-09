# mythic

next-generation cognitive memory runtime for engram.

mythic is the runtime layer above a memory store. engram remembers, retrieves,
consolidates, and verifies. mythic coordinates long-lived cognitive sessions,
planner state, memory activation, runtime events, and supervised execution loops
around that substrate.

## current status

This repo is at the first package scaffold:

- Python package: `mythic`
- CLI entrypoint: `mythic`
- local JSON runtime store for early session state
- event bus for structured cognition events
- planner state primitives
- memory activation adapter interface
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
```

Session state is stored locally under `.mythic/` by default.

## architecture direction

The first runtime surface is deliberately small:

```text
foundation model
  -> mythic runtime
      -> cognitive session
      -> planner state
      -> memory activation
      -> event stream
      -> runtime store
          -> engram / sqlite / postgres / filesystem
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

