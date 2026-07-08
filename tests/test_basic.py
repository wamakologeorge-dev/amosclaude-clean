"""Basic tests for Amoscloud AI"""

import pytest
import asyncio
from src.amoscloud_ai.models import DeploymentConfig, DatabaseMigration
from src.amoscloud_ai.config import settings
from src.amoscloud_ai.logger import log
from src.core.ci_orchestrator import CIOrchestrator, PipelineStatus
from src.core.code_analyzer import CodeAnalyzer
from src.core.smart_deployer import SmartDeployer, DeploymentStatus
from src.ai.agent_contingency import AIAgentContingency, ContingencyLevel
from src.database.db_manager import DatabaseManager


class TestModels:
    def test_deployment_config_defaults(self):
        config = DeploymentConfig(environment="staging")
        assert config.environment == "staging"
        assert config.pre_deploy_tests is True
        assert config.auto_rollback is True
        assert config.deploy_command is None

    def test_deployment_config_custom(self):
        config = DeploymentConfig(
            environment="production",
            deploy_command="docker-compose up -d",
            pre_deploy_tests=False,
            auto_rollback=False,
        )
        assert config.environment == "production"
        assert config.deploy_command == "docker-compose up -d"
        assert config.pre_deploy_tests is False
        assert config.auto_rollback is False

    def test_database_migration_defaults(self):
        migration = DatabaseMigration(migration_name="001_initial")
        assert migration.migration_name == "001_initial"
        assert migration.auto_backup is True
        assert migration.rollback_on_failure is True


class TestSettings:
    def test_settings_defaults(self):
        assert settings.deployment_retries >= 1
        assert isinstance(settings.database_url, str)
        assert isinstance(settings.redis_url, str)
        assert isinstance(settings.debug, bool)


class TestCIOrchestrator:
    def test_initial_status(self):
        orchestrator = CIOrchestrator(config={})
        status = orchestrator.get_status()
        assert status["status"] == PipelineStatus.PENDING.value
        assert status["jobs_count"] == 0
        assert status["reports_count"] == 0

    def test_start_pipeline_push(self):
        orchestrator = CIOrchestrator(config={})
        result = asyncio.get_event_loop().run_until_complete(
            orchestrator.start_pipeline("push", {"branch": "main"})
        )
        assert result is True
        assert orchestrator.status == PipelineStatus.SUCCESS

    def test_start_pipeline_pr(self):
        orchestrator = CIOrchestrator(config={})
        result = asyncio.get_event_loop().run_until_complete(
            orchestrator.start_pipeline("pull_request", {"number": 42})
        )
        assert result is True

    def test_start_pipeline_schedule(self):
        orchestrator = CIOrchestrator(config={})
        result = asyncio.get_event_loop().run_until_complete(
            orchestrator.start_pipeline("schedule", {})
        )
        assert result is True


class TestCodeAnalyzer:
    def test_analyze_existing_file(self, tmp_path):
        test_file = tmp_path / "sample.py"
        test_file.write_text("def hello():\n    pass\n")
        analyzer = CodeAnalyzer()
        result = analyzer.analyze_file(str(test_file))
        assert result["file"] == str(test_file)
        assert "hello" in result["functions"]

    def test_analyze_missing_file(self):
        analyzer = CodeAnalyzer()
        result = analyzer.analyze_file("/nonexistent/file.py")
        assert result == {}

    def test_calculate_complexity(self):
        import ast
        analyzer = CodeAnalyzer()
        tree = ast.parse("if True:\n    pass\nfor i in range(10):\n    pass\n")
        complexity = analyzer._calculate_complexity(tree)
        assert complexity >= 3


class TestSmartDeployer:
    def test_initial_status(self):
        deployer = SmartDeployer(config={})
        assert deployer.status == DeploymentStatus.PENDING

    def test_deploy_success(self):
        deployer = SmartDeployer(config={})
        result = asyncio.get_event_loop().run_until_complete(
            deployer.deploy("1.0.0", "staging")
        )
        assert result is True
        assert deployer.status == DeploymentStatus.COMPLETED

    def test_rollback(self):
        deployer = SmartDeployer(config={})
        result = asyncio.get_event_loop().run_until_complete(
            deployer.rollback("1.0.0", "staging")
        )
        assert result is True
        assert deployer.status == DeploymentStatus.ROLLED_BACK


class TestAIAgentContingency:
    def test_initialization(self):
        contingency = AIAgentContingency(config={"max_retries": 5, "retry_delay": 2})
        assert contingency.max_retries == 5
        assert contingency.retry_delay == 2

    def test_register_fallback(self):
        contingency = AIAgentContingency(config={})

        async def handler(ctx):
            return True

        contingency.register_fallback("ValueError", handler)
        assert "ValueError" in contingency.fallback_handlers

    def test_get_contingency_report(self):
        contingency = AIAgentContingency(config={})
        report = contingency.get_contingency_report()
        assert "total_events" in report
        assert "events" in report
        assert report["total_events"] == 0

    def test_handle_contingency(self):
        contingency = AIAgentContingency(config={})
        result = asyncio.get_event_loop().run_until_complete(
            contingency.handle_contingency(
                ValueError("test error"),
                {"operation": "test"},
                ContingencyLevel.LOW,
            )
        )
        assert result is True


class TestDatabaseManager:
    def test_connect(self):
        db = DatabaseManager("sqlite:///test.db")
        result = db.connect()
        assert result is True

    def test_get_session_without_connection(self):
        db = DatabaseManager("sqlite:///test.db")
        session = db.get_session()
        assert session is None

    def test_get_tables(self):
        db = DatabaseManager("sqlite:///test.db")
        tables = db.get_tables()
        assert isinstance(tables, list)
