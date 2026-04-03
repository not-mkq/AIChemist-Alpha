from fastapi import APIRouter
from fastapi.responses import JSONResponse
from typing import Optional, Dict, Any
import logging
import json

from tool_registry import (
    list_tools_by_directory, 
    _scan_tool_configs,
    get_tool_config_from_file,
    get_tool_type_from_file,
    get_tool_code_comment,
    get_tool_instance_comment,
    get_tool_code_template,
    save_tool_instance_to_file,
    delete_tool_instance_from_file,
    check_tool_instance_exists
)
from profile_config import get_tool_codes_dir, get_tool_instances_dir

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/tools")
def list_tools(directory: Optional[str] = None):
    """列出工具实例名"""
    if directory is not None:
        result = list_tools_by_directory(directory)
    else:
        result = _scan_tool_configs()
    
    return {
        "tools": result["single"],
        "merge_tools": result["merge"],
        "meta_tools": result["meta"]
    }

@router.get("/tool-instance/{instance_name}")
def get_tool_instance(instance_name: str):
    """获取工具实例详情"""
    try:
        config = get_tool_config_from_file(instance_name)
        if config is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        
        tool_type = get_tool_type_from_file(instance_name)
        if tool_type is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        
        code_name = config.get("code_name")
        instance_comment = get_tool_instance_comment(instance_name)
        code_comment = None
        
        if code_name:
            try:
                code_comment = get_tool_code_comment(code_name)
            except Exception as e:
                logger.warning(f"Failed to get code comment for {code_name}: {e}")
        
        return {
            "status": "ok",
            "instance_name": instance_name,
            "tool_type": tool_type,
            "code_name": code_name,
            "config": config,
            "comment": instance_comment,
            "code_comment": code_comment
        }
    except Exception as e:
        logger.error(f"get_tool_instance failed: {e}", exc_info=True)
        return JSONResponse({"status": "error", "reason": "internal_error", "detail": str(e)}, status_code=500)

@router.get("/tool-code/{code_name}/comment")
def get_tool_code_comment_endpoint(code_name: str):
    """获取工具代码注释"""
    comment = get_tool_code_comment(code_name)
    if comment is None:
        return JSONResponse({"status": "error", "reason": "not_found", "detail": f"Tool code '{code_name}' not found"}, status_code=404)
    return {"status": "ok", "code_name": code_name, "comment": comment}

@router.get("/tool-code/{code_name}/params")
def get_tool_code_params_endpoint(code_name: str):
    """获取工具代码参数信息"""
    template = get_tool_code_template(code_name)
    if not template:
        return JSONResponse({"status": "error", "reason": "not_found", "detail": f"Template for code '{code_name}' not found"}, status_code=404)
    
    params = template.get("params", [])
    tool_type = template.get("tool_type", "single")
    file_params = [p["name"] for p in params if p.get("type") == "file_label"]
    
    result = {
        "status": "ok",
        "code_name": code_name,
        "tool_type": tool_type,
        "params": params,
        "file_params": file_params,
        "input_cols": template.get("input_cols", {}),
        "output_file_label": template.get("output_file_label"),
        "result_col": template.get("result_col"),
        "output_pattern": template.get("output_pattern")
    }
    return result

@router.get("/tool-codes")
def list_tool_codes():
    """列出所有工具代码"""
    result = {"single": [], "merge": [], "meta": []}
    template_dirs = [get_tool_codes_dir("single"), get_tool_codes_dir("merge"), get_tool_codes_dir("meta")]
    seen_codes = set()
    
    for template_dir in template_dirs:
        if not template_dir.exists(): continue
        for template_file in template_dir.glob("*.template.config.json"):
            try:
                with open(template_file, "r", encoding="utf-8") as f:
                    template_data = json.load(f)
                code_name, tool_type = template_data.get("code_name"), template_data.get("tool_type")
                if not code_name or not tool_type or code_name in seen_codes: continue
                seen_codes.add(code_name)
                if tool_type in result:
                    result[tool_type].append({"code_name": code_name, "comment": template_data.get("comment", "")})
            except Exception as e:
                logger.error(f"Error reading {template_file}: {e}")
    
    for tool_type in result:
        result[tool_type].sort(key=lambda x: x["code_name"])
    return {"status": "ok", **result}

