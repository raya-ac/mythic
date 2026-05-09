import json
import sys

from mythic.memory import MemoryActivation
from mythic.cli import main
from mythic.plugins import PluginHost
from mythic.runtime import MythicRuntime
from mythic.store import JsonRuntimeStore, SQLiteRuntimeStore


class StaticMemoryAdapter:
    def activate(self, goal: str, *, top_k: int = 5):
        return [
            MemoryActivation(
                memory_id="mem_1",
                score=0.9,
                planner_relevance=0.8,
                layer="semantic",
                content_preview=f"memory for {goal}",
            )
        ][:top_k]


def test_session_start_persists_root_goal(tmp_path):
    runtime = MythicRuntime(store=SQLiteRuntimeStore(tmp_path))

    step = runtime.start_session("build mythic")

    loaded = runtime.resume_session(step.session.id)
    assert loaded.goal == "build mythic"
    assert len(loaded.planner.tasks) == 1


def test_memory_activation_emits_events_and_persists(tmp_path):
    runtime = MythicRuntime(
        store=JsonRuntimeStore(tmp_path),
        memory_adapter=StaticMemoryAdapter(),
    )
    session = runtime.start_session("continue cognition").session

    step = runtime.activate_memory(session)

    assert len(step.session.recent_memory_activations) == 1
    assert [event.type for event in step.events] == [
        "memory_activation",
        "memory_activation_complete",
    ]
    loaded = runtime.resume_session(session.id)
    assert loaded.recent_memory_activations[0].memory_id == "mem_1"


def test_checkpoint_round_trips(tmp_path):
    runtime = MythicRuntime(store=SQLiteRuntimeStore(tmp_path))
    session = runtime.start_session("ship package").session

    runtime.checkpoint(session, "first repo scaffold")

    loaded = runtime.resume_session(session.id)
    assert loaded.reasoning_history == ["[checkpoint] first repo scaffold"]


def test_cli_accepts_json_store_after_subcommands(tmp_path):
    store = tmp_path / "runtime"

    assert main(["init", "--store", str(store), "--backend", "json"]) == 0
    assert main(["session", "start", "cli store smoke", "--store", str(store), "--backend", "json"]) == 0

    sessions = JsonRuntimeStore(store).list_sessions()
    assert sessions[0].goal == "cli store smoke"


def test_sqlite_store_persists_events(tmp_path):
    runtime = MythicRuntime(store=SQLiteRuntimeStore(tmp_path))
    session = runtime.start_session("persist cognition events").session

    runtime.checkpoint(session, "event log survives restart")

    reloaded_runtime = MythicRuntime(store=SQLiteRuntimeStore(tmp_path))
    events = reloaded_runtime.list_events(session_id=session.id)
    assert [event.type for event in events] == [
        "session_started",
        "session_checkpoint",
    ]


def test_planner_tasks_round_trip(tmp_path):
    runtime = MythicRuntime(store=SQLiteRuntimeStore(tmp_path))
    session = runtime.start_session("plan runtime work").session

    step = runtime.add_task(session, "wire event persistence")

    loaded = runtime.resume_session(session.id)
    assert any(task.title == "wire event persistence" for task in loaded.planner.tasks.values())
    assert step.events[0].type == "planner_task_added"


def test_cli_default_sqlite_store_and_events(tmp_path, capsys):
    store = tmp_path / "runtime"

    assert main(["init", "--store", str(store)]) == 0
    capsys.readouterr()

    assert main(["session", "start", "cli sqlite smoke", "--store", str(store)]) == 0
    session = json.loads(capsys.readouterr().out)

    assert (store / "runtime.db").exists()
    assert main(["events", "list", "--store", str(store), "--session-id", session["id"]]) == 0
    events = json.loads(capsys.readouterr().out)
    assert events[0]["type"] == "session_started"


def write_echo_plugin(path):
    path.mkdir()
    (path / "worker.py").write_text(
        "import sys\nprint(sys.stdin.read().upper(), end='')\n",
        encoding="utf-8",
    )
    (path / "mythic-plugin.json").write_text(
        json.dumps(
            {
                "name": "uppercase",
                "runtime": "python",
                "entrypoint": [sys.executable, "worker.py"],
                "capabilities": ["transform:text"],
                "timeout_seconds": 5,
            }
        ),
        encoding="utf-8",
    )


def test_plugin_host_runs_manifest(tmp_path):
    plugin = tmp_path / "uppercase"
    write_echo_plugin(plugin)

    result = PluginHost().run(plugin, input_text="mythic")

    assert result.ok
    assert result.stdout == "MYTHIC"


def test_runtime_records_plugin_events(tmp_path):
    plugin = tmp_path / "uppercase"
    write_echo_plugin(plugin)
    runtime = MythicRuntime(store=SQLiteRuntimeStore(tmp_path / "runtime"))

    step = runtime.run_plugin(str(plugin), input_text="events")

    assert step.result.stdout == "EVENTS"
    assert [event.type for event in runtime.list_events()] == [
        "plugin_started",
        "plugin_completed",
    ]


def test_cli_plugin_run(tmp_path, capsys):
    plugin = tmp_path / "uppercase"
    write_echo_plugin(plugin)
    store = tmp_path / "runtime"

    assert main(["plugin", "run", str(plugin), "--input", "cli", "--store", str(store)]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["ok"]
    assert result["stdout"] == "CLI"
