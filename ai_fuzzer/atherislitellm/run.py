from pydantic import functional_validators
import concurrent.futures
from pathlib import Path
from datetime import datetime
from typing import Dict, List
import pandas as pd
from ai_fuzzer.atherislitellm.llm import llm_requests as atherisai
from ai_fuzzer.atherislitellm.analysis.analysis import create_starting_dataframe, add_columns_to_dataframe
from ai_fuzzer.atherislitellm.parsing import function_parser, file_saver
from ai_fuzzer.atherislitellm.smell.smell import code_smells
from ai_fuzzer.atherislitellm.logger.logs import log, report_failure

def find_function_candidates(path: Path, debug: bool = False, smell: bool = False, test_threshold: float = 1.1) -> dict[str, str]:
    func_name_contents = {}
    try:
        pyfiles = function_parser.get_python_file_paths(path, debug=debug)
        log(f"Scanning {len(pyfiles)} files for functions...", level="INFO")
        
        for pyfile in pyfiles:
            try:
                funcs = function_parser.extract_functions(pyfile, debug=debug, test_threshold=test_threshold)
                for func_name, func_body in funcs.items():
                    if smell:
                        if not code_smells(python_code=func_body, debug=debug):
                            continue
                    func_name_contents[func_name] = func_body
            except Exception as e:
                log(f"Error parsing functions in {pyfile}: {e}", level="ERROR")
    except Exception as e:
        report_failure(f"Critical error during function retrieval: {e}", "Parser")
        return {}
    return func_name_contents        

def prompt_function_candidates(template: str, func_name_contents: dict[str, str], debug: bool = False) -> dict[str, str]:
    """
    Scans the target directory for top-level functions and builds a map of ready-to-use LLM prompts.
    """
    func_tests = {}
    try:
        for func_name, func_body in func_name_contents.items():
            full_prompt = atherisai.format_prompt(template, func_body, debug)
            func_tests[func_name] = full_prompt
    except Exception as e:
        report_failure(f"Critical error during function retrieval: {e}", "Parser")
        
    return func_tests

def find_class_candidates(path: Path, debug: bool = False, smell: bool = False, test_threshold: float = 1.1) -> dict[str, str]:
    class_name_contents = {}
    try:
        pyfiles = function_parser.get_python_file_paths(path, debug=debug)
        log(f"Scanning {len(pyfiles)} files for classes...", level="INFO")
        
        for pyfile in pyfiles:
            try:
                classes_in_file, functions_inside_classes = function_parser.extract_classes(pyfile, debug=debug, test_threshold=test_threshold)
                for class_name, class_body in classes_in_file.items():
                    if smell:
                        if not code_smells(python_code=class_body, debug=debug):
                            continue
                    for function_name, function_body in functions_inside_classes.get(class_name, []):
                        class_name_contents[f"{class_name}.{function_name}"] = {
                            "class_name": class_name,
                            "class_body": class_body,
                            "function_name": function_name,
                            "function_body": function_body
                            }
            except Exception as e:
                log(f"Error parsing classes in {pyfile}: {e}", level="ERROR")
    except Exception as e:
        report_failure(f"Critical error during class retrieval: {e}", "Parser")
        return {}
    return class_name_contents

def prompt_class_candidates(template: str, class_contents: dict[str, dict[str, str]], debug: bool = False) -> dict[str, str]:
    """
    Scans the target directory for top-level classes and builds a map of ready-to-use LLM prompts.
    """
    class_tests = {}
    try:
        for class_name, class_body in class_contents.items():
            customized_target_prompt = (
                f"\n\n{class_body['class_body']}\n\n"
                f"**FUZZING FOCUS**\n"
                f"Method Name: {class_body['function_name']}\n"
                f"Method Body:\n{class_body['function_body']}"
            )
            full_prompt = atherisai.format_prompt(template, customized_target_prompt, debug) 
            class_tests[class_name] = full_prompt
    except Exception as e:
        report_failure(f"Critical error during class retrieval: {e}", "Parser")
    return class_tests

def process_candidate(name: str, full_prompt: str, client: dict, run_dir: Path, temperature: float, debug: bool, **kwargs):
    """
    Atomic worker task that requests a harness from the LLM and saves it to disk.
    """
    try:
        log(f"Starting generation for: {name}", level="DEBUG", debug=debug)
        response, tokens = atherisai.get_response(
            client=client,
            temperature=temperature,
            full_prompt=full_prompt,
            debug=debug,
            **kwargs
        )
        if response:
            block = atherisai.extract_code_blocks(response)
            if block:
                file_saver.save_to_file(name, block, run_dir, debug=debug)
                log(f"Generated harness: {name}", level="INFO")
                return name, block, tokens
            else:
                report_failure(f"No code block found in LLM response for: {name}", "Generation")
        else:
            report_failure(f"Empty response from LLM for candidate: {name}", "Generation")
    except Exception as e:
        report_failure(f"Unexpected error processing {name}: {e}", "Generation")

