import ast
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "lk47"

# the harness packages plus its run module, which the live runner drives, and the harness's
# browser library, through which the Verified runner records the network trace
ALLOWED = {
    "lk47",
    "lxml",
    "cssselect",
    "browser_env",
    "agent",
    "evaluation_harness",
    "run",
    "playwright",
}


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_agent_package_imports_only_the_allowlist() -> None:
    offenders: dict[str, set[str]] = {}
    for path in PACKAGE.rglob("*.py"):
        extra = {
            n
            for n in _top_level_imports(path)
            if n not in ALLOWED and n not in sys.stdlib_module_names
        }
        if extra:
            offenders[str(path.relative_to(PACKAGE))] = extra
    assert not offenders, offenders


def test_agent_never_opens_its_config_file() -> None:
    source = (PACKAGE / "agent.py").read_text()
    tree = ast.parse(source)
    opened = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open"
    ]
    assert not opened, f"open() called in agent.py at lines {opened}"
    assert "json" not in _top_level_imports(PACKAGE / "agent.py")
