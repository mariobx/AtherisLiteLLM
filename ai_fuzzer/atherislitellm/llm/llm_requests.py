from pathlib import Path
from typing import Optional, Tuple
import yaml
from ai_fuzzer.atherislitellm.fetch import fetch_docs
import re
from ai_fuzzer.atherislitellm.logger.logs import log
import litellm
import time
import logging
import litellm

class LiteLLMDebugFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            if any(term in record.msg for term in (
                "litellm.completion",
                "Params passed to completion()",
                "params passed to completion()",
                "Request to litellm",
                "Request Sent from LiteLLM",
            )):
                record.msg = "A request was sent with litellm"
                record.args = ()
            elif any(term in record.msg for term in (
                "token_counter.py:388",
                "RAW RESPONSE:",
            )):
                record.msg = "A response was recieved from litellm"
                record.args = ()
        if getattr(record, "filename", None) == "token_counter.py" and getattr(record, "lineno", None) == 388:
            record.msg = "A response was recieved from litellm"
            record.args = ()
        return True


def enable_debug_logging(run_dir: Path):
    """Enable LiteLLM debug logging and route it exclusively to a file in run_dir."""
    
    # Create file handler
    debug_log_path = run_dir / "litellm_debug.log"
    file_handler = logging.FileHandler(debug_log_path)
    file_handler.setLevel(logging.DEBUG)
    file_handler.addFilter(LiteLLMDebugFilter())
    
    # Standard formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s:%(levelname)s: %(filename)s:%(lineno)s - %(message)s",
        datefmt="%H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    
    # Use LiteLLM's internal method to bind the handler and stop propagation
    # (This automatically calls lg.handlers.clear() and lg.propagate = False for all litellm loggers)
    try:
        from litellm._logging import _initialize_loggers_with_handler
        _initialize_loggers_with_handler(file_handler)
    except ImportError:
        # Fallback if internal structure changes
        loggers = [
            logging.getLogger("LiteLLM"),
            logging.getLogger("LiteLLM Router"),
            logging.getLogger("LiteLLM Proxy")
        ]
        for lg in loggers:
            lg.handlers.clear()
            lg.addHandler(file_handler)
            lg.propagate = False

    # Turn on debug levels
    litellm._turn_on_debug()


def normalize_ollama_model(model: str) -> str:
    """
    Normalize Ollama model names to use the chat endpoint.

    LiteLLM routes 'ollama/' to /api/generate (raw completion, no chat template).
    'ollama_chat/' routes to /api/chat, which applies the model's native chat
    template (e.g. Granite, Llama, Qwen each have their own). Since we send
    structured messages with roles, /api/chat is the correct endpoint.
    """
    if model.startswith("ollama/"):
        return model.replace("ollama/", "ollama_chat/", 1)
    return model


def extract_code_blocks(text: str) -> str:
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

def get_response(client: dict, temperature: float, full_prompt: str, debug: bool = False, **kwargs) -> Optional[dict]:
    """Prepare a prompt, call LLM via LiteLLM to generate content, and return the text."""
    model = normalize_ollama_model(client["model"])
    log(f"Calling LLM ({model})...", level="INFO")
    start_time = time.time()
    return_object = {}
    try:
        completion_kwargs = {
            "model": model,
            "messages": [{"role": "user", "content": full_prompt}],
            "temperature": temperature,
            "num_retries": 1,
            "timeout": 900,
        }
        api_key_val = client.get("api_key")
        if api_key_val and api_key_val.startswith("http"):
            completion_kwargs["api_base"] = api_key_val
        elif model.startswith("ollama") and not api_key_val:
            completion_kwargs["api_base"] = "http://localhost:11434"
        else:
            completion_kwargs["api_key"] = api_key_val
            
        response = litellm.completion(**completion_kwargs, **kwargs)
        end_time = time.time()
        time_taken = round(end_time - start_time, 2)
        log(f"LLM responded in {time_taken}s", level="INFO")

        content = response.choices[0].message.content
        return_object["model"] = model
        if hasattr(response, "usage") and response.usage:
            return_object["input_tokens"] = getattr(response.usage, "prompt_tokens", 0)
            return_object["output_tokens"] = getattr(response.usage, "completion_tokens", 0)
            return_object["total_tokens"] = getattr(response.usage, "total_tokens", 0)
        else:
            return_object["input_tokens"] = 0
            return_object["output_tokens"] = 0
            return_object["total_tokens"] = 0
        return_object["content"] = content
        return_object["time_taken"] = time_taken

        if not content:
            log("Received empty content from model.", level="ERROR")
        return return_object

    except litellm.exceptions.Timeout as e:
        log(f"LLM call timed out after 900s: {e}", level="ERROR")
        return None
    except litellm.exceptions.ContextWindowExceededError as e:
        log(f"Prompt too large for model context window: {e}", level="ERROR")
        return None
    except litellm.exceptions.ServiceUnavailableError as e:
        log(f"LLM service unavailable (is Ollama running?): {e}", level="ERROR")
        return None
    except litellm.exceptions.BadRequestError as e:
        log(f"Bad request to LLM (check model name/params): {e}", level="ERROR")
        return None
    except Exception as e:
        log(f"Unexpected LLM error ({type(e).__name__}): {e}", level="ERROR")
        return None
