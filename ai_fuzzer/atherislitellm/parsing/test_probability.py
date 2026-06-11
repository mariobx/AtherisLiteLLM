import ast
from ai_fuzzer.atherislitellm.logger.logs import log

class TestCodeClassifier(ast.NodeVisitor):
    """
    A sophisticated static analysis engine designed to evaluate raw strings of Python 
    code and heuristically determine if the code represents testing artifacts.
    
    This class utilizes the standard library's ast module to traverse the Abstract 
    Syntax Tree without executing the code. It calculates a normalized heuristic 
    score based on testing framework signatures (unittest, pytest), decorators, 
    imports, and assertions.
    """

    # Empirical Heuristic Weights
    WEIGHT_TESTCASE_INHERITANCE = 1.0
    WEIGHT_TEST_NAMING_CONVENTION = 0.8
    WEIGHT_TEST_DECORATOR = 0.8
    WEIGHT_TEST_IMPORT = 0.6
    WEIGHT_MOCK_USAGE = 0.6
    WEIGHT_ASSERTION_PRESENCE = 0.4

    # Topologically significant testing signatures
    TEST_DECORATORS = {'fixture', 'patch', 'parametrize', 'mock', 'mark'}
    TEST_IMPORTS = {'pytest', 'unittest', 'mock', 'magicmock', 'patch', 'nose'}
    MOCK_OBJECTS = {'MagicMock', 'Mock', 'AsyncMock', 'patch'}

    def __init__(self):
        super().__init__()
        self.score = 0.0
        self.total_nodes = 0
        self.assert_count = 0

    def _add_score(self, weight: float, reason: str):
        """Accumulates the heuristic score and emits telemetry for the pipeline."""
        self.score += weight
        log(f"Test Classifier Evidence: {weight} - {reason}")

    def _extract_name(self, node: ast.AST) -> str:
        """
        Recursively extracts the string identifier from AST Name, Attribute, 
        and Call nodes. Critical for unrolling complex decorators and base classes.
        """
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        elif isinstance(node, ast.Call):
            # Recursively unwrap the function being called
            return self._extract_name(node.func)
        return ""

    def visit_ClassDef(self, node: ast.ClassDef):
        """Analyzes class definitions for framework inheritance and naming conventions."""
        self.total_nodes += 1
        
        # 1. Evaluate pytest naming convention (starts with 'Test')
        if node.name.startswith("Test"):
            # Pytest dictates that test classes must lack an __init__ constructor
            has_init = any(
                isinstance(child, ast.FunctionDef) and child.name == "__init__" 
                for child in node.body
            )
            if not has_init:
                self._add_score(
                    self.WEIGHT_TEST_NAMING_CONVENTION, 
                    f"Class '{node.name}' matches pytest convention without __init__."
                )

        # 2. Evaluate unittest.TestCase inheritance models
        for base in node.bases:
            base_name = self._extract_name(base)
            if base_name == "TestCase":
                self._add_score(
                    self.WEIGHT_TESTCASE_INHERITANCE, 
                    f"Class '{node.name}' inherits directly or via module from TestCase."
                )

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Analyzes function definitions for lexical conventions and framework decorators."""
        self.total_nodes += 1

        # 1. Evaluate pytest/unittest functional naming conventions
        if node.name.startswith("test_") or node.name.endswith("_test"):
            self._add_score(
                self.WEIGHT_TEST_NAMING_CONVENTION, 
                f"Function '{node.name}' matches standard test naming convention."
            )

        # 2. Extract and deeply analyze the decorator list
        for decorator in node.decorator_list:
            dec_name = self._extract_name(decorator).lower()
            if any(test_dec in dec_name for test_dec in self.TEST_DECORATORS):
                self._add_score(
                    self.WEIGHT_TEST_DECORATOR, 
                    f"Function '{node.name}' utilizes framework decorator '@{dec_name}'."
                )

        self.generic_visit(node)
        
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Processes asynchronous functions identically to standard synchronous functions."""
        self.visit_FunctionDef(node)

    def visit_Import(self, node: ast.Import):
        """Analyzes standard imports for testing framework dependencies."""
        self.total_nodes += 1
        for alias in node.names:
            if alias.name.lower() in self.TEST_IMPORTS:
                self._add_score(
                    self.WEIGHT_TEST_IMPORT, 
                    f"Explicit module import of testing framework: '{alias.name}'."
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Analyzes specific 'from X import Y' statements for testing dependencies."""
        self.total_nodes += 1
        if node.module and node.module.lower() in self.TEST_IMPORTS:
            self._add_score(
                self.WEIGHT_TEST_IMPORT, 
                f"Explicit import directed from testing framework: '{node.module}'."
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        """Analyzes function calls to detect state isolation via mock objects."""
        self.total_nodes += 1
        call_name = self._extract_name(node)
        if call_name in self.MOCK_OBJECTS:
            self._add_score(
                self.WEIGHT_MOCK_USAGE, 
                f"Detected mock object instantiation or framework patch: '{call_name}'."
            )
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert):
        """Tracks the frequency of assert statements to determine structural density."""
        self.total_nodes += 1
        self.assert_count += 1
        self.generic_visit(node)


def is_test_code(code_string: str | ast.AST, threshold: float = 1.1) -> bool:
    """
    Evaluates a string of Python code to determine if it is a testing artifact.
    Designed specifically to prevent LLM token waste in generative fuzzing pipelines.

    Args:
        code_string (str): The raw string of Python source code to analyze.
        threshold (float): The heuristic confidence threshold (0.0 to 1.0). 
                           If threshold < 0 or > 1, the filter is completely bypassed (off mode).

    Returns:
        bool: True if the code is classified as a test, False otherwise.
    """
    # Bypass evaluation entirely if threshold is out of mathematical bounds
    if threshold < 0.0 or threshold > 1.0:
        return False
        
    # evaluation for empty strings to prevent parser overhead
    if isinstance(code_string, str) and (not code_string or not code_string.strip()):
        return False

    try:
        # Parse the raw string into an Abstract Syntax Tree via ASDL grammar rules
        tree = ast.parse(code_string) if isinstance(code_string, str) else code_string
    except SyntaxError as e:
        log(f"SyntaxError encountered while parsing code string: {e}. Defaulting to False.")
        return False

    # Instantiate the visitor and traverse the AST nodes
    classifier = TestCodeClassifier()
    classifier.visit(tree)

    # Calculate assertion density impact algorithmically
    # A single assert in a small snippet gets partial weight; high density yields full weight.
    if classifier.assert_count > 0:
        if classifier.total_nodes > 0:
            density = classifier.assert_count / classifier.total_nodes
            # If assertions constitute more than 10% of the operational nodes, apply full weight
            if density > 0.10:
                classifier._add_score(
                    TestCodeClassifier.WEIGHT_ASSERTION_PRESENCE, 
                    "High assertion density detected."
                )
            else:
                # Proportional mathematical weight for lower density distributions
                classifier._add_score(
                    TestCodeClassifier.WEIGHT_ASSERTION_PRESENCE * (density * 10), 
                    "Minor assertion presence."
                )

    # Normalize the final score to a bounded maximum of 1.0
    normalized_score = min(1.0, classifier.score)
    
    log(f"Final normalized heuristic score: {normalized_score} (Threshold: {threshold})")

    # Evaluate against the configurable parameter
    return normalized_score >= threshold