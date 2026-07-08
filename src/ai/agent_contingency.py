"""AI Agent Contingency - Fallback and recovery mechanisms for AI agents"""

import logging
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
from datetime import datetime, timedelta

from src.ownership import get_ownership_profile

logger = logging.getLogger(__name__)


class ContingencyLevel(Enum):
    """Contingency severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ContingencyAction(Enum):
    """Available contingency actions"""
    RETRY = "retry"
    FALLBACK = "fallback"
    ESCALATE = "escalate"
    PAUSE = "pause"
    ROLLBACK = "rollback"
    ALERT = "alert"


class AIAgentContingency:
    """Handle AI agent contingencies and recovery"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.fallback_handlers = {}
        self.recovery_strategies = {}
        self.contingency_history = []
        self.owner_profile = get_ownership_profile()
        self.max_retries = config.get("max_retries", 3)
        self.retry_delay = config.get("retry_delay", 5)
    
    def register_fallback(self, error_type: str, handler: Callable) -> None:
        """Register a fallback handler for specific error type"""
        self.fallback_handlers[error_type] = handler
        logger.info(f"Registered fallback handler for {error_type}")
    
    def register_recovery_strategy(self, strategy_name: str, strategy: Callable) -> None:
        """Register a recovery strategy"""
        self.recovery_strategies[strategy_name] = strategy
        logger.info(f"Registered recovery strategy: {strategy_name}")
    
    async def handle_contingency(
        self,
        error: Exception,
        context: Dict[str, Any],
        level: ContingencyLevel = ContingencyLevel.MEDIUM
    ) -> bool:
        """Handle a contingency event"""
        try:
            logger.warning(f"Contingency triggered: {str(error)} (Level: {level.value})")
            
            error_type = type(error).__name__
            
            # Log the contingency event
            self._log_contingency(error_type, level, context)
            
            # Try fallback handler
            if error_type in self.fallback_handlers:
                handler = self.fallback_handlers[error_type]
                if await self._execute_handler(handler, context):
                    logger.info(f"Fallback handler succeeded for {error_type}")
                    return True
            
            # Determine action based on level
            action = self._determine_action(level, error_type)
            
            # Execute contingency action
            return await self._execute_action(action, context, error)
            
        except Exception as e:
            logger.error(f"Contingency handling failed: {str(e)}")
            return False
    
    def _determine_action(self, level: ContingencyLevel, error_type: str) -> ContingencyAction:
        """Determine appropriate action based on contingency level"""
        if level == ContingencyLevel.CRITICAL:
            return ContingencyAction.ESCALATE
        elif level == ContingencyLevel.HIGH:
            return ContingencyAction.ROLLBACK
        elif level == ContingencyLevel.MEDIUM:
            return ContingencyAction.RETRY
        else:
            return ContingencyAction.FALLBACK
    
    async def _execute_action(
        self,
        action: ContingencyAction,
        context: Dict[str, Any],
        error: Exception
    ) -> bool:
        """Execute contingency action"""
        try:
            if action == ContingencyAction.RETRY:
                return await self._retry_operation(context)
            elif action == ContingencyAction.FALLBACK:
                return await self._fallback_operation(context)
            elif action == ContingencyAction.ESCALATE:
                return await self._escalate_issue(context, error)
            elif action == ContingencyAction.ROLLBACK:
                return await self._rollback_operation(context)
            elif action == ContingencyAction.PAUSE:
                return await self._pause_operation(context)
            elif action == ContingencyAction.ALERT:
                return await self._send_alert(context, error)
            else:
                return False
        except Exception as e:
            logger.error(f"Action execution failed: {str(e)}")
            return False
    
    async def _retry_operation(self, context: Dict[str, Any]) -> bool:
        """Retry the failed operation"""
        logger.info("Retrying operation...")
        return True
    
    async def _fallback_operation(self, context: Dict[str, Any]) -> bool:
        """Execute fallback operation"""
        logger.info("Executing fallback operation...")
        return True
    
    async def _escalate_issue(self, context: Dict[str, Any], error: Exception) -> bool:
        """Escalate issue to higher level"""
        logger.critical(f"Escalating issue: {str(error)}")
        return True
    
    async def _rollback_operation(self, context: Dict[str, Any]) -> bool:
        """Rollback failed operation"""
        logger.warning("Rolling back operation...")
        return True
    
    async def _pause_operation(self, context: Dict[str, Any]) -> bool:
        """Pause operation temporarily"""
        logger.info("Pausing operation...")
        return True
    
    async def _send_alert(self, context: Dict[str, Any], error: Exception) -> bool:
        """Send alert notification"""
        logger.info(f"Sending alert: {str(error)}")
        return True
    
    async def _execute_handler(self, handler: Callable, context: Dict[str, Any]) -> bool:
        """Execute fallback handler"""
        try:
            return await handler(context)
        except Exception as e:
            logger.error(f"Handler execution failed: {str(e)}")
            return False
    
    def _log_contingency(
        self,
        error_type: str,
        level: ContingencyLevel,
        context: Dict[str, Any]
    ) -> None:
        """Log contingency event"""
        event = {
            "timestamp": datetime.now(),
            "error_type": error_type,
            "level": level.value,
            "context": context
        }
        self.contingency_history.append(event)
    
    def get_contingency_report(self) -> Dict[str, Any]:
        """Get contingency report"""
        return {
            "owner": self.owner_profile["owner"],
            "ownership": self.owner_profile,
            "total_events": len(self.contingency_history),
            "events": self.contingency_history,
            "registered_handlers": list(self.fallback_handlers.keys()),
            "recovery_strategies": list(self.recovery_strategies.keys())
        }
