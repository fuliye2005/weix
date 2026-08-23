import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.ai.persona_replay import PersonaReplayEngine, build_replay_index
from app.ai.agent import WeixAgent
from app.ai.style_distiller import StyleDistiller


TARGET_ID = "wxid_target"


def _message(
    speaker_id: str,
    content: str,
    *,
    source_file: str,
    source_index: int,
    conversation_id: str,
    is_group: bool,
) -> dict:
    return {
        "speaker_id": speaker_id,
        "speaker_name": speaker_id,
        "content": content,
        "source_file": source_file,
        "source_index": source_index,
        "conversation_id": conversation_id,
        "is_group": is_group,
    }


def test_build_index_keeps_file_boundaries_and_merges_consecutive_target_messages(tmp_path):
    messages = [
        _message("wxid_other", "第一组上下文", source_file="one.json", source_index=0, conversation_id="room_a@chatroom", is_group=True),
        _message(TARGET_ID, "第一组回复", source_file="one.json", source_index=1, conversation_id="room_a@chatroom", is_group=True),
        _message(TARGET_ID, "补充一句", source_file="one.json", source_index=2, conversation_id="room_a@chatroom", is_group=True),
        _message(TARGET_ID, "第二组目标先出现", source_file="two.json", source_index=0, conversation_id="room_b@chatroom", is_group=True),
        _message("wxid_other", "第二组上下文", source_file="two.json", source_index=1, conversation_id="room_b@chatroom", is_group=True),
        _message(TARGET_ID, "第二组回复", source_file="two.json", source_index=2, conversation_id="room_b@chatroom", is_group=True),
    ]

    index = build_replay_index(messages, TARGET_ID, "目标", index_path=tmp_path / "persona_replay.json")

    assert index["meta"]["sample_count"] == 2
    assert {sample["source_file"] for sample in index["samples"]} == {"one.json", "two.json"}
    first = next(sample for sample in index["samples"] if sample["source_file"] == "one.json")
    assert first["reply"] == "第一组回复\n补充一句"
    assert all("第二组上下文" not in item["content"] for item in first["context"])


def test_match_prefers_same_scene_and_can_return_direct_history(tmp_path):
    messages = [
        _message("wxid_friend", "你晚上有空吗", source_file="private.json", source_index=0, conversation_id="wxid_friend", is_group=False),
        _message(TARGET_ID, "有啊，咋了", source_file="private.json", source_index=1, conversation_id="wxid_friend", is_group=False),
        _message("wxid_friend", "你晚上有空吗", source_file="group.json", source_index=0, conversation_id="room@chatroom", is_group=True),
        _message(TARGET_ID, "群里问这个干嘛", source_file="group.json", source_index=1, conversation_id="room@chatroom", is_group=True),
    ]
    path = tmp_path / "persona_replay.json"
    build_replay_index(messages, TARGET_ID, "目标", index_path=path)
    engine = PersonaReplayEngine(
        index_path=path,
        config={"direct_threshold": 0.8, "few_shot_threshold": 0.4},
    )

    private_result = engine.match(
        "你晚上有空吗",
        recent_context="朋友: 你晚上有空吗",
        is_group=False,
        session_id="private:wxid_friend",
        sender_id="wxid_friend",
    )
    group_result = engine.match(
        "你晚上有空吗",
        recent_context="朋友: 你晚上有空吗",
        is_group=True,
        session_id="group:room@chatroom",
        sender_id="wxid_friend",
        room_id="room@chatroom",
    )

    assert private_result["direct"]["reply"] == "有啊，咋了"
    assert group_result["direct"]["reply"] == "群里问这个干嘛"


def test_match_returns_few_shot_or_miss_by_threshold(tmp_path):
    messages = [
        _message("wxid_friend", "周五晚上有空吗", source_file="one.json", source_index=0, conversation_id="wxid_friend", is_group=False),
        _message(TARGET_ID, "有空，怎么啦", source_file="one.json", source_index=1, conversation_id="wxid_friend", is_group=False),
    ]
    path = tmp_path / "persona_replay.json"
    build_replay_index(messages, TARGET_ID, "目标", index_path=path)

    few_shot_engine = PersonaReplayEngine(
        index_path=path,
        config={"direct_threshold": 1.1, "few_shot_threshold": 0.2},
    )
    few_shot_result = few_shot_engine.match(
        "周五晚上有空不",
        recent_context="朋友: 周五晚上有空不",
        session_id="private:wxid_friend",
    )
    assert few_shot_result["direct"] is None
    assert few_shot_result["few_shot"]

    miss_engine = PersonaReplayEngine(
        index_path=path,
        config={"direct_threshold": 0.8, "few_shot_threshold": 1.1},
    )
    miss_result = miss_engine.match("明天开会吗", session_id="private:wxid_friend")
    assert miss_result["matched"] is False
    assert miss_result["few_shot"] == []


