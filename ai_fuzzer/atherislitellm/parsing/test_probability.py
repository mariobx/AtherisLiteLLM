import ast
from typing import Dict, Set
from ai_fuzzer.atherislitellm.logger.logs import log, report_failure

class CodeContextAnalyzer(ast.NodeVisitor):
    """
    AST visitor that traverses a module to collect file-level test context 
    and assigns confidence scores to classes and functions.
    """
    def __init__(self):
        self.has_test_imports = False
        self.test_frameworks = {"pytest", "unittest", "mock", "hypothesis", "freezegun", "responses"}
        self.class_scores: Dict[str, float] = {}
        self.function_scores: Dict[str, float] = {}
        self.current_class = None

        self.test_prefixes = ("test_", "mock_", "dummy_")
        self.test_suffixes = ("_test", "_mock")
        self.test_decorators = {"fixture", "patch", "mock", "setup", "teardown", "pytest"}
        self.test_bases = {"TestCase", "IsolatedAsyncioTestCase"}
        self.test_framework_calls = {
            "assertEqual", "assertTrue", "assertFalse", "assertRaises", 
            "assertIsNone", "assertIn", "pytest.raises", "pytest.approx"
        }

    def visit_Module(self, node: ast.Module):
        # Scan for test imports to establish file-level context
        for child in ast.walk(node):
            if isinstance(child, ast.Import):
                for alias in child.names:
                    if any(fw in alias.name.lower() for fw in self.test_frameworks):
                        self.has_test_imports = True
            elif isinstance(child, ast.ImportFrom):
                if child.module and any(fw in child.module.lower() for fw in self.test_frameworks):
                    self.has_test_imports = True
        
        # Traverse the rest of the AST
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        score = 0.0
        
        if node.name.startswith("Test") or node.name.endswith("Test"):
            score += 0.4
            
        for base in node.bases:
            base_name = getattr(base, "id", getattr(base, "attr", ""))
            if base_name in self.test_bases:
                score = 1.0  # Absolute structural proof
        
        # Composition heuristics: analyze methods inside
        method_count = 0
        test_method_count = 0
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_count += 1
                if self._is_likely_test_method_name_or_body(item):
                    test_method_count += 1
                    
        if method_count > 0 and (test_method_count / method_count) >= 0.5:
            score = max(score, 1.0)
            
        self.class_scores[node.name] = score
        
        # Retain parent context for nested methods
        previous_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = previous_class

    def _is_likely_test_method_name_or_body(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        lower_name = node.name.lower()
        if lower_name.startswith(self.test_prefixes) or lower_name.endswith(self.test_suffixes):
            return True
        for dec in node.decorator_list:
            try:
                dec_name = getattr(dec, "id", getattr(getattr(dec, "func", None), "id", ""))
            except Exception as e:
                log(f"Error getting decorator name: {e}", level="ERROR", debug=True)
                continue
            if any(td in dec_name.lower() for td in self.test_decorators):
                return True
        return False

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._analyze_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._analyze_function(node)

    def _analyze_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        score = 0.0
        
        lower_name = node.name.lower()
        if lower_name.startswith(self.test_prefixes) or lower_name.endswith(self.test_suffixes):
            score += 0.5
        elif lower_name == "test":
            score += 0.6
            
        for dec in node.decorator_list:
            try:
                dec_name = getattr(dec, "id", getattr(getattr(dec, "func", None), "id", ""))
            except Exception as e:
                log(f"Error getting decorator name: {e}", level="ERROR", debug=True)
                continue
            if any(td in dec_name.lower() for td in self.test_decorators):
                score += 0.6

        raw_assert_count = 0
        framework_assert_count = 0
        mock_calls = 0
        total_statements = len(node.body)

        for child in ast.walk(node):
            if isinstance(child, ast.Assert):
                raw_assert_count += 1
            elif isinstance(child, ast.Call):
                if isinstance(child.func, ast.Attribute):
                    if child.func.attr in self.test_framework_calls:
                        framework_assert_count += 1
                elif isinstance(child.func, ast.Name):
                    if "mock" in child.func.id.lower() or child.func.id == "patch":
                        mock_calls += 1

        score += (framework_assert_count * 0.4)
        score += (mock_calls * 0.3)

        if total_statements > 0:
            assert_density = raw_assert_count / total_statements
            if assert_density > 0.3:
                score += 0.5
            elif raw_assert_count > 0:
                score += 0.1 * raw_assert_count

        if self.has_test_imports:
            score *= 1.5

        if self.current_class:
            try:
                if self.class_scores.get(self.current_class, 0.0) >= 0.4:
                    score *= 1.8
            except Exception as e:
                log(f"Error getting class score: {e}", level="ERROR", debug=True)

        self.function_scores[node.name] = min(1.0, score)
        self.generic_visit(node)

def calculate_test_probability(node: ast.AST, analyzer: CodeContextAnalyzer | None = None) -> float:
    """
    Evaluates an AST node (Function or Class) and returns a probability [0.0 - 1.0]
    that the node is test code rather than application logic.
    """
    if analyzer is not None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return analyzer.function_scores.get(node.name, 0.0)
        elif isinstance(node, ast.ClassDef):
            return analyzer.class_scores.get(node.name, 0.0)

    # Fallback to standalone analyzer if context is not pre-calculated
    analyzer_instance = CodeContextAnalyzer()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        analyzer_instance.visit(ast.Module(body=[node], type_ignores=[]))
        return analyzer_instance.function_scores.get(node.name, 0.0)
    elif isinstance(node, ast.ClassDef):
        analyzer_instance.visit(ast.Module(body=[node], type_ignores=[]))
        return analyzer_instance.class_scores.get(node.name, 0.0)
    
    return 0.0

def is_likely_test(node: ast.AST, threshold: float = 1.1, analyzer: CodeContextAnalyzer | None = None) -> bool:
    """Convenience function to check if a node crosses the probability threshold."""
    prob = calculate_test_probability(node, analyzer)
    obj_type = "Class" if isinstance(node, ast.ClassDef) else "Function"
    name = getattr(node, "name", "unknown")
    log(f"{obj_type} : {name} has test prob of {prob}", level="INFO")
    return prob >= threshold

