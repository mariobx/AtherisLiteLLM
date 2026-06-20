import sys
import traceback
import inspect
from pathlib import Path
from datetime import datetime

_ORIGINAL_STDOUT = sys.stdout
_ORIGINAL_STDERR = sys.stderr

_LOG_FILE: Path | None = None

def init_logger(output_dir: Path) -> None:
    """Set up the log directory and log file under the given base path."""
    global _LOG_FILE
    log_dir = output_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _LOG_FILE = log_dir / "log.log"

def log(msg: str, level: str = "INFO", debug: bool = False) -> None:
    """Log a message with a level (INFO, DEBUG, ERROR)."""
    if _LOG_FILE is None:
        ts = datetime.now().strftime("%I:%M:%S%p")
        print(f"[{ts}] [{level}] {msg}")
        return

    current = inspect.currentframe()
    frame = current.f_back if current is not None else None
    filename = Path(frame.f_code.co_filename).name if frame else "<unknown>"
    lineno = frame.f_lineno if frame else 0

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{ts}] [{level}] {filename}:{lineno} - {msg}\n"

    exc_type, exc, tb = sys.exc_info()
    if exc is not None:
        log_line += "".join(traceback.format_exception(exc_type, exc, tb)) + "\n"
    
    try:
        with _LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(log_line)
        
        display_ts = datetime.now().strftime("%I:%M:%S%p")
        display_msg = f"[{display_ts}] [{level}] {msg}"
        
        if level == "ERROR":
            _ORIGINAL_STDERR.write(display_msg + "\n")
        elif level == "INFO":
            _ORIGINAL_STDOUT.write(display_msg + "\n")
        elif level == "DEBUG" and debug:
            _ORIGINAL_STDOUT.write(display_msg + "\n")
            
    except Exception as e:
        _ORIGINAL_STDERR.write(f"[Logger Error] {e}\n")

def report_failure(error_msg: str, context: str = "General") -> None:
    """Write a failure report file in the log directory and log the event."""
    log(f"FAILURE [{context}]: {error_msg}", level="ERROR")
    
    if _LOG_FILE is None:
        return

    try:
        report_path = _LOG_FILE.parent / "failure_report.txt"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(report_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{context}]\n{error_msg}\n{'-'*40}\n")
    except Exception as e:
        _ORIGINAL_STDERR.write(f"[Critical Logger Error] {e}\n")