def test_replay_cooldown_blocks_same_reply_and_needs_no_llm(tmp_path):
    messages = [
        _message("wxid_friend", "在干嘛", source_file="one.json", source_index=0, conversation_id="wxid_friend", is_group=False),
        _message(TARGET_ID, "摸鱼呢", source_file="one.json", source_index=1, conversation_id="wxid_friend", is_group=False),
    ]
    path = tmp_path / "persona_replay.json"
    build_replay_index(messages, TARGET_ID, "目标", index_path=path)
    engine = PersonaReplayEngine(index_path=path, config={"direct_threshold": 0.8, "few_shot_threshold": 0.3, "repeat_cooldown": 60})

    first = engine.match("在干嘛", recent_context="朋友: 在干嘛", session_id="s")
    assert first["direct"]["reply"] == "摸鱼呢"
    engine.remember_reply("s", first["direct"]["reply"])
    second = engine.match("在干嘛", recent_context="朋友: 在干嘛", session_id="s")
    assert second["direct"] is None

    distiller = StyleDistiller(cache_path=tmp_path / "persona_skill.json", initialize_llm=False)
    skill = distiller.build_replay_skill(
        persona_name="目标",
        target_speaker_id=TARGET_ID,
        replay_stats={"sample_count": 1, "target_message_count": 1},
    )
    assert skill["simulation_mode"] == "replay"
    assert "摸鱼呢" not in json.dumps(skill, ensure_ascii=False)


def test_agent_replay_direct_path_does_not_create_agent_or_summarize(monkeypatch, tmp_path):
    messages = [
        _message("wxid_friend", "在干嘛", source_file="one.json", source_index=0, conversation_id="wxid_friend", is_group=False),
        _message(TARGET_ID, "摸鱼呢", source_file="one.json", source_index=1, conversation_id="wxid_friend", is_group=False),
    ]
    path = tmp_path / "persona_replay.json"
    build_replay_index(messages, TARGET_ID, "目标", index_path=path)
    engine = PersonaReplayEngine(index_path=path, config={"direct_threshold": 0.8, "few_shot_threshold": 0.3})

    class Memory:
        def __init__(self):
            self.recorded = []

        def record_turn(self, session_id, message, reply):
            self.recorded.append((session_id, message, reply))

        async def maybe_summarize(self, session_id):
            raise AssertionError("replay 直复用不应触发摘要 LLM")

    memory = Memory()
    agent = WeixAgent.__new__(WeixAgent)
    agent.memory = memory
    agent._rag = None
    agent._save_checkpoints = lambda: None

    old_engine = WeixAgent._replay_engine
    old_distiller = WeixAgent._distiller
    try:
        WeixAgent._replay_engine = engine
        WeixAgent._distiller = SimpleNamespace(has_persona=False)
        monkeypatch.setattr(WeixAgent, "_get_simulation_mode", classmethod(lambda cls: "replay"))
        monkeypatch.setattr(
            WeixAgent,
            "_create_agent",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("replay 不应创建 LangGraph Agent")),
        )

        result = __import__("asyncio").run(
            agent.chat(
                "在干嘛",
                session_id="private:wxid_friend",
                context={
                    "is_group": False,
                    "user_wxid": "wxid_friend",
                    "user_name": "朋友",
                    "chat_context": "朋友: 在干嘛",
                },
            )
        )
    finally:
        WeixAgent._replay_engine = old_engine
        WeixAgent._distiller = old_distiller

    assert result == "摸鱼呢"
    assert memory.recorded == [("private:wxid_friend", "在干嘛", "摸鱼呢")]