@router.post("/tool-instance")
def create_tool_instance(body: Dict[str, Any]):
    """创建工具实例"""
    try:
        instance_name, tool_type, config = body["instance_name"], body["tool_type"], body["config"]
        comment, directory = body.get("comment"), body.get("directory", "")
        if get_tool_config_from_file(instance_name) is not None:
            return JSONResponse({"status": "error", "reason": "instance_exists", "detail": f"工具实例 '{instance_name}' 已存在"}, status_code=400)
        config_file = save_tool_instance_to_file(instance_name, tool_type, config, comment, directory)
        return {"status": "ok", "instance_name": instance_name, "file_path": str(config_file)}
    except Exception as e:
        logger.error(f"create_tool_instance failed: {e}", exc_info=True)
        return JSONResponse({"status": "error", "reason": "create_failed", "detail": str(e)}, status_code=500)

@router.put("/tool-instance/{instance_name}")
def update_tool_instance(instance_name: str, body: Dict[str, Any]):
    """更新工具实例"""
    try:
        if get_tool_config_from_file(instance_name) is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        tool_type = get_tool_type_from_file(instance_name)
        new_config, comment, new_directory = body["config"], body.get("comment"), body.get("directory")
        
        if new_directory is not None:
            delete_tool_instance_from_file(instance_name)
            directory = new_directory
        else:
            existing_dir = check_tool_instance_exists(instance_name)
            directory = existing_dir if existing_dir is not None else ""
        
        config_file = save_tool_instance_to_file(instance_name, tool_type, new_config, comment, directory)
        return {"status": "ok", "instance_name": instance_name, "file_path": str(config_file)}
    except Exception as e:
        logger.error(f"update_tool_instance failed: {e}", exc_info=True)
        return JSONResponse({"status": "error", "reason": "update_failed", "detail": str(e)}, status_code=500)

@router.delete("/tool-instance/{instance_name}")
def delete_tool_instance(instance_name: str):
    """删除工具实例"""
    if get_tool_config_from_file(instance_name) is None:
        return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
    if delete_tool_instance_from_file(instance_name):
        return {"status": "ok", "instance_name": instance_name}
    return JSONResponse({"status": "error", "reason": "delete_failed"}, status_code=500)

@router.post("/tool-instance/{instance_name}/export")
def export_tool_instance(instance_name: str):
    """导出工具实例"""
    directory = check_tool_instance_exists(instance_name)
    if directory is None:
        return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
    config_file = (get_tool_instances_dir() / directory / f"{instance_name}.config.json") if directory else (get_tool_instances_dir() / f"{instance_name}.config.json")
    return {"status": "ok", "instance_name": instance_name, "file_path": str(config_file)}

@router.post("/reload-all")
def reload_all_endpoint():
    """重新加载所有工具代码和模板"""
    import tool_registry
    try:
        tool_registry._load_all_tool_modules()
        stats_codes = tool_registry.load_tool_code_metadata()
        from meta_runtime import load_meta_tools
        import importlib
        import meta_runtime
        importlib.reload(meta_runtime)
        load_meta_tools()
        label_sync_result = tool_registry.sync_all_output_labels_to_label_config()
        return {"status": "ok", "codes": stats_codes, "labels": label_sync_result}
    except Exception as e:
        logger.error(f"reload_all failed: {e}", exc_info=True)
        return JSONResponse({"status": "error", "reason": "reload_failed", "detail": str(e)}, status_code=500)

@router.post("/load-metadata")
def load_metadata_endpoint():
    """加载代码模板元数据"""
    import tool_registry
    try:
        stats = tool_registry.load_tool_code_metadata()
        return {"status": "ok", **stats}
    except Exception as e:
        return JSONResponse({"status": "error", "reason": "internal_error", "detail": str(e)}, status_code=500)

@router.post("/register-tools")
def register_tools_endpoint():
    """扫描所有工具配置文件（不注册）"""
    import tool_registry
    tool_registry._load_all_tool_modules()
    configs = tool_registry._scan_tool_configs()
    import importlib
    import meta_runtime
    importlib.reload(meta_runtime)
    return {"status": "ok", "single": len(configs["single"]), "merge": len(configs["merge"]), "meta": len(configs["meta"]), "total": sum(len(v) for v in configs.values())}
