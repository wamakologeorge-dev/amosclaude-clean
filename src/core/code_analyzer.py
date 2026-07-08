"""Code Analyzer - Intelligent code analysis and modification"""

import logging
import ast
from typing import Dict, List, Optional, Any
from pathlib import Path

from src.ownership import get_ownership_profile

logger = logging.getLogger(__name__)


class CodeAnalyzer:
    """Analyze and understand code structure"""
    
    def __init__(self):
        self.analysis_results = {}
        self.owner_profile = get_ownership_profile()
    
    def analyze_file(self, file_path: str) -> Dict[str, Any]:
        try:
            path = Path(file_path)
            if not path.exists():
                logger.error(f"File not found: {file_path}")
                return {}
            
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if file_path.endswith('.py'):
                return self._analyze_python(content, file_path)
            
            logger.warning(f"Unsupported file type: {file_path}")
            return {}
            
        except Exception as e:
            logger.error(f"Failed to analyze file: {str(e)}")
            return {}
    
    def _analyze_python(self, content: str, file_path: str) -> Dict[str, Any]:
        try:
            tree = ast.parse(content)
            analysis = {
                "file": file_path,
                "owner": self.owner_profile["owner"],
                "lines": len(content.split('\n')),
                "functions": [],
                "classes": [],
                "imports": [],
                "complexity": self._calculate_complexity(tree),
            }
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    analysis["functions"].append(node.name)
                elif isinstance(node, ast.ClassDef):
                    analysis["classes"].append(node.name)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    analysis["imports"].append(ast.unparse(node))
            
            logger.info(f"Analyzed Python file: {file_path}")
            return analysis
            
        except Exception as e:
            logger.error(f"Python analysis failed: {str(e)}")
            return {}
    
    def _calculate_complexity(self, tree: ast.AST) -> int:
        complexity = 1
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
        return complexity
    
    def analyze_directory(self, dir_path: str) -> Dict[str, List[Dict[str, Any]]]:
        results = {}
        path = Path(dir_path)
        
        for file_path in path.rglob('*'):
            if file_path.is_file():
                results[str(file_path)] = self.analyze_file(str(file_path))
        
        return results
