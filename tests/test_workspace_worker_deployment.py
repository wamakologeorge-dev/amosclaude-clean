from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_workspace_worker_is_private_non_root_and_secret_backed() -> None:
    compose = yaml.safe_load(
        (ROOT / "deploy/workspace-worker/docker-compose.yml").read_text(
            encoding="utf-8"
        )
    )
    worker = compose["services"]["workspace-worker"]

    assert "ports" not in worker
    assert worker["expose"] == ["8092"]
    assert worker["read_only"] is True
    assert worker["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in worker["security_opt"]
    assert worker["pids_limit"] == 256
    assert worker["cpus"] == 1.0
    assert worker["mem_limit"] == "512m"
    assert worker["user"] != "0:0"
    assert worker["environment"]["DOCKER_HOST"].startswith("unix://")
    assert worker["environment"]["AMOSCLAUD_WORKSPACE_MAX_CPU"] == "2"
    assert worker["environment"]["AMOSCLAUD_WORKSPACE_MAX_MEMORY_MB"] == "4096"
    assert worker["environment"]["AMOSCLAUD_WORKSPACE_MAX_PIDS"] == "512"
    assert worker["environment"]["AMOSCLAUD_WORKSPACE_WORKER_TOKEN_FILE"].startswith(
        "/run/secrets/"
    )
    assert compose["networks"]["workspace-control"]["internal"] is True


def test_public_application_never_receives_workspace_docker_socket() -> None:
    worker_compose = (
        ROOT / "deploy/workspace-worker/docker-compose.yml"
    ).read_text(encoding="utf-8")
    public_compose = (ROOT / "Infrastructure/docker-compose.yml").read_text(
        encoding="utf-8"
    )

    assert "docker.sock" in worker_compose
    assert "docker.sock" not in public_compose


def test_workspace_worker_image_runs_as_non_root() -> None:
    dockerfile = (ROOT / "workspace_worker/Dockerfile").read_text(encoding="utf-8")

    assert "USER 10001:10001" in dockerfile
    assert "workspace_worker.app:app" in dockerfile
    assert "dockerd" not in dockerfile