def test_agent_hybrid_uses_few_shot_then_falls_back_to_persona(monkeypatch, tmp_path):
    messages = [
        _message(
            "wxid_friend",
            "周五晚上有空吗",
            source_file="one.json",
            source_index=0,
            conversation_id="wxid_friend",
            is_group=False,
        ),
        _message(
            TARGET_ID,
            "有空，怎么啦",
            source_file="one.json",
            source_index=1,
            conversation_id="wxid_friend",
            is_group=False,
        ),
    ]
    path = tmp_path / "persona_replay.json"
    build_replay_index(messages, TARGET_ID, "目标", index_path=path)
    engine = PersonaReplayEngine(
        index_path=path,
        config={"direct_threshold": 1.1, "few_shot_threshold": 0.2},
    )

    class Memory:
        def __init__(self):
            self.recorded = []

        def record_turn(self, session_id, message, reply):
            self.recorded.append((session_id, message, reply))

        async def maybe_summarize(self, session_id):
            return None

    class FakeAgent:
        def invoke(self, *_args, **_kwargs):
            from langchain_core.messages import AIMessage

            return {"messages": [AIMessage(content="Persona 回退回复")]}

    memory = Memory()
    agent = WeixAgent.__new__(WeixAgent)
    agent.memory = memory
    agent._rag = None
    agent._save_checkpoints = lambda: None
    captured_context = {}

    old_engine = WeixAgent._replay_engine
    old_distiller = WeixAgent._distiller
    try:
        WeixAgent._replay_engine = engine
        WeixAgent._distiller = SimpleNamespace(has_persona=True)
        monkeypatch.setattr(
            WeixAgent,
            "_get_simulation_mode",
            classmethod(lambda cls: "hybrid"),
        )
        monkeypatch.setattr(
            WeixAgent,
            "_create_agent",
            lambda self, _session_id, _is_group, context: (
                captured_context.update(context) or FakeAgent()
            ),
        )

        result = __import__("asyncio").run(
            agent.chat(
                "周五晚上有空不",
                session_id="private:wxid_friend",
                context={
                    "is_group": False,
                    "user_wxid": "wxid_friend",
                    "user_name": "朋友",
                    "chat_context": "朋友: 周五晚上有空不",
                },
            )
        )
    finally:
        WeixAgent._replay_engine = old_engine
        WeixAgent._distiller = old_distiller

    assert result == "Persona 回退回复"
    assert "历史表达参考" in captured_context["persona_replay_examples"]


def test_replay_mode_reads_cached_skill_without_initializing_llm(monkeypatch):
    class ReadOnlyDistiller:
        def __init__(self, *, initialize_llm):
            assert initialize_llm is False
            self.has_persona = True
            self.mode = "replay"
            self.simulation_mode = "replay"

    monkeypatch.setattr("app.ai.style_distiller.StyleDistiller", ReadOnlyDistiller)
    old_distiller = WeixAgent._distiller
    try:
        WeixAgent._distiller = None
        assert WeixAgent._get_simulation_mode() == "replay"
    finally:
        WeixAgent._distiller = old_distiller


def test_hybrid_generated_reply_enters_same_session_cooldown(monkeypatch, tmp_path):
    path = tmp_path / "persona_replay.json"
    build_replay_index(
        [
            _message(
                "wxid_friend",
                "原始问题",
                source_file="one.json",
                source_index=0,
                conversation_id="wxid_friend",
                is_group=False,
            ),
            _message(
                TARGET_ID,
                "历史回复",
                source_file="one.json",
                source_index=1,
                conversation_id="wxid_friend",
                is_group=False,
            ),
        ],
        TARGET_ID,
        "目标",
        index_path=path,
    )
    engine = PersonaReplayEngine(
        index_path=path,
        config={"direct_threshold": 1.1, "few_shot_threshold": 0.2, "repeat_cooldown": 60},
    )

    class Memory:
        def record_turn(self, *_args):
            return None

        async def maybe_summarize(self, _session_id):
            return None

    class FakeAgent:
        def invoke(self, *_args, **_kwargs):
            from langchain_core.messages import AIMessage

            return {"messages": [AIMessage(content="生成回复")]}

    agent = WeixAgent.__new__(WeixAgent)
    agent.memory = Memory()
    agent._rag = None
    agent._save_checkpoints = lambda: None
    old_engine = WeixAgent._replay_engine
    old_distiller = WeixAgent._distiller
    try:
        WeixAgent._replay_engine = engine
        WeixAgent._distiller = SimpleNamespace(has_persona=True)
        monkeypatch.setattr(WeixAgent, "_get_simulation_mode", classmethod(lambda cls: "hybrid"))
        monkeypatch.setattr(WeixAgent, "_create_agent", lambda *_args, **_kwargs: FakeAgent())
        __import__("asyncio").run(
            agent.chat(
                "原始问题改写",
                session_id="private:wxid_friend",
                context={"is_group": False, "user_wxid": "wxid_friend", "chat_context": "朋友: 原始问题改写"},
            )
        )
    finally:
        WeixAgent._replay_engine = old_engine
        WeixAgent._distiller = old_distiller

    assert "生成回复" in engine._blocked_replies("private:wxid_friend")