def run_multi_threaded_generation(
    all_fuzzing_candidates: Dict[str, str],
    client: dict,
    run_dir: Path,
    temperature: float,
    workers: int,
    debug: bool,
    analysis_df: pd.DataFrame,
    **kwargs
) -> None:
    """
    Manages the concurrent generation of multiple harnesses using a thread pool.
    """
    log(f"Generating {len(all_fuzzing_candidates)} harnesses with {workers} workers...", level="INFO")

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                process_candidate, name, prompt, client, run_dir, temperature, debug, **kwargs
            ): name for name, prompt in all_fuzzing_candidates.items()
        }
        
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                if result:
                    returned_name, block, tokens = result
                    analysis_df.loc[analysis_df['candidate_name'] == returned_name, 'created_harness'] = block
                    analysis_df.loc[analysis_df['candidate_name'] == returned_name, 'tokens_used'] = tokens
            except Exception as e:
                report_failure(f"Thread execution failed for {name}: {e}", "Threading")

def run(
        source_dir: Path, output_dir: Path, prompt_id: str, prompt_yaml_path: Path, model: str, api: str | None, debug: bool, smell: bool, workers: int = 1, test_threshold: float = 1.1, **kwargs
) -> None:
    """
    Top-level orchestrator for the fuzzing harness generation pipeline.
    """

    log(f"Starting run (Model: {model}, Workers: {workers})", level="INFO")

    client = {
            "model": model.strip() if model else "",
            "api_key": api.strip() if api else None,
    }

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%m-%d-%y_%I-%M-%S%p").lower()
        safe_model_str = model.strip().replace("/", ".").replace(":", ".")
        output_dir_name = f"fuzzing({source_dir.name})using({safe_model_str}on({timestamp})"
        run_dir = output_dir / output_dir_name
        run_dir.mkdir(parents=True, exist_ok=True)
        log(f"Output directory initialized at: {run_dir}", level="DEBUG", debug=debug)

        log(f"Loading prompt template: {prompt_id}", level="DEBUG", debug=debug)
        temperature, _, template = atherisai.load_prompt_data(prompt_id, prompt_yaml_path, debug)
        
        function_code_snippets = find_function_candidates(source_dir, debug=debug, smell=smell, test_threshold=test_threshold)
        function_prompts = prompt_function_candidates(template, function_code_snippets, debug=debug)
        class_code_snippets = find_class_candidates(source_dir, debug=debug, smell=smell, test_threshold=test_threshold)
        class_prompts = prompt_class_candidates(template, class_code_snippets, debug=debug)

        analysis_df = create_starting_dataframe()
        rows = []

        for name, body in function_code_snippets.items():
            rows.append({
                "candidate_name": name,
                "entity_type": "function",
                "model": model.strip() if model else "",
                "temperature": temperature,
                "prompt_id": prompt_id,
                "full_prompt": function_prompts[name],
                "fuzz_target": body,
                "created_harness": "",
                **{col: 0 for col in analysis_df.columns if col not in [
                    "candidate_name", "entity_type", "model", "temperature", 
                    "prompt_id", "full_prompt", "fuzz_target", "created_harness"
                ]}
            })
        for name, body in class_code_snippets.items():
            rows.append({
                "candidate_name": name,
                "entity_type": "class",
                "model": model.strip() if model else "",
                "temperature": temperature,
                "prompt_id": prompt_id,
                "full_prompt": class_prompts[name],
                "fuzz_target": body["class_body"] + "\n\n#FOCUSING-ON\n\n" + body["function_body"],
                "created_harness": "",
                **{col: 0 for col in analysis_df.columns if col not in [
                    "candidate_name", "entity_type", "model", "temperature", 
                    "prompt_id", "full_prompt", "fuzz_target", "created_harness"
                ]}
            })
        if rows:
            analysis_df = pd.concat([analysis_df, pd.DataFrame(rows)], ignore_index=True)
        
        all_fuzzing_candidates = function_prompts | class_prompts
        
        log(f"Discovery phase complete. Found {len(function_code_snippets)} functions and {len(class_code_snippets)} classes.", level="INFO")
        
        del function_code_snippets
        del class_code_snippets
        del function_prompts
        del class_prompts
        del rows

        if not all_fuzzing_candidates:
            log("No valid functions or classes found for fuzzing.", level="INFO")
            return

        run_multi_threaded_generation(
            all_fuzzing_candidates=all_fuzzing_candidates,
            client=client,
            run_dir=run_dir,
            temperature=temperature,
            workers=workers,
            debug=debug,
            analysis_df=analysis_df,
            **kwargs
        )

        analysis_df.to_csv(run_dir / "analysis.csv", index=False)

        log(f"Success. All harnesses saved in: {run_dir}", level="INFO")

    except Exception as e:
        report_failure(f"Fatal coordination error: {e}", "Orchestration")
        raise e
