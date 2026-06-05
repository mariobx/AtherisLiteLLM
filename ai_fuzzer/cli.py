from pathlib import Path
import argparse
import os
import sys
import litellm
import git
from urllib.parse import urlparse
from ai_fuzzer.atherislitellm.run import run
from ai_fuzzer.atherislitellm.logger.logs import log, init_logger

def resolve_api_key(arg_val: str | None, model: str, debug: bool = False) -> str | None:
    """Resolve API key from CLI or Environment."""
    if arg_val:
        log("Using API key provided via CLI", level="DEBUG", debug=debug)
        return arg_val.strip()

    try:
        check = litellm.validate_environment(model)
        if check.get("keys_in_environment"):
            log(f"Environment is valid for model '{model}'", level="DEBUG", debug=debug)
            return None
        
        missing = check.get("missing_keys", [])
        if missing:
            if "ollama" in model.lower():
                print(f"Note: Model '{model}' appears to be an Ollama model.")
                print("Make sure your Ollama server is running and accessible.")
                print("If it's not at the default location, set the environment variable:")
                if sys.platform == "win32":
                    print("  set OLLAMA_API_BASE=http://localhost:11434")
                else:
                    print("  export OLLAMA_API_BASE=http://localhost:11434")
                print("-" * 40)

            print(f"Error: Missing configuration for model '{model}'.")
            print("Please provide it via --api-key or set the following environment variable(s):")
            for key in missing:
                if sys.platform == "win32":
                    print(f"  set {key}=your_value_here")
                else:
                    print(f"  export {key}=your_value_here")
            sys.exit(1)
    except Exception as e:
        log(f"Error validating environment: {e}", level="ERROR")
        sys.exit(1)
    
    return None

class ParseKwargs(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, dict())
        for value in values:
            if '=' in value:
                key, val = value.split('=', 1)
                getattr(namespace, self.dest)[key] = val
            else:
                log(f"Ignoring malformed extra parameter: {value}", level="DEBUG", debug=True)

def validate_workers(value):
    """Ensure workers are between 1 and the system's CPU count."""
    try:
        ivalue = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Workers must be an integer (provided {value})")
    
    max_cpu = os.cpu_count() or 1
    if ivalue < 1:
        raise argparse.ArgumentTypeError(f"Workers must be at least 1 (provided {value})")
    if ivalue > max_cpu:
        # We cap it at max_cpu for system stability
        return max_cpu
    return ivalue

