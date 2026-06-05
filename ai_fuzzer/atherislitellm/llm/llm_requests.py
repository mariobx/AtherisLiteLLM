from pathlib import Path
from typing import Optional, Tuple
import yaml
from ai_fuzzer.atherislitellm.fetch import fetch_docs
import re
from ai_fuzzer.atherislitellm.logger.logs import log
import litellm
from litellm import token_counter

def extract_code_blocks(text):
    """Extract fenced code blocks from text and return them joined."""
    if not text:
        return ""
    pattern = r'```(?:[\w+-]*)\s*\n([\s\S]*?)```'
    matches = re.findall(pattern, text)
    return '\n\n'.join(matches)

def load_prompt_data(prompt_id: str, yaml_path: Path, debug=False) -> Tuple[float, str, str]:
    """Load prompt settings from a YAML file and return (temperature, description, template)."""
    with open(yaml_path, "r", encoding="utf-8") as f:
        all_prompts = yaml.safe_load(f)
    if prompt_id not in all_prompts:
        raise KeyError(f"Prompt ID '{prompt_id}' not found in {yaml_path}")
    entry = all_prompts[prompt_id]
    return float(entry["temperature"]), entry["description"], entry["template"]

def format_prompt(template: str, target_func: str, debug=False) -> str:
    """Fill the template with the target function and Atheris docs."""
    doc_block = f"{fetch_docs.fetch_atheris_readme(debug)}\n\n{fetch_docs.fetch_atheris_hooking_docs(debug)}"
    return template.replace("{{CODE}}", target_func).replace("{{DOCS}}", doc_block)

def get_response(client: dict, temperature: float, full_prompt: str, debug: bool = False, **kwargs) -> Tuple[str | None, int | None]:
    """Prepare a prompt, call LLM via LiteLLM to generate content, and return the text."""
    log(f"Calling LLM ({client['model']})...", level="DEBUG", debug=debug)
    
    try:
        response = litellm.completion(
            model=client["model"],
            messages=[{"role": "user", "content": full_prompt}],
            api_key=client["api_key"],
            temperature=temperature,
            num_retries=5,
            **kwargs
        )

        content = getattr(getattr(getattr(response, "choices", [None])[0], "message", None), "content", None)
        tokens = token_counter(model=client["model"], messages=[{"role": "user", "content": full_prompt}])
        if not content:
            log("Received empty content from model.", level="ERROR")
        return content, tokens

    except Exception as e:
        log(f"LiteLLM error: {e}", level="ERROR")
        return None, None
