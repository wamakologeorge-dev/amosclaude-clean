from __future__ import annotations

from pathlib import Path
from textwrap import dedent


ROOT = Path(__file__).resolve().parents[2]


def replace_between(
    path: Path,
    start_marker: str,
    end_marker: str,
    replacement: str,
) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(start_marker) != 1:
        raise RuntimeError(
            f"Expected one start marker in {path}, found {text.count(start_marker)}"
        )
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")


def patch_platform_services() -> None:
    path = ROOT / "amoscloud_ai/api/routes/platform_services.py"
    replacement = dedent(
        '''\
        def _self_hosted_reachable() -> bool:
            cand = _find_candidate("self-hosted")
            return bool(
                cand is not None
                and cand.configured
                and model_runtime.candidate_health(cand).reachable
            )


        def _model_network_reachable() -> tuple[bool, int]:
            """Return whether a genuine first-party station can serve inference."""
            state = model_runtime.network_state()
            stations = int(state.get("ready_stations") or 0)
            return bool(state.get("ready") and stations > 0), stations


        def _check_amosclaud_provider() -> dict:
            """Report the aggregate first-party provider path truthfully.

            Model-network stations, the optional hosted Amosclaud API, and the direct
            self-hosted endpoint are all first-party routes. The provider path is
            operational when any one of those routes is genuinely reachable.
            """
            sid = "amosclaud-provider"
            name = "First-party Amosclaud provider path"

            network_reachable, stations = _model_network_reachable()
            if network_reachable:
                return _entry(
                    sid,
                    name,
                    OPERATIONAL,
                    f"{stations} first-party model station(s) are registered and online, "
                    "so the Amosclaud provider path can serve inference even if the "
                    "direct self-hosted endpoint is unavailable.",
                    "amoscloud_ai.model_network.network_status() and the model-runtime "
                    "resolution order",
                )

            cand = _find_candidate("amosclaud-api")
            api_health = None
            if cand is not None and cand.configured:
                api_health = model_runtime.candidate_health(cand)
                if api_health.reachable:
                    return _health_entry(sid, name, cand, api_health)

            if _self_hosted_reachable():
                return _entry(
                    sid,
                    name,
                    OPERATIONAL,
                    "The direct self-hosted model runtime is reachable and serves the "
                    "first-party provider path, so the optional hosted Amosclaud API "
                    "and station network are not required.",
                    "model_runtime candidate 'self-hosted' passed its bounded preflight",
                )

            if cand is not None and api_health is not None:
                return _health_entry(sid, name, cand, api_health)

            return _entry(
                sid,
                name,
                NOT_CONFIGURED,
                "No model station is ready, the remote-hosted Amosclaud API is not "
                "configured, and no self-hosted runtime is reachable, so the "
                "first-party provider path cannot serve traffic.",
                "model_runtime candidates 'model-network', 'amosclaud-api', and "
                "'self-hosted'",
                "Connect an online model station, configure a reachable self-hosted "
                "AMOSCLAUD_MODEL_URL, or set AMOSCLAUD_PROVIDER_API_URL + "
                "AMOSCLAUD_API_KEY for the remote API.",
            )


        '''
    )
    replace_between(
        path,
        "def _self_hosted_reachable() -> bool:\n",
        "def _check_model_runtime() -> dict:\n",
        replacement,
    )


def patch_model_runtime() -> None:
    path = ROOT / "amoscloud_ai/model_runtime.py"
    text = path.read_text(encoding="utf-8")

    status_marker = "def _status_code(error: BaseException) -> int | None:\n"
    if text.count(status_marker) != 1:
        raise RuntimeError(
            f"Expected one _status_code marker, found {text.count(status_marker)}"
        )

    helper = dedent(
        '''\
        def _preflight_timeout_diagnosis(
            error: BaseException, candidate: Candidate
        ) -> Diagnosis:
            """Explain a TCP preflight timeout without confusing it with inference."""
            endpoint = candidate.sanitized_endpoint or "the configured model endpoint"
            endpoint_env = candidate.endpoint_env or "AMOSCLAUD_MODEL_URL"
            return Diagnosis(
                code=TIMEOUT,
                detail=redact(f"{type(error).__name__}: {error}")[:300],
                remediation=(
                    f"{endpoint} did not accept a TCP connection within the bounded "
                    "preflight — check that the model service is running and listening "
                    "on the private-network host and port, confirm "
                    f"{endpoint_env} points at the inference port, and raise "
                    "AMOSCLAUD_MODEL_PROBE_TIMEOUT only if the healthy service needs a "
                    "larger connection budget."
                ),
            )


        '''
    )
    text = text.replace(status_marker, helper + status_marker, 1)

    tcp_start_marker = (
        "    try:\n"
        "        _tcp_connect(host, port, connect_budget_seconds())\n"
    )
    success_marker = (
        "    return CandidateHealth(candidate=candidate, reachable=True, checked_at=now)\n"
    )
    if text.count(tcp_start_marker) != 1:
        raise RuntimeError(
            f"Expected one TCP preflight start, found {text.count(tcp_start_marker)}"
        )
    tcp_start = text.index(tcp_start_marker)
    tcp_end = text.index(success_marker, tcp_start)
    tcp_block = dedent(
        '''\
            try:
                _tcp_connect(host, port, connect_budget_seconds())
            except Exception as error:
                diagnosis = classify(error, candidate)
                if diagnosis.code == TIMEOUT:
                    diagnosis = _preflight_timeout_diagnosis(error, candidate)
                return CandidateHealth(
                    candidate=candidate,
                    reachable=False,
                    diagnosis=diagnosis,
                    checked_at=now,
                )
        '''
    )
    text = text[:tcp_start] + tcp_block + text[tcp_end:]
    path.write_text(text, encoding="utf-8")


