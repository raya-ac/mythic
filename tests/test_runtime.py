import json
import sys

from mythic.bridge import BridgePublishResult, CycleMemoryFormatter
from mythic.memory import MemoryActivation
from mythic.cli import main
from mythic.mesh import MemoryMeshEdge, mesh_node_id
from mythic.planner import TaskStatus
from mythic.plugins import PluginHost
from mythic.runtime import MythicRuntime
from mythic.store import JsonRuntimeStore, SQLiteRuntimeStore


class StaticMemoryAdapter:
    def __init__(self):
        self.requests = []

    def activate(self, request, *, top_k: int = 5):
        self.requests.append(request)
        return [
            MemoryActivation(
                memory_id="mem_1",
                score=0.9,
                planner_relevance=0.8,
                layer="semantic",
                content_preview=f"memory for {request.goal}",
                metadata={"query": request.to_query()},
            )
        ][:top_k]


class RecordingBridge:
    backend = "recording"

    def __init__(self):
        self.cycles = []
        self.reflections = []

    def publish_cycle(self, cycle, snapshot=None):
        self.cycles.append((cycle, snapshot))
        return BridgePublishResult(backend=self.backend, memory_ids=[f"cycle:{cycle.id}"])

    def publish_reflection(self, reflection):
        self.reflections.append(reflection)
        return BridgePublishResult(backend=self.backend, memory_ids=[f"reflection:{reflection.id}"])


def test_session_start_persists_root_goal(tmp_path):
    runtime = MythicRuntime(store=SQLiteRuntimeStore(tmp_path))

    step = runtime.start_session("build mythic")

    loaded = runtime.resume_session(step.session.id)
    assert loaded.goal == "build mythic"
    assert len(loaded.planner.tasks) == 1


