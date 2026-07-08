"""
Database service for database management and migrations
"""

from typing import Optional
import subprocess
from src.amoscloud_ai.logger import log
from src.amoscloud_ai.models import DatabaseMigration


class DatabaseService:
    """Handle database operations"""
    
    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url
    
    def run_migration(self, migration: DatabaseMigration) -> bool:
        """Execute database migration"""
        try:
            # Create backup if enabled
            if migration.auto_backup:
                log.info(f"Creating backup before migration")
                self.backup_database()
            
            log.info(f"Running migration: {migration.migration_name}")
            
            # Execute migration script
            result = subprocess.run(
                f"alembic upgrade head",
                shell=True,
                capture_output=True,
                text=True,
                timeout=600
            )
            
            if result.returncode == 0:
                log.info(f"Migration {migration.migration_name} completed successfully")
                return True
            else:
                log.error(f"Migration failed: {result.stderr}")
                if migration.rollback_on_failure:
                    log.info("Rolling back migration")
                    self.rollback_migration()
                return False
        except Exception as e:
            log.error(f"Migration error: {str(e)}")
            return False
    
    def backup_database(self) -> bool:
        """Create database backup"""
        try:
            log.info("Creating database backup")
            
            result = subprocess.run(
                "pg_dump -U postgres > backup.sql",
                shell=True,
                capture_output=True,
                timeout=300
            )
            
            if result.returncode == 0:
                log.info("Database backup created successfully")
                return True
            else:
                log.error(f"Backup failed: {result.stderr}")
                return False
        except Exception as e:
            log.error(f"Backup error: {str(e)}")
            return False
    
    def restore_database(self, backup_file: str) -> bool:
        """Restore database from backup"""
        try:
            log.info(f"Restoring database from {backup_file}")
            
            result = subprocess.run(
                f"psql -U postgres < {backup_file}",
                shell=True,
                capture_output=True,
                timeout=600
            )
            
            if result.returncode == 0:
                log.info("Database restored successfully")
                return True
            else:
                log.error(f"Restore failed: {result.stderr}")
                return False
        except Exception as e:
            log.error(f"Restore error: {str(e)}")
            return False
    
    def rollback_migration(self) -> bool:
        """Rollback last migration"""
        try:
            log.info("Rolling back migration")
            
            result = subprocess.run(
                "alembic downgrade -1",
                shell=True,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode == 0:
                log.info("Migration rolled back successfully")
                return True
            else:
                log.error(f"Rollback failed: {result.stderr}")
                return False
        except Exception as e:
            log.error(f"Rollback error: {str(e)}")
            return False
    
    def get_database_status(self) -> dict:
        """Get database status"""
        try:
            log.info("Checking database status")
            
            result = subprocess.run(
                "alembic current",
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                return {
                    "status": "healthy",
                    "current_migration": result.stdout.strip()
                }
            else:
                return {
                    "status": "error",
                    "error": result.stderr
                }
        except Exception as e:
            log.error(f"Failed to get database status: {str(e)}")
            return {"status": "unknown", "error": str(e)}