def write_regression_tests() -> None:
    path = ROOT / "tests/test_model_runtime_dashboard_corrections.py"
    path.write_text(
        dedent(
            '''\
            """Regression tests for model provider dashboard corrections."""
            from __future__ import annotations

            import socket

            from amoscloud_ai import model_runtime
            from amoscloud_ai.api.routes import platform_services as ps


            def test_provider_path_is_operational_via_online_station(monkeypatch):
                monkeypatch.setattr(
                    ps.model_runtime,
                    "network_state",
                    lambda: {
                        "configured": True,
                        "ready": True,
                        "ready_stations": 1,
                    },
                )
                monkeypatch.setattr(
                    ps,
                    "_self_hosted_reachable",
                    lambda: False,
                )

                entry = ps._check_amosclaud_provider()

                assert entry["state"] == ps.OPERATIONAL
                assert "station" in entry["explanation"].lower()
                assert "1" in entry["explanation"]


            def test_tcp_preflight_timeout_names_probe_timeout(monkeypatch):
                monkeypatch.delenv("AMOSCLAUD_MODEL_ENDPOINT", raising=False)
                monkeypatch.delenv("AMOSCLAUD_BOT_URL", raising=False)
                monkeypatch.setenv(
                    "AMOSCLAUD_MODEL_URL",
                    "http://amosclaud-model.railway.internal:11434",
                )
                model_runtime.reset_cache()
                candidate = next(
                    item
                    for item in model_runtime.resolve_candidates(
                        {"configured": False, "ready": False, "ready_stations": 0}
                    )
                    if item.key == "self-hosted"
                )
                monkeypatch.setattr(
                    model_runtime,
                    "_resolve_host",
                    lambda host, port: [
                        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))
                    ],
                )

                def timeout(host: str, port: int, budget: float) -> None:
                    raise socket.timeout("timed out")

                monkeypatch.setattr(model_runtime, "_tcp_connect", timeout)

                health = model_runtime.candidate_health(candidate, force=True)

                assert health.reachable is False
                assert health.diagnosis is not None
                assert health.diagnosis.code == model_runtime.TIMEOUT
                remediation = health.diagnosis.remediation
                assert "AMOSCLAUD_MODEL_PROBE_TIMEOUT" in remediation
                assert "AMOSCLAUD_MODEL_TIMEOUT" not in remediation
                assert "private-network" in remediation
            '''
        ),
        encoding="utf-8",
    )


def validate_text_contracts() -> None:
    platform = (ROOT / "amoscloud_ai/api/routes/platform_services.py").read_text(
        encoding="utf-8"
    )
    runtime = (ROOT / "amoscloud_ai/model_runtime.py").read_text(encoding="utf-8")

    required_platform = (
        "def _model_network_reachable() -> tuple[bool, int]:",
        "network_reachable, stations = _model_network_reachable()",
        "first-party model station(s) are registered and online",
    )
    required_runtime = (
        "def _preflight_timeout_diagnosis(",
        "AMOSCLAUD_MODEL_PROBE_TIMEOUT",
        "diagnosis = _preflight_timeout_diagnosis(error, candidate)",
    )
    for marker in required_platform:
        if marker not in platform:
            raise RuntimeError(f"Missing platform contract: {marker}")
    for marker in required_runtime:
        if marker not in runtime:
            raise RuntimeError(f"Missing runtime contract: {marker}")


def main() -> None:
    patch_platform_services()
    patch_model_runtime()
    write_regression_tests()
    validate_text_contracts()


if __name__ == "__main__":
    main()
