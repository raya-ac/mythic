"""Command-line interface for Mythic."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from mythic import __version__
from mythic.memory import EngramMemoryAdapter, NullMemoryAdapter
from mythic.runtime import MythicRuntime
from mythic.store import JsonRuntimeStore


def _runtime(args: argparse.Namespace) -> MythicRuntime:
    adapter = NullMemoryAdapter()
    if getattr(args, "engram", False):
        adapter = EngramMemoryAdapter(getattr(args, "engram_config", None))
    return MythicRuntime(
        store=JsonRuntimeStore(args.store),
        memory_adapter=adapter,
    )


def main(argv: Sequence[str] | None = None) -> int:
    store_parent = argparse.ArgumentParser(add_help=False)
    store_parent.add_argument("--store", default=argparse.SUPPRESS, help="Runtime store directory")

    parser = argparse.ArgumentParser(prog="mythic", description="Persistent cognition runtime")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    parser.add_argument("--store", default=".mythic", help="Runtime store directory")

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

    session_sub.add_parser("list", parents=[store_parent], help="List sessions")

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

    if args.command == "session" and args.session_command == "list":
        print(json.dumps([session.to_dict() for session in runtime.list_sessions()], indent=2, sort_keys=True))
        return 0

    parser.print_help()
    return 1
