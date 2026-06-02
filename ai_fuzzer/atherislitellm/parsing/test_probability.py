import ast

# --- The Testing Corpus ---
TEST_PREFIXES = ("test_", "mock_", "dummy_")
TEST_SUFFIXES = ("_test", "_mock")
TEST_DECORATORS = {"fixture", "patch", "mock", "setup", "teardown", "pytest"}
TEST_BASES = {"TestCase", "IsolatedAsyncioTestCase"}
TEST_FRAMEWORK_CALLS = ("assertEqual", "assertTrue", "assertFalse", "assertRaises", 
                        "assertIsNone", "assertIn", "pytest.raises", "pytest.approx")

def _calculate_function_probability(node: ast.FunctionDef | ast.AsyncFunctionDef) -> float:
    """Calculates the probability that a function is a unit test."""
    score = 0.0

    # 1. Name Heuristics
    lower_name = node.name.lower()
    if lower_name.startswith(TEST_PREFIXES) or lower_name.endswith(TEST_SUFFIXES):
        score += 0.5
    elif lower_name == "test":
        score += 0.6

    # 2. Decorator Heuristics
    for decorator in node.decorator_list:
        dec_name = ""
        if isinstance(decorator, ast.Name):
            dec_name = decorator.id
        elif isinstance(decorator, ast.Attribute):
            dec_name = decorator.attr
        elif isinstance(decorator, ast.Call):
            if isinstance(decorator.func, ast.Name):
                dec_name = decorator.func.id
            elif isinstance(decorator.func, ast.Attribute):
                dec_name = decorator.func.attr
        
        if any(td in dec_name.lower() for td in TEST_DECORATORS):
            score += 0.6

    # 3. Body Introspection (Assertions & Density)
    raw_assert_count = 0
    framework_assert_count = 0
    mock_calls = 0
    total_statements = len(node.body)

    for child in ast.walk(node):
        # Catch raw 'assert x == y'
        if isinstance(child, ast.Assert):
            raw_assert_count += 1
        
        # Catch framework calls like 'self.assertEqual()' or 'MagicMock()'
        elif isinstance(child, ast.Call):
            if isinstance(child.func, ast.Attribute):
                if child.func.attr in TEST_FRAMEWORK_CALLS:
                    framework_assert_count += 1
            elif isinstance(child.func, ast.Name):
                if "mock" in child.func.id.lower() or child.func.id == "patch":
                    mock_calls += 1

    # Apply Weights
    score += (framework_assert_count * 0.4) # Framework asserts are strong indicators
    score += (mock_calls * 0.3)             # Mocking is a strong indicator

    # Handle raw asserts safely using density
    if total_statements > 0:
        assert_density = raw_assert_count / total_statements
        if assert_density > 0.3:
            # High density of asserts (more than 30% of lines) -> likely a test
            score += 0.5
        elif raw_assert_count > 0:
            # Low density -> likely defensive programming -> very low weight
            score += 0.1 * raw_assert_count

    return min(1.0, score)

def _calculate_class_probability(node: ast.ClassDef) -> float:
    """Calculates the probability that a class is a test suite."""
    score = 0.0

    # 1. Name Heuristics
    if node.name.startswith("Test") or node.name.endswith("Test"):
        score += 0.4

    # 2. Inheritance Heuristics (e.g., inherits from unittest.TestCase)
    for base in node.bases:
        base_name = ""
        if isinstance(base, ast.Name):
            base_name = base.id
        elif isinstance(base, ast.Attribute):
            base_name = base.attr
        
        if base_name in TEST_BASES:
            return 1.0 # Absolute certainty

    # 3. Composition Heuristics (Does it contain test functions?)
    method_count = 0
    test_method_count = 0
    
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            method_count += 1
            method_prob = _calculate_function_probability(item)
            if method_prob >= 0.7:
                test_method_count += 1

    if method_count > 0:
        test_method_ratio = test_method_count / method_count
        if test_method_ratio >= 0.5:
            score += 0.6 # If half its methods are tests, the class is a test suite

    return min(1.0, score)

def calculate_test_probability(node: ast.AST) -> float:
    """
    Evaluates an AST node (Function or Class) and returns a probability [0.0 - 1.0] 
    that the node is test code rather than application logic.
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _calculate_function_probability(node)
    elif isinstance(node, ast.ClassDef):
        return _calculate_class_probability(node)
    
    return 0.0

def is_likely_test(node: ast.AST, threshold: float = 0.7) -> bool:
    """Convenience function to check if a node crosses the probability threshold."""
    return calculate_test_probability(node) >= threshold
