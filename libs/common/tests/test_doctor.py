from langchain_core.messages import AIMessage

from lessongen_common.llm import LLMProvider, LLMRole, LLMSettings
from lessongen_common.llm.doctor import _Ping, run_doctor
from lessongen_common.testing import ScriptedChatModel, tool_call_message


async def test_doctor_checks_capabilities_and_every_reasoning_effort() -> None:
    def script(efforts: int) -> list:
        return [
            AIMessage(content="OK"),
            _Ping(ok=True, word="pong"),
            tool_call_message("_PingTool", {"word": "pong"}),
        ] + [AIMessage(content="OK")] * efforts

    primary = ScriptedChatModel(model_name="gpt-5.5", script=script(2))  # efforts: low, medium
    fast = ScriptedChatModel(
        model_name="gpt-5.4-mini", script=script(3)
    )  # efforts: low, medium, none
    settings = LLMSettings(_env_file=None)  # type: ignore[call-arg]
    overrides = {
        role: primary if settings.resolve(role).tier == "primary" else fast for role in LLMRole
    }
    rows = await run_doctor(LLMProvider(settings, overrides=overrides))

    by_deployment = {r["deployment"]: r for r in rows}
    assert set(by_deployment) == {"gpt-5.5", "gpt-5.4-mini"}
    assert all(r["ok"] for r in rows)
    assert set(by_deployment["gpt-5.4-mini"]["efforts"]) == {"low", "medium", "none"}
    assert by_deployment["gpt-5.5"]["tool_calling"]["detail"] == "1 tool call(s)"


async def test_doctor_reports_a_rejected_effort() -> None:
    capabilities = [
        AIMessage(content="OK"),
        _Ping(ok=True, word="pong"),
        tool_call_message("_PingTool", {"word": "x"}),
    ]
    fast = ScriptedChatModel(
        script=[
            *capabilities,
            AIMessage(content="OK"),
            AIMessage(content="OK"),
            ValueError("Unsupported value: 'reasoning_effort' 'none'"),
        ]
    )
    primary = ScriptedChatModel(
        script=[*capabilities, AIMessage(content="OK"), AIMessage(content="OK")]
    )
    settings = LLMSettings(_env_file=None)  # type: ignore[call-arg]
    overrides = {
        role: primary if settings.resolve(role).tier == "primary" else fast for role in LLMRole
    }
    rows = {
        r["deployment"]: r for r in await run_doctor(LLMProvider(settings, overrides=overrides))
    }
    assert rows["gpt-5.4-mini"]["ok"] is False
    assert "reasoning_effort" in rows["gpt-5.4-mini"]["efforts"]["none"]["detail"]
    assert rows["gpt-5.5"]["ok"] is True
