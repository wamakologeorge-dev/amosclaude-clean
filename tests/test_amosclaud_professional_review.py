from amosclaud_bot.professional import _changed_file_summary, _professional_review


def test_changed_file_summary_detects_risk_and_tests():
    files = [
        {"filename": ".github/workflows/ci.yml", "additions": 10, "deletions": 2},
        {"filename": "src/app.py", "additions": 20, "deletions": 4},
        {"filename": "tests/test_app.py", "additions": 12, "deletions": 1},
    ]
    summary = _changed_file_summary(files)
    assert ".github/workflows/ci.yml" in summary["high_risk"]
    assert "tests/test_app.py" in summary["tests"]
    assert summary["changed_lines"] == 49


def test_professional_review_requests_changes_for_high_risk_paths():
    pr = {
        "title": "Update CI",
        "base": {"ref": "main"},
        "head": {"ref": "feature/ci"},
    }
    files = [
        {"filename": ".github/workflows/ci.yml", "additions": 12, "deletions": 2},
        {"filename": "tests/test_ci.py", "additions": 10, "deletions": 0},
    ]
    result = {"status": "completed", "evidence": ["Autonomous review completed"]}
    body = _professional_review(pr=pr, files=files, autonomous_result=result)
    assert "Professional PR Review" in body
    assert "Risk:** **HIGH" in body
    assert "CHANGES REQUESTED" in body
    assert "Security" in body
    assert "Tests" in body


def test_professional_review_requires_human_review_when_source_has_no_tests():
    pr = {
        "title": "Change application",
        "base": {"ref": "main"},
        "head": {"ref": "feature/app"},
    }
    files = [{"filename": "src/app.py", "additions": 20, "deletions": 2}]
    result = {"status": "success"}
    body = _professional_review(pr=pr, files=files, autonomous_result=result)
    assert "Risk:** **MEDIUM" in body
    assert "NEEDS HUMAN REVIEW" in body
    assert "no changed test file" in body.lower()


def test_professional_review_can_approve_low_risk_tested_change():
    pr = {
        "title": "Improve parser",
        "base": {"ref": "main"},
        "head": {"ref": "feature/parser"},
    }
    files = [
        {"filename": "src/parser.py", "additions": 8, "deletions": 2},
        {"filename": "tests/test_parser.py", "additions": 12, "deletions": 0},
    ]
    result = {"status": "completed"}
    body = _professional_review(pr=pr, files=files, autonomous_result=result)
    assert "Risk:** **LOW" in body
    assert "**APPROVE**" in body
