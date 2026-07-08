"""Git Manager - Repository management for Amoscloud AI"""

import logging
from typing import Dict, List, Optional, Any
from git import Repo, GitCommandError

logger = logging.getLogger(__name__)


class GitManager:
    """Manage Git operations and repository interactions"""
    
    def __init__(self, repo_url: str, github_token: Optional[str] = None):
        self.repo_url = repo_url
        self.github_token = github_token
        self.local_repo = None
    
    def clone_repository(self, target_path: str) -> bool:
        try:
            logger.info(f"Cloning repository to {target_path}")
            self.local_repo = Repo.clone_from(self.repo_url, target_path)
            logger.info("Repository cloned successfully")
            return True
        except GitCommandError as e:
            logger.error(f"Failed to clone repository: {str(e)}")
            return False
    
    def create_branch(self, branch_name: str, base_branch: str = "main") -> bool:
        try:
            if not self.local_repo:
                logger.error("Repository not initialized")
                return False
            self.local_repo.create_head(branch_name, base_branch)
            logger.info(f"Branch '{branch_name}' created successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to create branch: {str(e)}")
            return False
    
    def commit_changes(self, message: str, files: Optional[List[str]] = None) -> bool:
        try:
            if not self.local_repo:
                logger.error("Repository not initialized")
                return False
            if files:
                self.local_repo.index.add(files)
            else:
                self.local_repo.index.add(self.local_repo.untracked_files)
            self.local_repo.index.commit(message)
            logger.info(f"Changes committed: {message}")
            return True
        except Exception as e:
            logger.error(f"Failed to commit changes: {str(e)}")
            return False
    
    def push_changes(self, branch: str = "main") -> bool:
        try:
            if not self.local_repo:
                logger.error("Repository not initialized")
                return False
            self.local_repo.remotes.origin.push(branch)
            logger.info(f"Pushed changes to {branch}")
            return True
        except Exception as e:
            logger.error(f"Failed to push changes: {str(e)}")
            return False
