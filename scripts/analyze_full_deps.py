import os
import json
import ast
import re
from pathlib import Path

# Configuration
ROOT_DIR = Path(r"c:/Users/SASINDU/Desktop/IRWA Group Repo/dynamic-pricing-ai-IRWA_PROJECT")
OUTPUT_FILE = ROOT_DIR / "codebase_graph_data.json"

# Exclusions
EXCLUDE_DIRS = {
    "node_modules", "__pycache__", ".git", ".vscode", "dist", "build", ".venv",
    "scripts", "tests", "ai_commit", "docs", "loadtests", "loc_reports", ".hypothesis",
    ".llm_cache", ".pytest_cache", ".recycle_bin", "coverage"
}
EXCLUDE_FILES = {
    ".env", ".env.example", ".gitignore", "package-lock.json", "yarn.lock",
    "requirements.txt", "pytest.ini", "README.md", "LICENSE", "poetry.lock"
}
EXCLUDE_EXTENSIONS = {
    ".pyc", ".pyd", ".obj", ".o", ".a", ".lib", ".dll", ".so", ".exe", ".bin",
    ".min.js", ".min.css", ".map", ".log", ".txt", ".bat", ".ini", ".db", ".db.old",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".json", ".md", ".html", ".css"
}

# Regex for JS/TS imports
# Matches: import ... from '...'; or import '...'; or const ... = require('...');
TS_IMPORT_RE = re.compile(r"""(?:import\s+(?:[\w\s{},*]+)\s+from\s+['"]([^'"]+)['"])|(?:import\s+['"]([^'"]+)['"])|(?:require\s*\(\s*['"]([^'"]+)['"]\s*\))""")

def should_exclude(path: Path):
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return True
    if path.name in EXCLUDE_FILES:
        return True
    if path.suffix in EXCLUDE_EXTENSIONS:
        return True
    if path.name.startswith("."):
        return True
    return False

def get_all_files(root_dir):
    files = []
    for root, dirs, filenames in os.walk(root_dir):
        # Modify dirs in-place to skip excluded directories
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]
        
        for filename in filenames:
            file_path = Path(root) / filename
            if not should_exclude(file_path):
                files.append(file_path)
    return files

def resolve_python_import(import_name, current_file_path, root_dir):
    """
    Resolves a Python import to a file path.
    Handles absolute imports (from root) and relative imports.
    """
    # 1. Try as relative path first if it starts with .
    # But ast gives module names "foo.bar", not paths.
    # Relative imports in AST have 'level' > 0.
    
    # This function will be called with the module name derived from AST
    # For "from . import utils", import_name="utils", level=1
    # For "import core.settings", import_name="core.settings", level=0
    
    # We'll handle logic inside parse_python_file mostly, but here we check existence
    
    potential_paths = []
    
    # Convert dot notation to path
    path_parts = import_name.split('.')
    
    # Try as a file
    potential_paths.append(root_dir.joinpath(*path_parts).with_suffix('.py'))
    # Try as a package (init.py)
    potential_paths.append(root_dir.joinpath(*path_parts) / "__init__.py")
    
    for p in potential_paths:
        if p.exists() and p.is_file():
            return p
            
    return None

def resolve_ts_import(import_path, current_file_path, root_dir):
    """
    Resolves a TS/JS import path.
    """
    if import_path.startswith('.'):
        # Relative path
        resolved = (current_file_path.parent / import_path).resolve()
    elif import_path.startswith('@/'):
        # Alias (assuming @ maps to src or frontend/src usually, but let's try to guess or just use root)
        # In this project, frontend/src seems to be the root for frontend code
        # Let's try resolving from frontend/src if it exists
        frontend_src = root_dir / "frontend" / "src"
        if frontend_src.exists():
             resolved = (frontend_src / import_path[2:]).resolve()
        else:
             resolved = (root_dir / import_path[2:]).resolve()
    else:
        # Likely a node_module or absolute path (which we ignore for now unless it matches a file)
        return None

    # Try extensions
    extensions = ['.ts', '.tsx', '.js', '.jsx', '.d.ts', '']
    for ext in extensions:
        candidate = resolved.with_suffix(resolved.suffix + ext)
        if candidate.exists() and candidate.is_file():
            return candidate
        # Also try index files
        candidate_index = resolved / f"index{ext}"
        if candidate_index.exists() and candidate_index.is_file():
            return candidate_index
            
    return None

