from amoscloud_ai.agent import AgentRuntime, AgentStep, Tool, ToolResult


class ScriptedModel:
    def __init__(self, steps):
        self.steps = iter(steps)

    def next_step(self, **_kwargs):
        return next(self.steps)


def test_agent_executes_tool_then_finishes_with_evidence():
    model = ScriptedModel(
        [
            AgentStep("inspect", tool="check", arguments={"value": 7}),
            AgentStep("verified", final_answer="done"),
        ]
    )
    tool = Tool(
        "check",
        "Return verification evidence",
        lambda args: ToolResult(True, "ok", {"checked": args["value"]}),
    )

    result = AgentRuntime(model, [tool]).run("verify project")

    assert result.status == "completed"
    assert result.answer == "done"
    assert result.iterations == 2
    assert result.evidence == [{"tool": "check", "checked": 7}]


def test_agent_blocks_unapproved_tool():
    model = ScriptedModel(
        [
            AgentStep("dangerous", tool="delete", arguments={}),
            AgentStep("stop", final_answer="not executed"),
        ]
    )
    called = False

    def handler(_args):
        nonlocal called
        called = True
        return ToolResult(True, "deleted")

    result = AgentRuntime(
        model,
        [Tool("delete", "Dangerous operation", handler, requires_approval=True)],
    ).run("delete data")

    assert result.status == "completed"
    assert called is False