def main():
    """Parse CLI arguments and run the fuzzer."""
    parser = argparse.ArgumentParser(
        description="AI-powered Python fuzzer with AtherisLiteLLM.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Cloning & Source Logic:
  - If only --url is provided, it clones to ~/Downloads/<repo_name>.
  - If both --url and --src-dir are provided, it clones into a subdirectory inside --src-dir.
  - If only --src-dir is provided, it uses that local directory as-is.

Examples:
  1. Clone from a URL to default Downloads directory:
  atherislitellm \\
    --url https://github.com/user/repo \\
    --output-dir output_logs \\
    --prompts-path prompts.yaml \\
    --prompt base \\
    --model gemini/gemini-1.5-flash \\
    --api-key YOUR_KEY \\
    --workers 4

  2. Clone from a URL into a specific folder with complexity filtering:
  atherislitellm \\
    --url https://github.com/user/repo \\
    --src-dir /home/user/fuzzing_projects \\
    --output-dir output_logs \\
    --prompts-path prompts.yaml \\
    --prompt base \\
    --model openai/gpt-4 \\
    --extra-model-prompts project=my-project \\
    --debug \\
    --smell

  3. Use a local directory with short-form flags:
  atherislitellm \\
    -s /home/user/local_source \\
    -o output_logs \\
    -pp prompts.yaml \\
    -p base \\
    -m gemini/gemini-1.5-flash \\
    -k YOUR_KEY \\
    -w 2
        """
    )

    parser.add_argument("-s", "--src-dir", type=Path,
                        help="Path to source directory. If --url is provided, it clones into a subdirectory here.")
    parser.add_argument("-u", "--url", type=str,
                        help="Git URL to clone. Defaults to ~/Downloads if no --src-dir is given.")
    parser.add_argument("-o", "--output-dir", type=Path, required=True,
                        help="Destination for generated harnesses and logs.")
    parser.add_argument("-pp", "--prompts-path", type=Path, required=True,
                        help="Path to prompts.yaml configuration.")
    parser.add_argument("-p", "--prompt", default="base", required=True,
                        help="ID of the prompt template to use.")
    parser.add_argument("-m", "--model", type=str, required=True,
                        help="LiteLLM model string (e.g. gemini/gemini-1.5-flash, openai/gpt-4).")
    parser.add_argument("-k", "--api-key", type=str,
                        help="API key string (optional if environment variable exists).")
    parser.add_argument("-e", "--extra-model-prompts", nargs='*', action=ParseKwargs,
                        help="Vendor-specific parameters as key=value pairs.")
    parser.add_argument("-d", "--verbose", "-v", "--debug", action="store_true",
                        help="Enable verbose logging.")
    parser.add_argument("-sm", "--smell", action="store_true",
                        help="Filter out low-maintainability code using Radon.")
    parser.add_argument("-w", "--workers", type=validate_workers, default=1,
                        help=f"Number of concurrent generation threads (default: 1). Max: {os.cpu_count() or 1}")
    parser.add_argument("-tt", "--test-threshold", type=float, default=1.1,
                        help="Threshold for filtering out code used for testing, saves on tokens.\n(default: 1.1 meaning it will always be off\n. Higher values mean you filter less code, lower values filter more).\n ")

    args = parser.parse_args()

    if not args.src_dir and not args.url:
        parser.error("You must provide either --src-dir, --url, or both.")

    init_logger(args.output_dir)

    # Handle URL cloning
    if args.url:
        parsed_url = urlparse(args.url)
        clean_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
        repo_name = Path(parsed_url.path).stem
        
        if args.src_dir:
            # If src_dir is provided, clone INTO it (as a subdirectory)
            target_path = args.src_dir / repo_name
        else:
            # If only url is provided, clone into ~/Downloads
            target_path = Path.home() / "Downloads" / repo_name
        
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if target_path.exists() and any(target_path.iterdir()):
            log(f"Target '{target_path}' is not empty. Assuming already cloned.", level="INFO")
        else:
            log(f"Cloning {clean_url} into {target_path}...", level="INFO")
            try:
                git.Repo.clone_from(clean_url, target_path)
                log("Clone successful.", level="INFO")
            except git.GitCommandError as e:
                log(f"Failed to clone repository: {e}", level="ERROR")
                sys.exit(1)
        
        #update src_dir to the actual clone location for the rest of the app
        args.src_dir = target_path

    if not args.src_dir.is_dir():
        log(f"Source directory '{args.src_dir}' does not exist or is not a directory.", level="ERROR")
        sys.exit(1)

    try:
        litellm.get_llm_provider(args.model)
    except Exception as e:
        log(f"Unrecognized model: {args.model}. {e}", level="ERROR")
        sys.exit(1)

    api_key = resolve_api_key(args.api_key, args.model, args.verbose)
    extra_params = getattr(args, 'extra_model_prompts', {}) or {}

    try:
        run(
            source_dir=args.src_dir,
            output_dir=args.output_dir,
            prompt_id=args.prompt,
            prompt_yaml_path=args.prompts_path,
            model=args.model,
            api=api_key,
            debug=args.verbose,
            smell=args.smell,
            workers=args.workers,
            test_threshold=args.test_threshold,
            **extra_params
        )
    except Exception as e:
        log(f"Fatal error: {e}", level="ERROR")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
