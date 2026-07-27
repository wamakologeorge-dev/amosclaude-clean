from src.agent.engineering_loop import AutonomousEngineeringLoop


class Analyzer:
    def inspect(self):
        return ["repository mapped", "dependency graph ready"]


class Model:
    def plan(self, objective, evidence):
        return ["inspect", "change", "verify"]

    def complete(self, objective, evidence):
        return '{"changes":[{"path":"result.txt","content":"verified","reason":"test"}]}'


class Files:
    def __init__(self):
        self.writes = []

    def write(self, path, content, *, authorized):
        assert authorized is True
        self.writes.append((path, content))


class Runtime:
    def __init__(self, passed=True):
        self.passed = passed

    def verify(self):
        return [{"name": "tests", "passed": self.passed, "summary": "tests passed" if self.passed else "tests failed"}]


def make_loop(passed=True):
    files = Files()
    loop = AutonomousEngineeringLoop(analyzer=Analyzer(), model=Model(), files=files, runtime=Runtime(passed))
    return loop, files


def test_read_only_loop_runs_all_reporting_phases_without_writes():
    loop, files = make_loop()
    result = loop.run(objective="inspect project", mode="plan", authorized_writes=False)
    assert result.status == "success"
    assert files.writes == []
    assert [event.phase for event in result.events] == ["understand", "inspect", "plan", "execute", "verify", "learn", "report"]


def test_fix_requires_explicit_write_authorization():
    loop, files = make_loop()
    result = loop.run(objective="repair project", mode="fix", authorized_writes=False)
    assert result.status == "blocked"
    assert "authorization" in result.blocker.lower()
    assert files.writes == []


def test_authorized_fix_writes_then_verifies():
    loop, files = make_loop()
    result = loop.run(objective="repair project", mode="fix", authorized_writes=True)
    assert result.status == "success"
    assert result.changed_files == ["result.txt"]
    assert files.writes == [("result.txt", "verified")]
    assert result.lessons


def test_failed_verification_never_reports_success():
    loop, _ = make_loop(passed=False)
    result = loop.run(objective="check project", mode="plan", authorized_writes=False)
    assert result.status == "failed"
    assert result.blocker == "tests failed"
    assert any("Do not report success" in lesson for lesson in result.lessons)


class CorrectingModel:
    def __init__(self):
        self.calls = []

    def plan(self, objective, evidence):
        return ["inspect", "repair", "verify", "self-correct"]

    def complete(self, objective, evidence):
        self.calls.append((objective, list(evidence)))
        content = "broken" if len(self.calls) == 1 else "corrected"
        return (
            '{"changes":[{"path":"result.txt","content":"'
            + content
            + '","reason":"test"}]}'
        )


class CorrectingRuntime:
    def __init__(self):
        self.calls = 0

    def verify(self, changed_files=None):
        self.calls += 1
        if self.calls == 1:
            return [
                {
                    "name": "Python compilation",
                    "passed": False,
                    "exit_code": 1,
                    "summary": "NameError: missing symbol",
                    "output": "Traceback: NameError: missing symbol",
                    "command": "python -m py_compile result.py",
                    "isolated": True,
                }
            ]
        return [
            {
                "name": "Python compilation",
                "passed": True,
                "exit_code": 0,
                "summary": "compiled",
                "output": "compiled",
                "command": "python -m py_compile result.py",
                "isolated": True,
            }
        ]


def test_failed_isolated_verification_drives_a_corrective_patch():
    model = CorrectingModel()
    files = Files()
    runtime = CorrectingRuntime()
    loop = AutonomousEngineeringLoop(
        analyzer=Analyzer(),
        model=model,
        files=files,
        runtime=runtime,
        max_attempts=3,
    )

    result = loop.run(
        objective="repair compiler error",
        mode="fix",
        authorized_writes=True,
    )

    assert result.status == "success"
    assert runtime.calls == 2
    assert files.writes == [
        ("result.txt", "broken"),
        ("result.txt", "corrected"),
    ]
    assert len(model.calls) == 2
    retry_objective, retry_evidence = model.calls[1]
    assert "failed isolated verification" in retry_objective.lower()
    assert any("NameError: missing symbol" in item for item in retry_evidence)
    assert any(event.status == "retry" for event in result.events)
