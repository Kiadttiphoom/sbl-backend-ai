import sys
import os
from pathlib import Path
from agent_skills import AgentSkillsToolset, AgentSkill, SandboxExecutor
from code_sandboxes import EvalSandbox

def test():
    print("--- Manual Discovery Test ---")
    dir_path = Path("./skills").absolute()
    print(f"Directory: {dir_path}")
    
    discovered_skills = {}
    
    for f in dir_path.rglob("SKILL.md"):
        print(f"\nChecking file: {f}")
        try:
            skill = AgentSkill.from_skill_md(f)
            print(f"  Skill Name: {skill.name}")
            print(f"  Skill Description: {skill.description[:50]}...")
            print(f"  Scripts: {[s.name for s in skill.scripts]}")
            discovered_skills[skill.name] = skill
        except Exception as e:
            print(f"  FAILED to load: {type(e).__name__}: {e}")

    print(f"\nDiscovered: {list(discovered_skills.keys())}")
    
    # Now try the Toolset
    print("\n--- Toolset Initialization ---")
    try:
        toolset = AgentSkillsToolset(
            directories=[str(dir_path)],
            executor=SandboxExecutor(EvalSandbox())
        )
        print(f"Toolset _list_skills(): {toolset._list_skills()}")
        print(f"Toolset Discovered: {list(toolset._discovered_skills.keys())}")
    except Exception as e:
        print(f"Toolset Error: {e}")

if __name__ == "__main__":
    test()
