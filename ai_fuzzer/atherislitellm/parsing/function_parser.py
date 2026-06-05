import os
import ast
from typing import List
from pathlib import Path
from ai_fuzzer.atherislitellm.logger.logs import log
from ai_fuzzer.atherislitellm.parsing.test_probability import CodeContextAnalyzer, is_likely_test

def is_virtualenv_dir(path, debug=False):
    """Returns True if the given directory looks like a Python virtual environment."""
    pyvenv_cfg = os.path.join(path, "pyvenv.cfg")
    bin_python = os.path.join(path, "bin", "python")
    scripts_python = os.path.join(path, "Scripts", "python.exe")
    if os.path.isfile(pyvenv_cfg):
        if os.path.isfile(bin_python) or os.path.isfile(scripts_python):
            log(f"Ignoring virtualenv at {path}", level="DEBUG", debug=debug)
            return True
    return False

def get_python_file_paths(directory_path, debug=False):
    """Recursively get .py files, skipping virtual environments."""
    log(f"Walking directory: {directory_path}", level="DEBUG", debug=debug)
    python_files: List[str] = []
    try:
        for root, dirs, files in os.walk(directory_path):
            dirs[:] = [
                d for d in dirs 
                if d.lower() not in {"test", "docs"} and not is_virtualenv_dir(os.path.join(root, d), debug)
            ]
            for file in files:
                if file.endswith(".py"):
                    full_path = os.path.join(root, file)
                    python_files.append(full_path)
                    log(f"Found: {full_path}", level="DEBUG", debug=debug)
    except PermissionError as e:
        log(f"Permission denied accessing {directory_path}: {e}", level="ERROR")
    except Exception as e:
        log(f"Error walking directory {directory_path}: {e}", level="ERROR")
        
    return python_files

def extract_functions(path: str | Path, debug=False, test_threshold: float = 1.1) -> dict[str, str]:
    """Parses a Python file and extracts top-level functions."""
    path = Path(path)
    if not path.is_file():
        return {}

    try:
        source_code = path.read_text(encoding="utf-8")
        tree = ast.parse(source_code, filename=str(path))
    except SyntaxError as e:
        log(f"Syntax error in {path.name}: {e}", level="ERROR")
        return {}
    except Exception as e:
        log(f"Failed to parse {path.name}: {e}", level="ERROR")
        return {}

    analyzer = CodeContextAnalyzer()
    analyzer.visit(tree)

    functions = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if is_likely_test(node, threshold=test_threshold, analyzer=analyzer):
                continue
            source = ast.get_source_segment(source_code, node)
            if source:
                functions[node.name] = source

    log(f"Extracted {len(functions)} functions from {path.name}", level="DEBUG", debug=debug)
    return functions

def extract_classes(path: str | Path, debug=False, test_threshold: float = 1.1):
    """Parses a Python file and extracts classes and their methods."""
    path = Path(path)
    if not path.is_file():
        return {}, {}

    try:
        source_code = path.read_text(encoding="utf-8")
        tree = ast.parse(source_code)
    except SyntaxError as e:
        log(f"Syntax error in {path.name}: {e}", level="ERROR")
        return {}, {}
    except Exception as e:
        log(f"Failed to parse {path.name}: {e}", level="ERROR")
        return {}, {}

    analyzer = CodeContextAnalyzer()
    analyzer.visit(tree)

    classes_in_file = {}
    functions_inside_classes = {}

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if is_likely_test(node, threshold=test_threshold, analyzer=analyzer):
                continue
            cls_name = node.name
            cls_body = ast.get_source_segment(source_code, node)
            classes_in_file[cls_name] = cls_body
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if is_likely_test(item, threshold=test_threshold, analyzer=analyzer):
                        continue
                    method_source = ast.get_source_segment(source_code, item)
                    methods.append((item.name, method_source))
            
            functions_inside_classes[cls_name] = methods

    log(f"Extracted {len(classes_in_file)} classes from {path.name}", level="DEBUG", debug=debug)
    return classes_in_file, functions_inside_classes
