"""Command-line interface for Mythic."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from mythic import __version__
from mythic.memory import EngramMemoryAdapter, NullMemoryAdapter
from mythic.planner import TaskStatus
from mythic.runtime import MythicRuntime
from mythic.store import make_runtime_store


def _runtime(args: argparse.Namespace) -> MythicRuntime:
    adapter = NullMemoryAdapter()
    if getattr(args, "engram", False):
        adapter = EngramMemoryAdapter(getattr(args, "engram_config", None))
    return MythicRuntime(
        store=make_runtime_store(args.store, backend=args.backend),
        memory_adapter=adapter,
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

    parser = argparse.ArgumentParser(prog="mythic", description="Persistent cognition runtime")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    parser.add_argument("--store", default=".mythic", help="Runtime store directory")
    parser.add_argument("--backend", choices=["sqlite", "json"], default="sqlite", help="Runtime store backend")

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

    p_checkpoint = session_sub.add_parser("checkpoint", parents=[store_parent], help="Checkpoint a session")
    p_checkpoint.add_argument("session_id")
    p_checkpoint.add_argument("note")

    p_show = session_sub.add_parser("show", parents=[store_parent], help="Show one session")
    p_show.add_argument("session_id")

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

    p_plugin = sub.add_parser("plugin", parents=[store_parent], help="Run supervised plugins")
    plugin_sub = p_plugin.add_subparsers(dest="plugin_command")
    p_plugin_run = plugin_sub.add_parser("run", parents=[store_parent], help="Run a plugin manifest or directory")
    p_plugin_run.add_argument("path")
    p_plugin_run.add_argument("--input", dest="input_text")
    p_plugin_run.add_argument("--timeout", type=float)
    p_plugin_run.add_argument("--session-id")

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

    if args.command == "session" and args.session_command == "checkpoint":
        session = runtime.resume_session(args.session_id)
        step = runtime.checkpoint(session, args.note)
        print(json.dumps(step.session.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "session" and args.session_command == "show":
        session = runtime.resume_session(args.session_id)
        print(json.dumps(session.to_dict(), indent=2, sort_keys=True))
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

    if args.command == "plugin" and args.plugin_command == "run":
        step = runtime.run_plugin(
            args.path,
            input_text=args.input_text,
            timeout_seconds=args.timeout,
            session_id=args.session_id,
        )
        print(json.dumps(step.result.to_dict(), indent=2, sort_keys=True))
        return 0

    parser.print_help()
    return 1