def test_memory_activation_emits_events_and_persists(tmp_path):
    adapter = StaticMemoryAdapter()
    runtime = MythicRuntime(
        store=JsonRuntimeStore(tmp_path),
        memory_adapter=adapter,
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
    assert adapter.requests[0].goal == "continue cognition"


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


def test_cognitive_cycle_uses_planner_context_and_persists(tmp_path):
    adapter = StaticMemoryAdapter()
    runtime = MythicRuntime(
        store=SQLiteRuntimeStore(tmp_path),
        memory_adapter=adapter,
    )
    session = runtime.start_session("build cognitive cycles").session
    runtime.add_task(session, "activate memory from ready task")
    blocked = runtime.add_task(session, "resolve missing context").session
    blocked_task_id = next(
        task.id
        for task in blocked.planner.tasks.values()
        if task.title == "resolve missing context"
    )
    runtime.set_task_status(blocked, blocked_task_id, TaskStatus.BLOCKED)

    step = runtime.run_cycle(blocked)

    request = adapter.requests[-1]
    assert "activate memory from ready task" in request.ready_tasks
    assert "resolve missing context" in request.blocked_tasks
    assert step.cycle.activations[0].memory_id == "mem_1"
    assert step.cycle.reflections[0].kind == "blocked_task"

    reloaded = MythicRuntime(store=SQLiteRuntimeStore(tmp_path))
    assert reloaded.list_cycles(session_id=session.id)[0].id == step.cycle.id
    assert reloaded.list_reflections(session_id=session.id)[0].kind == "blocked_task"


def test_session_snapshot_collects_runtime_state(tmp_path):
    runtime = MythicRuntime(
        store=SQLiteRuntimeStore(tmp_path),
        memory_adapter=StaticMemoryAdapter(),
    )
    session = runtime.start_session("snapshot state").session
    runtime.add_task(session, "next ready task")
    runtime.run_cycle(session)

    snapshot = runtime.session_snapshot(session)

    assert snapshot["session"]["id"] == session.id
    assert snapshot["planner"]["ready"][0]["title"] == "snapshot state"
    assert snapshot["recent_cycles"]
    assert snapshot["recent_events"]
    assert snapshot["suggested_next_actions"]


def test_cycle_publish_uses_memory_bridge(tmp_path):
    bridge = RecordingBridge()
    runtime = MythicRuntime(
        store=SQLiteRuntimeStore(tmp_path),
        memory_adapter=StaticMemoryAdapter(),
        memory_bridge=bridge,
    )
    session = runtime.start_session("publish cycle").session

    step = runtime.run_cycle(session, publish=True)

    assert step.bridge_result.memory_ids == [f"cycle:{step.cycle.id}"]
    assert bridge.cycles[0][0].id == step.cycle.id
    assert bridge.cycles[0][1]["session"]["id"] == session.id
    assert step.events[-1].type == "bridge_publish_completed"


def test_runtime_records_session_cycle_memory_mesh(tmp_path):
    runtime = MythicRuntime(
        store=SQLiteRuntimeStore(tmp_path),
        memory_adapter=StaticMemoryAdapter(),
    )
    session = runtime.start_session("mesh runtime state").session
    runtime.add_task(session, "connect activated memory")
    cycle = runtime.run_cycle(session).cycle

    node_ids = {node.id for node in runtime.list_mesh_nodes(limit=0)}
    edge_kinds = {edge.kind for edge in runtime.list_mesh_edges(limit=0)}
    traversal = runtime.traverse_mesh(session.id, kind="session", depth=2, limit=20)
    traversal_node_ids = {node.id for node in traversal.nodes}

    assert mesh_node_id("session", session.id) in node_ids
    assert mesh_node_id("cycle", cycle.id) in node_ids
    assert mesh_node_id("memory", "mem_1") in node_ids
    assert "ran_cycle" in edge_kinds
    assert "activated" in edge_kinds
    assert mesh_node_id("memory", "mem_1") in traversal_node_ids
    assert traversal.edges


def test_mesh_link_merges_repeated_edges(tmp_path):
    runtime = MythicRuntime(store=SQLiteRuntimeStore(tmp_path))

    first = runtime.link_mesh(
        source_kind="memory",
        source_identifier="mem_a",
        target_kind="memory",
        target_identifier="mem_b",
        kind="supports",
        confidence=0.4,
    )
    second = runtime.link_mesh(
        source_kind="memory",
        source_identifier="mem_a",
        target_kind="memory",
        target_identifier="mem_b",
        kind="supports",
        confidence=0.9,
        planner_relevance=0.7,
    )

    assert first.edge.id == second.edge.id
    assert second.edge.activation_count == 2
    assert second.edge.confidence == 0.9
    assert second.edge.planner_relevance == 0.7


def test_json_store_persists_mesh(tmp_path):
    runtime = MythicRuntime(store=JsonRuntimeStore(tmp_path))
    runtime.link_mesh(
        source_kind="memory",
        source_identifier="mem_a",
        target_kind="task",
        target_identifier="task_a",
        kind="informs",
    )

    reloaded = MythicRuntime(store=JsonRuntimeStore(tmp_path))
    traversal = reloaded.traverse_mesh("mem_a", kind="memory")

    assert reloaded.list_mesh_edges()[0].kind == "informs"
    assert mesh_node_id("task", "task_a") in {node.id for node in traversal.nodes}


def test_cli_mesh_commands(tmp_path, capsys):
    store = tmp_path / "runtime"

    assert main([
        "mesh",
        "link",
        "mem_a",
        "mem_b",
        "supports",
        "--store",
        str(store),
        "--confidence",
        "0.8",
        "--planner-relevance",
        "0.6",
        "--metadata",
        "{\"reason\":\"manual\"}",
    ]) == 0
    link = json.loads(capsys.readouterr().out)
    assert link["edge"]["kind"] == "supports"
    assert link["edge"]["metadata"]["reason"] == "manual"

    assert main(["mesh", "nodes", "--store", str(store), "--kind", "memory"]) == 0
    nodes = json.loads(capsys.readouterr().out)
    assert {node["id"] for node in nodes} == {"memory:mem_a", "memory:mem_b"}

    assert main(["mesh", "edges", "--store", str(store), "--source-id", "memory:mem_a"]) == 0
    edges = json.loads(capsys.readouterr().out)
    assert edges[0]["target_id"] == "memory:mem_b"

    assert main(["mesh", "traverse", "mem_a", "--kind", "memory", "--store", str(store)]) == 0
    traversal = json.loads(capsys.readouterr().out)
    assert traversal["root_id"] == "memory:mem_a"
    assert "memory:mem_b" in {node["id"] for node in traversal["nodes"]}


def test_feedback_reinforces_future_activation(tmp_path):
    runtime = MythicRuntime(
        store=SQLiteRuntimeStore(tmp_path),
        memory_adapter=StaticMemoryAdapter(),
    )
    session = runtime.start_session("reinforce memory").session
    first_cycle = runtime.run_cycle(session)

    feedback_step = runtime.record_feedback(
        session_id=session.id,
        cycle_id=first_cycle.cycle.id,
        memory_id="mem_1",
        outcome="useful",
        note="helped choose the next task",
    )
    second_cycle = runtime.run_cycle(session)
    activation = second_cycle.cycle.activations[0]

    assert round(feedback_step.state.score, 3) == 0.15
    assert feedback_step.event.type == "memory_reinforced"
    assert activation.metadata["reinforcement"]["score"] == feedback_step.state.score
    assert activation.metadata["base_planner_relevance"] == 0.8
    assert round(activation.planner_relevance, 3) == 0.95


def test_feedback_persists_and_negative_outcomes_reduce_relevance(tmp_path):
    runtime = MythicRuntime(
        store=SQLiteRuntimeStore(tmp_path),
        memory_adapter=StaticMemoryAdapter(),
    )
    session = runtime.start_session("penalize stale memory").session

    runtime.record_feedback(
        session_id=session.id,
        memory_id="mem_1",
        outcome="contradicted",
        note="project state had drifted",
    )

    reloaded = MythicRuntime(
        store=SQLiteRuntimeStore(tmp_path),
        memory_adapter=StaticMemoryAdapter(),
    )
    state = reloaded.list_reinforcements()[0]
    feedback = reloaded.list_feedback(memory_id="mem_1")[0]
    cycle = reloaded.run_cycle(reloaded.resume_session(session.id))

    assert state.memory_id == "mem_1"
    assert round(state.score, 3) == -0.25
    assert state.failures == 1
    assert state.contradictions == 1
    assert feedback.outcome.value == "contradicted"
    assert round(cycle.cycle.activations[0].planner_relevance, 3) == 0.55


def test_decay_reinforcements_moves_scores_toward_zero(tmp_path):
    runtime = MythicRuntime(store=SQLiteRuntimeStore(tmp_path))
    session = runtime.start_session("decay reinforcement").session
    runtime.record_feedback(
        session_id=session.id,
        memory_id="mem_1",
        outcome="useful",
    )

    step = runtime.decay_reinforcements(rate=0.5)

    assert step.event.type == "reinforcement_decay_completed"
    assert round(step.states[0].score, 3) == 0.075
    assert runtime.list_reinforcements()[0].decayed_at is not None


def test_json_store_persists_reinforcement_feedback(tmp_path):
    runtime = MythicRuntime(store=JsonRuntimeStore(tmp_path))
    session = runtime.start_session("json reinforcement").session

    runtime.record_feedback(
        session_id=session.id,
        memory_id="mem_1",
        outcome="stale",
        note="old note",
    )

    reloaded = MythicRuntime(store=JsonRuntimeStore(tmp_path))
    state = reloaded.list_reinforcements()[0]
    feedback = reloaded.list_feedback(session_id=session.id)[0]

    assert state.stale == 1
    assert round(state.score, 3) == -0.12
    assert feedback.note == "old note"


def test_cli_reinforcement_commands(tmp_path, capsys):
    store = tmp_path / "runtime"

    assert main(["session", "start", "cli reinforcement smoke", "--store", str(store)]) == 0
    session = json.loads(capsys.readouterr().out)

    assert main([
        "reinforcement",
        "feedback",
        session["id"],
        "mem_1",
        "useful",
        "--store",
        str(store),
        "--note",
        "cli signal",
    ]) == 0
    feedback_result = json.loads(capsys.readouterr().out)
    assert feedback_result["reinforcement"]["successes"] == 1

    assert main(["reinforcement", "list", "--store", str(store)]) == 0
    states = json.loads(capsys.readouterr().out)
    assert states[0]["memory_id"] == "mem_1"

    assert main(["reinforcement", "feedback-list", "--store", str(store), "--memory-id", "mem_1"]) == 0
    feedback = json.loads(capsys.readouterr().out)
    assert feedback[0]["note"] == "cli signal"

    assert main(["reinforcement", "decay", "--store", str(store), "--rate", "0.5"]) == 0
    decay = json.loads(capsys.readouterr().out)
    assert decay["count"] == 1


def test_drift_inspection_detects_planner_mesh_and_reinforcement_issues(tmp_path):
    runtime = MythicRuntime(store=SQLiteRuntimeStore(tmp_path))
    session = runtime.start_session("detect drift").session
    task_step = runtime.add_task(session, "blocked on missing dependency", depends_on=["missing-task"])
    task_id = next(
        task.id
        for task in task_step.session.planner.tasks.values()
        if task.title == "blocked on missing dependency"
    )
    runtime.set_task_status(task_step.session, task_id, TaskStatus.BLOCKED)
    runtime.record_feedback(
        session_id=session.id,
        memory_id="mem_drift",
        outcome="contradicted",
        note="the memory disagreed with current state",
    )
    runtime.store.save_mesh_edge(
        MemoryMeshEdge(
            source_id="memory:missing-source",
            target_id="memory:missing-target",
            kind="claims",
        )
    )

    step = runtime.inspect_drift(session_id=session.id)
    issue_kinds = {issue.kind for issue in step.report.issues}

    assert step.event.type == "drift_inspection_completed"
    assert step.report.scope == f"session:{session.id}"
    assert step.report.score < 100
    assert "planner_missing_dependency" in issue_kinds
    assert "blocked_task" in issue_kinds
    assert "contradicted_memory" in issue_kinds
    assert "mesh_dangling_source" in issue_kinds
    assert "mesh_dangling_target" in issue_kinds
    assert runtime.list_drift_reports(scope=f"session:{session.id}")[0].id == step.report.id


def test_drift_report_persists_in_json_store(tmp_path):
    runtime = MythicRuntime(store=JsonRuntimeStore(tmp_path))
    session = runtime.start_session("json drift").session
    old_updated_at = session.updated_at
    session.updated_at = old_updated_at - (8 * 24 * 60 * 60)
    runtime.store.save_session(session)

    report = runtime.inspect_drift(
        session_id=session.id,
        stale_after_seconds=7 * 24 * 60 * 60,
    ).report
    reloaded = MythicRuntime(store=JsonRuntimeStore(tmp_path))
    reports = reloaded.list_drift_reports(scope=f"session:{session.id}")

    assert reports[0].id == report.id
    assert any(issue.kind == "stale_session" for issue in reports[0].issues)


def test_drift_no_save_does_not_persist_report(tmp_path):
    runtime = MythicRuntime(store=SQLiteRuntimeStore(tmp_path))

    step = runtime.inspect_drift(persist=False)

    assert step.report.scope == "runtime"
    assert runtime.list_drift_reports() == []


def test_cli_drift_commands(tmp_path, capsys):
    store = tmp_path / "runtime"

    assert main(["session", "start", "cli drift smoke", "--store", str(store)]) == 0
    session = json.loads(capsys.readouterr().out)

    assert main([
        "reinforcement",
        "feedback",
        session["id"],
        "mem_1",
        "stale",
        "--store",
        str(store),
    ]) == 0
    capsys.readouterr()

    assert main(["drift", "inspect", "--store", str(store), "--session-id", session["id"]]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["report"]["scope"] == f"session:{session['id']}"
    assert any(issue["kind"] == "stale_memory" for issue in result["report"]["issues"])

    assert main([
        "drift",
        "reports",
        "--store",
        str(store),
        "--scope",
        f"session:{session['id']}",
    ]) == 0
    reports = json.loads(capsys.readouterr().out)
    assert reports[0]["id"] == result["report"]["id"]


def test_cycle_memory_formatter_maps_reflections_to_procedural_memory(tmp_path):
    runtime = MythicRuntime(store=SQLiteRuntimeStore(tmp_path))
    session = runtime.start_session("format bridge memory").session
    step = runtime.add_task(session, "blocked task")
    task_id = next(task.id for task in step.session.planner.tasks.values() if task.title == "blocked task")
    runtime.set_task_status(step.session, task_id, TaskStatus.BLOCKED)
    cycle = runtime.run_cycle(step.session).cycle

    formatter = CycleMemoryFormatter()
    cycle_memory = formatter.cycle_memory(cycle, snapshot=runtime.session_snapshot(step.session))
    reflection_memory = formatter.reflection_memory(cycle.reflections[0])

    assert cycle_memory.layer == "episodic"
    assert cycle_memory.memory_type == "narrative"
    assert reflection_memory.layer == "procedural"
    assert reflection_memory.memory_type == "procedure"
    assert reflection_memory.metadata["kind"] == "mythic_reflection"


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


def test_cli_cycle_and_snapshot(tmp_path, capsys):
    store = tmp_path / "runtime"

    assert main(["session", "start", "cli cycle smoke", "--store", str(store)]) == 0
    session = json.loads(capsys.readouterr().out)

    assert main(["session", "cycle", session["id"], "--store", str(store)]) == 0
    cycle = json.loads(capsys.readouterr().out)
    assert cycle["activation_request"]["goal"] == "cli cycle smoke"

    assert main(["session", "snapshot", session["id"], "--store", str(store)]) == 0
    snapshot = json.loads(capsys.readouterr().out)
    assert snapshot["recent_cycles"][0]["id"] == cycle["id"]


def write_echo_plugin(path):
    path.mkdir(parents=True)
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


def write_failing_plugin(path):
    path.mkdir(parents=True)
    (path / "worker.py").write_text(
        "import sys\nprint('bad', file=sys.stderr)\nsys.exit(2)\n",
        encoding="utf-8",
    )
    (path / "mythic-plugin.json").write_text(
        json.dumps(
            {
                "name": "failing",
                "runtime": "python",
                "entrypoint": [sys.executable, "worker.py"],
                "capabilities": ["debug:fail"],
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


def test_plugin_host_discovers_by_capability(tmp_path):
    plugin = tmp_path / "plugins" / "uppercase"
    write_echo_plugin(plugin)

    host = PluginHost()
    discovered = host.discover(tmp_path / "plugins")
    result = host.run_capability(tmp_path / "plugins", "transform:text", input_text="mesh")

    assert discovered[0].manifest.name == "uppercase"
    assert result.stdout == "MESH"


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


def test_cli_plugin_run_capability(tmp_path, capsys):
    plugin = tmp_path / "plugins" / "uppercase"
    write_echo_plugin(plugin)
    store = tmp_path / "runtime"

    assert main(["plugin", "list", str(tmp_path / "plugins"), "--store", str(store)]) == 0
    plugins = json.loads(capsys.readouterr().out)
    assert plugins[0]["manifest"]["capabilities"] == ["transform:text"]

    assert main([
        "plugin",
        "run-capability",
        str(tmp_path / "plugins"),
        "transform:text",
        "--input",
        "cap",
        "--store",
        str(store),
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["stdout"] == "CAP"


def test_plugin_failure_records_reflection(tmp_path):
    plugin = tmp_path / "failing"
    write_failing_plugin(plugin)
    runtime = MythicRuntime(store=SQLiteRuntimeStore(tmp_path / "runtime"))
    session = runtime.start_session("plugin reflection").session

    step = runtime.run_plugin(str(plugin), input_text="bad", session_id=session.id)

    assert not step.result.ok
    reflections = runtime.list_reflections(session_id=session.id)
    assert reflections[0].kind == "plugin_failure"


def test_plugin_failure_publishes_reflection_when_bridge_configured(tmp_path):
    plugin = tmp_path / "failing"
    write_failing_plugin(plugin)
    bridge = RecordingBridge()
    runtime = MythicRuntime(
        store=SQLiteRuntimeStore(tmp_path / "runtime"),
        memory_bridge=bridge,
    )
    session = runtime.start_session("plugin bridge reflection").session

    step = runtime.run_plugin(str(plugin), input_text="bad", session_id=session.id)

    assert not step.result.ok
    assert bridge.reflections[0].kind == "plugin_failure"
    assert step.events[-1].type == "bridge_publish_completed"
