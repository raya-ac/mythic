"""Command-line interface for Mythic."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from mythic import __version__
from mythic.bridge import EngramMemoryBridge, NullMemoryBridge
from mythic.memory import EngramMemoryAdapter, NullMemoryAdapter
from mythic.planner import TaskStatus
from mythic.reinforcement import ActivationOutcome
from mythic.runtime import MythicRuntime
from mythic.store import make_runtime_store


def _json_object(value: str | None) -> dict | None:
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("metadata must be a JSON object")
    return parsed


def _runtime(args: argparse.Namespace) -> MythicRuntime:
    adapter = NullMemoryAdapter()
    if getattr(args, "engram", False):
        adapter = EngramMemoryAdapter(getattr(args, "engram_config", None))
    bridge = NullMemoryBridge()
    if getattr(args, "bridge", "none") == "engram":
        bridge = EngramMemoryBridge(getattr(args, "bridge_engram_config", None))
    return MythicRuntime(
        store=make_runtime_store(args.store, backend=args.backend),
        memory_adapter=adapter,
        memory_bridge=bridge,
    )


def main(argv: Sequence[str] | None = None) -> int:
    store_parent = argparse.ArgumentParser(add_help=False)
    store_parent.add_argument("--store", default=argparse.SUPPRESS, help="Runtime store directory")
    store_parent.add_argument(
        "--backend",
        choices=["sqlite", "json"],
        default=argparse.SUPPRESS,
        help="Runtime store backend",
    )
    store_parent.add_argument(
        "--bridge",
        choices=["none", "engram"],
        default=argparse.SUPPRESS,
        help="External memory bridge for published runtime records",
    )
    store_parent.add_argument(
        "--bridge-engram-config",
        default=argparse.SUPPRESS,
        help="Engram config path for --bridge engram",
    )

    parser = argparse.ArgumentParser(prog="mythic", description="Persistent cognition runtime")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    parser.add_argument("--store", default=".mythic", help="Runtime store directory")
    parser.add_argument("--backend", choices=["sqlite", "json"], default="sqlite", help="Runtime store backend")
    parser.add_argument("--bridge", choices=["none", "engram"], default="none", help="External memory bridge")
    parser.add_argument("--bridge-engram-config", help="Engram config path for --bridge engram")

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init", parents=[store_parent], help="Initialize local runtime state")

    p_session = sub.add_parser("session", parents=[store_parent], help="Manage cognitive sessions")
    session_sub = p_session.add_subparsers(dest="session_command")

    p_start = session_sub.add_parser("start", parents=[store_parent], help="Start a cognitive session")
    p_start.add_argument("goal")
    p_start.add_argument("--activate", action="store_true", help="Run memory activation after session creation")
    p_start.add_argument("--engram", action="store_true", help="Use Engram for memory activation")
    p_start.add_argument("--engram-config", help="Path to Engram config.yaml")

    p_activate = session_sub.add_parser("activate", parents=[store_parent], help="Activate memories for a session")
    p_activate.add_argument("session_id")
    p_activate.add_argument("-k", "--top-k", type=int, default=5)
    p_activate.add_argument("--engram", action="store_true", help="Use Engram for memory activation")
    p_activate.add_argument("--engram-config", help="Path to Engram config.yaml")

    p_cycle = session_sub.add_parser("cycle", parents=[store_parent], help="Run one cognitive cycle")
    p_cycle.add_argument("session_id")
    p_cycle.add_argument("-k", "--top-k", type=int, default=5)
    p_cycle.add_argument("--engram", action="store_true", help="Use Engram for memory activation")
    p_cycle.add_argument("--engram-config", help="Path to Engram config.yaml")
    p_cycle.add_argument("--publish", action="store_true", help="Publish cycle summary through the configured bridge")

    p_checkpoint = session_sub.add_parser("checkpoint", parents=[store_parent], help="Checkpoint a session")
    p_checkpoint.add_argument("session_id")
    p_checkpoint.add_argument("note")

    p_show = session_sub.add_parser("show", parents=[store_parent], help="Show one session")
    p_show.add_argument("session_id")

    p_snapshot = session_sub.add_parser("snapshot", parents=[store_parent], help="Show a resumable session snapshot")
    p_snapshot.add_argument("session_id")
    p_snapshot.add_argument("--limit", type=int, default=10)

    session_sub.add_parser("list", parents=[store_parent], help="List sessions")

    p_task = sub.add_parser("task", parents=[store_parent], help="Manage planner tasks")
    task_sub = p_task.add_subparsers(dest="task_command")

    p_task_add = task_sub.add_parser("add", parents=[store_parent], help="Add a planner task")
    p_task_add.add_argument("session_id")
    p_task_add.add_argument("title")
    p_task_add.add_argument("--depends-on", action="append", default=[], help="Dependency task id")

    p_task_ready = task_sub.add_parser("ready", parents=[store_parent], help="List ready tasks")
    p_task_ready.add_argument("session_id")

    p_task_status = task_sub.add_parser("status", parents=[store_parent], help="Set task status")
    p_task_status.add_argument("session_id")
    p_task_status.add_argument("task_id")
    p_task_status.add_argument("status", choices=[status.value for status in TaskStatus])

    p_events = sub.add_parser("events", parents=[store_parent], help="Inspect cognition events")
    events_sub = p_events.add_subparsers(dest="events_command")
    p_events_list = events_sub.add_parser("list", parents=[store_parent], help="List recent events")
    p_events_list.add_argument("--session-id")
    p_events_list.add_argument("--limit", type=int, default=50)

    p_cycles = sub.add_parser("cycles", parents=[store_parent], help="Inspect cognitive cycles")
    cycles_sub = p_cycles.add_subparsers(dest="cycles_command")
    p_cycles_list = cycles_sub.add_parser("list", parents=[store_parent], help="List recent cognitive cycles")
    p_cycles_list.add_argument("--session-id")
    p_cycles_list.add_argument("--limit", type=int, default=20)

    p_reflections = sub.add_parser("reflections", parents=[store_parent], help="Inspect reflective records")
    reflections_sub = p_reflections.add_subparsers(dest="reflections_command")
    p_reflections_list = reflections_sub.add_parser("list", parents=[store_parent], help="List recent reflections")
    p_reflections_list.add_argument("--session-id")
    p_reflections_list.add_argument("--limit", type=int, default=20)

    p_reinforcement = sub.add_parser("reinforcement", parents=[store_parent], help="Inspect and update memory reinforcement")
    reinforcement_sub = p_reinforcement.add_subparsers(dest="reinforcement_command")

    p_reinforce_feedback = reinforcement_sub.add_parser("feedback", parents=[store_parent], help="Record feedback for an activated memory")
    p_reinforce_feedback.add_argument("session_id")
    p_reinforce_feedback.add_argument("memory_id")
    p_reinforce_feedback.add_argument("outcome", choices=[outcome.value for outcome in ActivationOutcome])
    p_reinforce_feedback.add_argument("--cycle-id")
    p_reinforce_feedback.add_argument("--note")
    p_reinforce_feedback.add_argument("--source", default="human")
    p_reinforce_feedback.add_argument("--signal", type=float)

    p_reinforce_feedback_list = reinforcement_sub.add_parser("feedback-list", parents=[store_parent], help="List activation feedback")
    p_reinforce_feedback_list.add_argument("--session-id")
    p_reinforce_feedback_list.add_argument("--memory-id")
    p_reinforce_feedback_list.add_argument("--limit", type=int, default=50)

    p_reinforce_list = reinforcement_sub.add_parser("list", parents=[store_parent], help="List reinforcement states")
    p_reinforce_list.add_argument("--limit", type=int, default=50)

    p_reinforce_decay = reinforcement_sub.add_parser("decay", parents=[store_parent], help="Decay reinforcement scores toward zero")
    p_reinforce_decay.add_argument("--rate", type=float, default=0.05)

    p_mesh = sub.add_parser("mesh", parents=[store_parent], help="Inspect and link the memory mesh")
    mesh_sub = p_mesh.add_subparsers(dest="mesh_command")

    p_mesh_link = mesh_sub.add_parser("link", parents=[store_parent], help="Create or reinforce a mesh edge")
    p_mesh_link.add_argument("source")
    p_mesh_link.add_argument("target")
    p_mesh_link.add_argument("kind")
    p_mesh_link.add_argument("--source-kind", default="memory")
    p_mesh_link.add_argument("--target-kind", default="memory")
    p_mesh_link.add_argument("--source-label")
    p_mesh_link.add_argument("--target-label")
    p_mesh_link.add_argument("--confidence", type=float, default=1.0)
    p_mesh_link.add_argument("--planner-relevance", type=float, default=0.0)
    p_mesh_link.add_argument("--emotional-weight", type=float, default=0.0)
    p_mesh_link.add_argument("--metadata", type=_json_object)

    p_mesh_nodes = mesh_sub.add_parser("nodes", parents=[store_parent], help="List mesh nodes")
    p_mesh_nodes.add_argument("--kind")
    p_mesh_nodes.add_argument("--limit", type=int, default=50)

    p_mesh_edges = mesh_sub.add_parser("edges", parents=[store_parent], help="List mesh edges")
    p_mesh_edges.add_argument("--source-id")
    p_mesh_edges.add_argument("--target-id")
    p_mesh_edges.add_argument("--kind")
    p_mesh_edges.add_argument("--limit", type=int, default=50)

    p_mesh_traverse = mesh_sub.add_parser("traverse", parents=[store_parent], help="Traverse the mesh from one node")
    p_mesh_traverse.add_argument("root")
    p_mesh_traverse.add_argument("--kind")
    p_mesh_traverse.add_argument("--depth", type=int, default=2)
    p_mesh_traverse.add_argument("--limit", type=int, default=50)

    p_drift = sub.add_parser("drift", parents=[store_parent], help="Inspect runtime drift")
    drift_sub = p_drift.add_subparsers(dest="drift_command")

    p_drift_inspect = drift_sub.add_parser("inspect", parents=[store_parent], help="Run a drift inspection")
    p_drift_inspect.add_argument("--session-id")
    p_drift_inspect.add_argument("--stale-after-hours", type=float, default=24 * 7)
    p_drift_inspect.add_argument("--no-save", action="store_true", help="Do not persist the drift report")

    p_drift_reports = drift_sub.add_parser("reports", parents=[store_parent], help="List persisted drift reports")
    p_drift_reports.add_argument("--scope")
    p_drift_reports.add_argument("--limit", type=int, default=20)

    p_plugin = sub.add_parser("plugin", parents=[store_parent], help="Run supervised plugins")
    plugin_sub = p_plugin.add_subparsers(dest="plugin_command")
    p_plugin_list = plugin_sub.add_parser("list", parents=[store_parent], help="Discover plugins under a root")
    p_plugin_list.add_argument("root")

    p_plugin_run = plugin_sub.add_parser("run", parents=[store_parent], help="Run a plugin manifest or directory")
    p_plugin_run.add_argument("path")
    p_plugin_run.add_argument("--input", dest="input_text")
    p_plugin_run.add_argument("--timeout", type=float)
    p_plugin_run.add_argument("--session-id")

    p_plugin_cap = plugin_sub.add_parser("run-capability", parents=[store_parent], help="Run the first plugin matching a capability")
    p_plugin_cap.add_argument("root")
    p_plugin_cap.add_argument("capability")
    p_plugin_cap.add_argument("--input", dest="input_text")
    p_plugin_cap.add_argument("--timeout", type=float)
    p_plugin_cap.add_argument("--session-id")

    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    runtime = _runtime(args)

    if args.command == "init":
        runtime.init()
        print(json.dumps({"status": "initialized", "store": args.store}))
        return 0

    if args.command == "session" and args.session_command == "start":
        step = runtime.start_session(args.goal)
        if args.activate:
            step = runtime.activate_memory(step.session)
        print(json.dumps(step.session.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "session" and args.session_command == "activate":
        session = runtime.resume_session(args.session_id)
        step = runtime.activate_memory(session, top_k=args.top_k)
        print(json.dumps([event.to_dict() for event in step.events], indent=2, sort_keys=True))
        return 0

    if args.command == "session" and args.session_command == "cycle":
        session = runtime.resume_session(args.session_id)
        step = runtime.run_cycle(session, top_k=args.top_k, publish=args.publish)
        payload = step.cycle.to_dict()
        if step.bridge_result is not None:
            payload["bridge_result"] = step.bridge_result.to_dict()
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.command == "session" and args.session_command == "checkpoint":
        session = runtime.resume_session(args.session_id)
        step = runtime.checkpoint(session, args.note)
        print(json.dumps(step.session.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "session" and args.session_command == "show":
        session = runtime.resume_session(args.session_id)
        print(json.dumps(session.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "session" and args.session_command == "snapshot":
        session = runtime.resume_session(args.session_id)
        print(json.dumps(runtime.session_snapshot(session, limit=args.limit), indent=2, sort_keys=True))
        return 0

    if args.command == "session" and args.session_command == "list":
        print(json.dumps([session.to_dict() for session in runtime.list_sessions()], indent=2, sort_keys=True))
        return 0

    if args.command == "task" and args.task_command == "add":
        session = runtime.resume_session(args.session_id)
        step = runtime.add_task(session, args.title, depends_on=args.depends_on)
        print(json.dumps(step.session.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "task" and args.task_command == "ready":
        session = runtime.resume_session(args.session_id)
        print(json.dumps([task.to_dict() for task in runtime.ready_tasks(session)], indent=2, sort_keys=True))
        return 0

    if args.command == "task" and args.task_command == "status":
        session = runtime.resume_session(args.session_id)
        step = runtime.set_task_status(session, args.task_id, TaskStatus(args.status))
        print(json.dumps(step.session.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "events" and args.events_command == "list":
        events = runtime.list_events(limit=args.limit, session_id=args.session_id)
        print(json.dumps([event.to_dict() for event in events], indent=2, sort_keys=True))
        return 0

    if args.command == "cycles" and args.cycles_command == "list":
        cycles = runtime.list_cycles(limit=args.limit, session_id=args.session_id)
        print(json.dumps([cycle.to_dict() for cycle in cycles], indent=2, sort_keys=True))
        return 0

    if args.command == "reflections" and args.reflections_command == "list":
        reflections = runtime.list_reflections(limit=args.limit, session_id=args.session_id)
        print(json.dumps([reflection.to_dict() for reflection in reflections], indent=2, sort_keys=True))
        return 0

    if args.command == "reinforcement" and args.reinforcement_command == "feedback":
        step = runtime.record_feedback(
            session_id=args.session_id,
            memory_id=args.memory_id,
            outcome=args.outcome,
            cycle_id=args.cycle_id,
            note=args.note,
            source=args.source,
            signal=args.signal,
        )
        print(
            json.dumps(
                {
                    "feedback": step.feedback.to_dict(),
                    "reinforcement": step.state.to_dict(),
                    "event": step.event.to_dict(),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "reinforcement" and args.reinforcement_command == "feedback-list":
        feedback = runtime.list_feedback(
            limit=args.limit,
            memory_id=args.memory_id,
            session_id=args.session_id,
        )
        print(json.dumps([item.to_dict() for item in feedback], indent=2, sort_keys=True))
        return 0

    if args.command == "reinforcement" and args.reinforcement_command == "list":
        states = runtime.list_reinforcements(limit=args.limit)
        print(json.dumps([state.to_dict() for state in states], indent=2, sort_keys=True))
        return 0

    if args.command == "reinforcement" and args.reinforcement_command == "decay":
        step = runtime.decay_reinforcements(rate=args.rate)
        print(
            json.dumps(
                {
                    "count": len(step.states),
                    "states": [state.to_dict() for state in step.states],
                    "event": step.event.to_dict(),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "mesh" and args.mesh_command == "link":
        step = runtime.link_mesh(
            source_kind=args.source_kind,
            source_identifier=args.source,
            target_kind=args.target_kind,
            target_identifier=args.target,
            kind=args.kind,
            source_label=args.source_label,
            target_label=args.target_label,
            confidence=args.confidence,
            planner_relevance=args.planner_relevance,
            emotional_weight=args.emotional_weight,
            metadata=args.metadata,
        )
        print(
            json.dumps(
                {
                    "source": step.source.to_dict(),
                    "target": step.target.to_dict(),
                    "edge": step.edge.to_dict(),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "mesh" and args.mesh_command == "nodes":
        nodes = runtime.list_mesh_nodes(limit=args.limit, kind=args.kind)
        print(json.dumps([node.to_dict() for node in nodes], indent=2, sort_keys=True))
        return 0

    if args.command == "mesh" and args.mesh_command == "edges":
        edges = runtime.list_mesh_edges(
            limit=args.limit,
            source_id=args.source_id,
            target_id=args.target_id,
            kind=args.kind,
        )
        print(json.dumps([edge.to_dict() for edge in edges], indent=2, sort_keys=True))
        return 0

    if args.command == "mesh" and args.mesh_command == "traverse":
        traversal = runtime.traverse_mesh(
            args.root,
            kind=args.kind,
            depth=args.depth,
            limit=args.limit,
        )
        print(json.dumps(traversal.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "drift" and args.drift_command == "inspect":
        step = runtime.inspect_drift(
            session_id=args.session_id,
            stale_after_seconds=args.stale_after_hours * 60 * 60,
            persist=not args.no_save,
        )
        print(
            json.dumps(
                {
                    "report": step.report.to_dict(),
                    "event": step.event.to_dict(),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "drift" and args.drift_command == "reports":
        reports = runtime.list_drift_reports(limit=args.limit, scope=args.scope)
        print(json.dumps([report.to_dict() for report in reports], indent=2, sort_keys=True))
        return 0

    if args.command == "plugin" and args.plugin_command == "run":
        step = runtime.run_plugin(
            args.path,
            input_text=args.input_text,
            timeout_seconds=args.timeout,
            session_id=args.session_id,
        )
        print(json.dumps(step.result.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "plugin" and args.plugin_command == "list":
        print(json.dumps(runtime.discover_plugins(args.root), indent=2, sort_keys=True))
        return 0

    if args.command == "plugin" and args.plugin_command == "run-capability":
        step = runtime.run_capability(
            args.root,
            args.capability,
            input_text=args.input_text,
            timeout_seconds=args.timeout,
            session_id=args.session_id,
        )
        print(json.dumps(step.result.to_dict(), indent=2, sort_keys=True))
        return 0

    parser.print_help()
    return 1
