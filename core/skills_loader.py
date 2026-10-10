import importlib
import pkgutil

import skills as skills_pkg


def load_skills():
    """Return {skill_name: {"metadata": dict, "run": callable}}."""
    registry = {}
    for module_info in pkgutil.iter_modules(skills_pkg.__path__):
        if module_info.name.startswith("_"):
            continue  # skip __init__ and private files
        try:
            module = importlib.import_module(f"skills.{module_info.name}")
            meta = module.SKILL_METADATA
            run = module.run
        except Exception as e:
            print(f"[skills] skipped '{module_info.name}': {e}")
            continue
        if not isinstance(meta, dict) or "name" not in meta or not callable(run):
            print(f"[skills] skipped '{module_info.name}': bad metadata or run()")
            continue
        registry[meta["name"]] = {"metadata": meta, "run": run}
    return registry


def get_skill_declarations():
    """Metadata of all skills, for merging into TOOL_DECLARATIONS."""
    return [s["metadata"] for s in load_skills().values()]