import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

from tool_runtime import regist_tool, return_file

logger = logging.getLogger(__name__)

def json_aggregate_series(
    tool_name: str,
    source_jsons: Union[str, List[str]], # Input file(s)
    
    # Optional: Add Metadata/Attribute
    add_key: str | None = None,
    add_value: str | None = None,
) -> None:
    """
    Aggregate multiple JSON series files into a single JSON file.
    Optionally adds a custom property to each series object.
    """
    
    # 1. Normalize Input
    json_paths = [source_jsons] if isinstance(source_jsons, str) else source_jsons
    all_objects = []
    
    # 2. Read and Aggregate
    for p in json_paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    all_objects.extend(data)
                else:
                    all_objects.append(data)
        except Exception as e:
            logger.error(f"Failed to load JSON {p}: {e}")

    # 3. Apply Custom Attribute
    if add_key and str(add_key).strip():
        key = str(add_key).strip()
        val = add_value # Can be evaluated? Or raw string? 
        # User said "value". Usually raw string is safer here unless they want eval.
        # Let's support simple string first.
        
        for obj in all_objects:
            # Where to add? Top level or Metadata?
            # Top level is more flexible for "grouping" logic.
            obj[key] = val

    # 4. Output
    out_name = "aggregated_series.json"
    with open(out_name, "w", encoding="utf-8") as f:
        json.dump(all_objects, f, indent=2, ensure_ascii=False)
        
    return_file(out_name)

regist_tool(json_aggregate_series)
