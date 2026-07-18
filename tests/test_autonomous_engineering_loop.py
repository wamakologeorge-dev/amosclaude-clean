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
