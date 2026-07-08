"""Data models for Amoscloud AI"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DeploymentConfig:
    """Configuration for a deployment operation"""

    environment: str
    deploy_command: Optional[str] = None
    pre_deploy_tests: bool = True
    auto_rollback: bool = True


@dataclass
class DatabaseMigration:
    """Configuration for a database migration"""

    migration_name: str
    auto_backup: bool = True
    rollback_on_failure: bool = True
