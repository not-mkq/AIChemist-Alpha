from fastapi import APIRouter
from typing import Dict, Any
from fastapi.responses import JSONResponse
import logging
from profile_config import get_current_profile, set_current_profile
from tool_registry import list_profiles, list_directories

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/profiles")
def list_profiles_endpoint():
    """
    列出所有可用的profile。
    """
    profiles = list_profiles()
    return {
        "status": "ok",
        "profiles": profiles
    }

@router.get("/profile")
def get_current_profile_endpoint():
    """
    获取当前使用的 profile。
    """
    return {
        "status": "ok",
        "profile": get_current_profile()
    }

@router.put("/profile")
def set_current_profile_endpoint(body: Dict[str, Any]):
    """
    设置当前使用的 profile。
    """
    profile = body.get("profile")
    if not profile:
        return JSONResponse(
            {"status": "error", "reason": "missing_profile"},
            status_code=400
        )
    
    # 检查profile是否存在
    available_profiles = list_profiles()
    if profile not in available_profiles:
        return JSONResponse(
            {"status": "error", "reason": "profile_not_found", "detail": f"Profile '{profile}' 不存在"},
            status_code=404
        )
    
    set_current_profile(profile)
    return {
        "status": "ok",
        "profile": profile
    }

@router.get("/directories")
def list_directories_endpoint():
    """
    列出当前profile下的所有一级子目录。
    """
    directories = list_directories()
    return {
        "status": "ok",
        "directories": directories
    }
