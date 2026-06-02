from pathlib import Path
import os
from ai_fuzzer.atherislitellm.logger.logs import log

def save_to_file(name=None, text=None, path=None, debug=False):
    """Save provided text to a timestamped Atheris harness file in path."""
    if path is None:
        raise ValueError("The 'path' argument must not be None.")

    # Make subdirectory: <path>/<name>/
    subdir = Path(path) / str(name)
    subdir.mkdir(parents=True, exist_ok=True)

    # Write file inside the subdirectory
    file_path = subdir / f"atheris_harness_for_(({name})).py"
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(text if text is not None else "")

    log(f"Saved {name} harness to {file_path.name}", level="DEBUG", debug=debug)
