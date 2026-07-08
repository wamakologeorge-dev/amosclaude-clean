"""
Deployment service for application deployment and rollback
"""

import subprocess
from typing import Optional
from src.amoscloud_ai.logger import log
from src.amoscloud_ai.config import settings
from src.amoscloud_ai.models import DeploymentConfig


class DeployService:
    """Handle deployment operations"""
    
    def __init__(self):
        self.retries = settings.deployment_retries
    
    def deploy(self, config: DeploymentConfig) -> bool:
        """Deploy application"""
        try:
            log.info(f"Deploying to {config.environment} environment")
            
            # Run tests if enabled
            if config.pre_deploy_tests:
                log.info("Running pre-deployment tests")
                test_result = subprocess.run(
                    "pytest tests/",
                    shell=True,
                    capture_output=True,
                    timeout=300
                )
                if test_result.returncode != 0:
                    log.error("Pre-deployment tests failed")
                    return False
            
            # Execute deployment
            deploy_cmd = config.deploy_command or "docker-compose up -d"
            log.info(f"Executing deployment command: {deploy_cmd}")
            
            result = subprocess.run(
                deploy_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=600
            )
            
            if result.returncode == 0:
                log.info("Deployment successful")
                return True
            else:
                log.error(f"Deployment failed: {result.stderr}")
                if config.auto_rollback:
                    log.info("Initiating automatic rollback")
                    self.rollback(config)
                return False
        except Exception as e:
            log.error(f"Deployment error: {str(e)}")
            return False
    
    def rollback(self, config: DeploymentConfig) -> bool:
        """Rollback deployment"""
        try:
            log.info(f"Rolling back {config.environment} deployment")
            
            rollback_cmd = f"git reset --hard HEAD~1"
            result = subprocess.run(
                rollback_cmd,
                shell=True,
                capture_output=True,
                timeout=300
            )
            
            if result.returncode == 0:
                log.info("Rollback successful")
                return True
            else:
                log.error(f"Rollback failed: {result.stderr}")
                return False
        except Exception as e:
            log.error(f"Rollback error: {str(e)}")
            return False
    
    def deploy_with_retry(self, config: DeploymentConfig) -> bool:
        """Deploy with retry logic"""
        for attempt in range(self.retries):
            try:
                log.info(f"Deployment attempt {attempt + 1}/{self.retries}")
                if self.deploy(config):
                    return True
            except Exception as e:
                log.error(f"Deployment attempt {attempt + 1} failed: {str(e)}")
        
        log.error(f"Deployment failed after {self.retries} attempts")
        return False
    
    def get_deployment_status(self) -> dict:
        """Get current deployment status"""
        try:
            result = subprocess.run(
                "docker-compose ps",
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                return {
                    "status": "running",
                    "details": result.stdout
                }
            else:
                return {
                    "status": "error",
                    "details": result.stderr
                }
        except Exception as e:
            log.error(f"Failed to get deployment status: {str(e)}")
            return {"status": "unknown", "error": str(e)}
