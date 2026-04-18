from typing import Dict, Callable, Any
import logging

logger = logging.getLogger(__name__)

# Registry for all available AI skills
# This replaces the scattered dynamic loading with a strict, controlled map.

import importlib.util
import sys
import os

def load_module_by_path(module_name: str, file_path: str):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module

base_dir = os.path.dirname(os.path.abspath(__file__))
search_data_path = os.path.join(base_dir, "search-data", "scripts", "script.py")
analyze_report_path = os.path.join(base_dir, "analyze-report", "scripts", "script.py")

search_data_script = load_module_by_path("search_data_script", search_data_path)
try:
    analyze_report_script = load_module_by_path("analyze_report_script", analyze_report_path)
except Exception as e:
    logger.warning(f"Failed to load analyze-report script: {e}")
    analyze_report_script = None

SKILLS: Dict[str, Callable[[str], Any]] = {
    "search-data": search_data_script.run,
    "analyze-report": analyze_report_script.run if (analyze_report_script and hasattr(analyze_report_script, 'run')) else lambda x: "Skill not fully implemented."
}

def execute_skill(skill_name: str, args: str) -> Any:
    """Executes a skill from the registry. Returns the result."""
    if skill_name not in SKILLS:
        raise ValueError(f"Skill '{skill_name}' not found in registry.")
    
    logger.info(f"Executing skill: {skill_name} with args: {args}")
    try:
        return SKILLS[skill_name](args)
    except Exception as e:
        logger.error(f"Error executing skill {skill_name}: {e}")
        return f"Error executing skill: {str(e)}"
