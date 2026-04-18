import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from agent_skills import AgentSkillsToolset, SandboxExecutor, AgentSkill
    from code_sandboxes import EvalSandbox
except ImportError as e:
    print(f"Error: Missing dependencies - {e}")
    sys.exit(1)

def verify():
    skills_dir = Path("./skills").absolute()
    print(f"--- Skill Verification Diagnostic ---")
    print(f"Checking skills directory: {skills_dir}")
    
    if not skills_dir.exists():
        print(f"FAIL: {skills_dir} does not exist!")
        return

    # Check for SKILL.md files manually
    skill_files = list(skills_dir.rglob("SKILL.md"))
    print(f"Found {len(skill_files)} SKILL.md files:")
    for f in skill_files:
        print(f" - {f}")
        try:
            # Try to load each skill using the library's internal logic
            skill = AgentSkill.from_skill_md(f)
            print(f"   SUCCESS: Loaded skill '{skill.name}'")
            print(f"   - Scripts found: {[s.name for s in skill.scripts]}")
        except Exception as e:
            print(f"   FAIL: Could not load skill from {f}")
            print(f"   Error: {e}")

    # Test the Toolset discovery
    print("\nTesting AgentSkillsToolset discovery:")
    try:
        toolset = AgentSkillsToolset(
            directories=[str(skills_dir)],
            executor=SandboxExecutor(EvalSandbox())
        )
        # Access discovered skills
        discovered = toolset._discovered_skills
        print(f"Discovered {len(discovered)} skills via toolset: {list(discovered.keys())}")
        
        if len(discovered) == 0:
            print("WARNING: Toolset returned 0 skills even if files exist.")
    except Exception as e:
        print(f"Error initializing toolset: {e}")

if __name__ == "__main__":
    verify()
