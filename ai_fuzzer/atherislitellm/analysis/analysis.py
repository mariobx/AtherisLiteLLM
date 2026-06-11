import pandas as pd
from ai_fuzzer.atherislitellm.logger.logs import log, report_failure
from pathlib import Path

COLUMNS = [
    "candidate_name", "entity_type", "model", 
    "temperature", "prompt_id", "template_prompt", "fuzz_target", "full_prompt",
    "target_lines_of_code", 
    "target_logical_lines_of_code", "target_source_lines_of_code", 
    "target_cyclomatic_complexity", "target_cyclomatic_complexity_rank", 
    "target_maintainability_index", "created_harness", "time_taken",
    "harness_lines_of_code", "harness_logical_lines_of_code", 
    "harness_source_lines_of_code", "harness_cyclomatic_complexity", 
    "harness_cyclomatic_complexity_rank", "harness_maintainability_index", 
    "input_tokens", "output_tokens", "total_tokens"
]

def create_starting_dataframe() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)

def add_columns_to_dataframe(df: pd.DataFrame, column_name: str, information: any) -> pd.DataFrame:
    try:
        df[column_name] = information
        return df
    except Exception as e:
        log(f"Error adding information to column: {e}", level="ERROR")
        report_failure(f"Error adding information to column: {e}", "Analysis")

def export_dataframe_to_csv(df: pd.DataFrame, csv_path: Path) -> None:
    try:
        df.to_csv(csv_path, index=False)
    except Exception as e:
        log(f"Error exporting dataframe to csv: {e}", level="ERROR")
        report_failure(f"Error exporting dataframe to csv: {e}", "Analysis")
