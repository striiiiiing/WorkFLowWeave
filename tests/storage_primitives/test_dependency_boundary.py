import ast
from pathlib import Path


def test_storage_primitives_do_not_import_business_orchestration():
    package = Path(__file__).parents[2] / "src" / "workflowweave" / "storage_primitives"
    imported_roots = set()
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(
                    alias.name.split(".")[1]
                    for alias in node.names
                    if alias.name.startswith("workflowweave.")
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("workflowweave."):
                    imported_roots.add(node.module.split(".")[1])

    assert not imported_roots.intersection({"agent", "workflow"})
