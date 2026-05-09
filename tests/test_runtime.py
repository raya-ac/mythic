from mythic.memory import MemoryActivation
from mythic.cli import main
from mythic.runtime import MythicRuntime
from mythic.store import JsonRuntimeStore


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
    runtime = MythicRuntime(store=JsonRuntimeStore(tmp_path))

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
    runtime = MythicRuntime(store=JsonRuntimeStore(tmp_path))
    session = runtime.start_session("ship package").session

    runtime.checkpoint(session, "first repo scaffold")

    loaded = runtime.resume_session(session.id)
    assert loaded.reasoning_history == ["[checkpoint] first repo scaffold"]


def test_cli_accepts_store_after_subcommands(tmp_path):
    store = tmp_path / "runtime"

    assert main(["init", "--store", str(store)]) == 0
    assert main(["session", "start", "cli store smoke", "--store", str(store)]) == 0

    sessions = JsonRuntimeStore(store).list_sessions()
    assert sessions[0].goal == "cli store smoke"
