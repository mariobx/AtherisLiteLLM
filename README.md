## AtherisLiteLLM:
This project creates a LLM-assisted Python fuzzing harness generator designed to leverage large language models via LiteLLM to automatically build fuzzing harnesses for target Python functions and classes. It uses Google’s Atheris fuzzing engine to dynamically generate and test code, with the aim of uncovering bugs or vulnerabilities in software. 

# Workflow:
  1. Resolve API keys and model configurations.
  2. Clone repository from URL or verify existing local source directory.
  3. Discover and parse Python files for target functions and classes.
  4. (Optional) Filter targets by maintainability index using Radon.
  5. Concurrently generate harnesses via LiteLLM using extracted code context.
  6. Save and organize all valid harnesses into a structured, timestamped output directory.

# Arguments:
  - `-u`, `--url`: Git URL to clone. Defaults to `~/Downloads` if no `--src-dir` is given.
  - `-s`, `--src-dir`: Path to source directory. If `--url` is provided, it clones into a subdirectory here.
  - `-o`, `--output-dir`: Destination for generated harnesses and logs.
  - `-m`, `--model`: LiteLLM model string (e.g. `gemini/gemini-1.5-flash`, `ollama/llama3`).
  - `-pp`, `--prompts-path`: Path to `prompts.yaml` configuration.
  - `-p`, `--prompt`: ID of the prompt template to use.
  - `-k`, `--api-key`: API key string (optional if environment variable exists).
  - `-e`, `--extra-model-prompts`: Vendor-specific parameters as `key=value` pairs.
  - `-d`, `-v`, `--verbose`, `--debug`: Enable verbose application logging.
  - `--litellm_debug_mode`: Enable full LiteLLM request/response dumping. Outputs a massive log file (`litellm_debug.log`) into the specific run directory. Use this ONLY if you need to debug the raw HTTP requests being sent to the LLM.
  - `-sm`, `--smell`: Filter out low-maintainability code using Radon.
  - `-w`, `--workers`: Number of concurrent generation threads.
  - `-tt`, `--test-threshold`: Threshold for filtering out code used for testing to save on tokens (default: `1.1` which disables the filter). Higher values filter less code, lower values filter more.

# Examples:
  1. **Clone from a URL to default Downloads directory:** \
  atherislitellm \
    --url https://github.com/user/repo \
    --output-dir output_logs \
    --prompts-path prompts.yaml \
    --prompt base \
    --model gemini/gemini-1.5-flash \
    --api-key YOUR_KEY \
    --workers 4 \

  2. **Clone from a URL into a specific folder with complexity filtering:** \
  atherislitellm \
    --url https://github.com/user/repo \
    --src-dir /home/user/fuzzing_projects \
    --output-dir output_logs \
    --prompts-path prompts.yaml \
    --prompt base \
    --model openai/gpt-4 \
    --extra-model-prompts project=my-project \
    --debug \
    --smell \

  3. **Use a local directory with short-form flags:** \
  atherislitellm \
    -s /home/user/local_source \
    -o output_logs \
    -pp prompts.yaml \
    -p base \
    -m gemini/gemini-1.5-flash \
    -k YOUR_KEY \
    -w 2 \

  4. **Run with local Ollama model:** \
  export OLLAMA_API_BASE=http://localhost:11434
  atherislitellm \
    -s /home/user/local_source \
    -o output_logs \
    -pp prompts.yaml \
    -p base \
    -m ollama/codegemma:7b \
    -d \
    -sm \
    -e project=fuzz-test

# Output and Analysis:
All results are saved into a structured, timestamped subfolder in your output directory:
  - **Harness Files**: The generated self-contained Atheris fuzzing harnesses.
  - **analysis.csv**: A detailed log capturing comprehensive metadata for all discovered code candidates. This report tracks function names, complexity rankings, maintainability indexes, the generated harness code, and API tokens used tokens_used per prompt.