def parse_python_imports(file_path, root_dir):
    imports = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))
            
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = resolve_python_import(alias.name, file_path, root_dir)
                    if target:
                        imports.append({"target": str(target.relative_to(root_dir)), "type": "import", "symbols": [alias.name]})
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    # Absolute or relative with module specified
                    # e.g. from core.settings import ... -> module="core.settings"
                    # e.g. from .utils import ... -> module="utils", level=1 (handled by logic below)
                    
                    module_name = node.module
                    if node.level > 0:
                        # Relative import logic is tricky with just module name
                        # We'll simplify: resolve relative to current file
                        # This is a heuristic
                        pass 
                    
                    target = resolve_python_import(module_name, file_path, root_dir)
                    if target:
                         symbols = [n.name for n in node.names]
                         imports.append({"target": str(target.relative_to(root_dir)), "type": "from_import", "symbols": symbols})
                else:
                    # from . import foo
                    if node.level > 0:
                        # Relative import without module
                        # e.g. from . import auth
                        for alias in node.names:
                            # Construct path relative to current file
                            # level 1 = ., level 2 = ..
                            parent = file_path.parent
                            for _ in range(node.level - 1):
                                parent = parent.parent
                            
                            target = resolve_python_import(alias.name, parent / "placeholder", parent) # Hacky usage of resolve
                            if target:
                                imports.append({"target": str(target.relative_to(root_dir)), "type": "relative_import", "symbols": [alias.name]})

    except Exception as e:
        # print(f"Error parsing {file_path}: {e}")
        pass
    return imports

def parse_ts_imports(file_path, root_dir):
    imports = []
    try:
        content = file_path.read_text(encoding="utf-8")
        matches = TS_IMPORT_RE.findall(content)
        for match in matches:
            # match is tuple of groups, take the first non-empty one
            import_path = next((m for m in match if m), None)
            if import_path:
                target = resolve_ts_import(import_path, file_path, root_dir)
                if target and not should_exclude(target):
                     try:
                        rel_target = str(target.relative_to(root_dir))
                        imports.append({"target": rel_target, "type": "import", "symbols": [import_path]}) # Regex doesn't easily capture symbols without complex parsing
                     except ValueError:
                         pass # Target is outside root (shouldn't happen with resolve logic but safety first)
    except Exception as e:
        pass
    return imports

def main():
    print("Scanning files...")
    all_files = get_all_files(ROOT_DIR)
    print(f"Found {len(all_files)} files.")
    
    nodes = []
    links = []
    
    file_map = {str(f.relative_to(ROOT_DIR)): i for i, f in enumerate(all_files)}
    
    for i, file_path in enumerate(all_files):
        rel_path = str(file_path.relative_to(ROOT_DIR))
        size = file_path.stat().st_size
        
        # Determine group
        if "frontend" in rel_path:
            group = "frontend"
        elif "backend" in rel_path:
            group = "backend"
        elif "core" in rel_path:
            group = "core"
        else:
            group = "other"
            
        nodes.append({
            "id": rel_path,
            "group": group,
            "size": size,
            "name": file_path.name
        })
        
        # Parse imports
        file_imports = []
        if file_path.suffix == ".py":
            file_imports = parse_python_imports(file_path, ROOT_DIR)
        elif file_path.suffix in [".ts", ".tsx", ".js", ".jsx"]:
            file_imports = parse_ts_imports(file_path, ROOT_DIR)
            
        for imp in file_imports:
            target = imp["target"]
            if target in file_map:
                links.append({
                    "source": rel_path,
                    "target": target,
                    "type": imp["type"],
                    "symbols": imp["symbols"]
                })
    
    graph_data = {"nodes": nodes, "links": links}
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(graph_data, f, indent=2)
        
    print(f"Graph data saved to {OUTPUT_FILE}")
    print(f"Nodes: {len(nodes)}, Links: {len(links)}")

if __name__ == "__main__":
    main()
