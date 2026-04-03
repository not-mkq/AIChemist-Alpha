#!/usr/bin/env python3
"""
api_client.py

HTTP API 客户端
"""

import sys
import socket
import json
import logging
from typing import List, Dict, Any, Optional

from i18n import tr
import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
from urllib3.connectionpool import HTTPConnectionPool
from urllib3.connection import HTTPConnection

logger = logging.getLogger(__name__)

# --- UDS 适配器组件 ---

class UnixHTTPConnection(HTTPConnection):
    def __init__(self, unix_socket_path, *args, **kwargs):
        super().__init__("localhost", *args, **kwargs)
        self.unix_socket_path = unix_socket_path
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.unix_socket_path)

class UnixHTTPConnectionPool(HTTPConnectionPool):
    def __init__(self, unix_socket_path, *args, **kwargs):
        super().__init__("localhost", *args, **kwargs)
        self.unix_socket_path = unix_socket_path
    def _new_conn(self):
        return UnixHTTPConnection(self.unix_socket_path)

class UnixPoolManager(PoolManager):
    def __init__(self, unix_socket_path, *args, **kwargs):
        self.unix_socket_path = unix_socket_path
        super().__init__(*args, **kwargs)
    def _new_pool(self, scheme, host, port, request_context=None):
        return UnixHTTPConnectionPool(self.unix_socket_path)

class UnixAdapter(HTTPAdapter):
    def __init__(self, unix_socket_path):
        self.unix_socket_path = unix_socket_path
        super().__init__()
        self.poolmanager = UnixPoolManager(unix_socket_path)

# --- ApiClient 类 ---

class ApiClient:
    """HTTP API 客户端 (支持 TCP 和 UDS)"""
    
    def __init__(self, base_url: str = "http://127.0.0.1:8000", transport: str = "tcp", uds_path: str = "/tmp/dataprocess.sock"):
        self.session = requests.Session()
        self.session.trust_env = False  # 禁用代理
        
        if transport == "uds" and sys.platform != "win32":
            # 挂载 UDS 适配器
            adapter = UnixAdapter(uds_path)
            self.session.mount("http://unix-socket", adapter)
            self.base_url = "http://unix-socket"
            logger.info(f"ApiClient 初始化 (通讯方式: UDS, 路径: {uds_path})")
        else:
            self.base_url = base_url.rstrip("/")
            logger.info(f"ApiClient 初始化 (通讯方式: TCP, 地址: {self.base_url})")
    
    def get_tools(self, directory: Optional[str] = None) -> Dict[str, list]:
        """获取工具列表（可选指定目录）
        
        参数：
            directory: 目录名（""表示根目录，None表示返回所有工具）
        """
        try:
            url = f"{self.base_url}/tools"
            params = {}
            # directory 为空字符串 "" 表示根目录，None 表示不指定目录（返回所有工具）
            # 为了明确，我们总是传递 directory 参数（即使是空字符串）
            if directory is not None:
                params["directory"] = directory
            logger.info(f"请求工具列表: {url}, params={params}")
            response = self.session.get(url, params=params, timeout=10)
            logger.info(f"响应状态码: {response.status_code}, URL: {response.url}")
            response.raise_for_status()
            data = response.json()
            logger.info(f"获取工具列表成功，工具数量: single={len(data.get('tools', []))}, merge={len(data.get('merge_tools', []))}, meta={len(data.get('meta_tools', []))}")
            return data
        except requests.exceptions.ConnectionError as e:
            logger.error(f"连接失败: {e}")
            raise Exception(tr("err_connect_failed").format(self.base_url))
        except requests.exceptions.Timeout as e:
            logger.error(f"请求超时: {e}")
            raise Exception(tr("err_timeout").format(self.base_url))
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP 错误: {e}, 响应内容: {e.response.text if hasattr(e, 'response') else 'N/A'}")
            raise Exception(f"HTTP 错误: {e}")
        except Exception as e:
            logger.error(f"获取工具列表失败: {e}", exc_info=True)
            raise
    
    def get_profiles(self) -> List[str]:
        """获取所有profile列表"""
        try:
            response = self.session.get(f"{self.base_url}/profiles", timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("profiles", [])
        except Exception as e:
            logger.error(f"获取profile列表失败: {e}")
            return []
    
    def get_current_profile(self) -> str:
        """获取当前profile"""
        try:
            response = self.session.get(f"{self.base_url}/profile", timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("profile", "default-profile")
        except Exception as e:
            logger.error(f"获取当前profile失败: {e}")
            return "default-profile"
    
    def set_current_profile(self, profile: str) -> None:
        """设置当前profile"""
        try:
            response = self.session.put(f"{self.base_url}/profile", json={"profile": profile}, timeout=10)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"设置profile失败: {e}")
            raise
    
    def get_directories(self) -> List[str]:
        """获取当前profile下的目录列表"""
        try:
            response = self.session.get(f"{self.base_url}/directories", timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("directories", [])
        except Exception as e:
            logger.error(f"获取目录列表失败: {e}")
            return []
    
    def get_tool_instance(self, instance_name: str) -> Dict[str, Any]:
        """获取工具实例详情"""
        try:
            logger.info(f"请求工具实例详情: {instance_name}")
            response = self.session.get(f"{self.base_url}/tool-instance/{instance_name}", timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            # 404错误时返回错误信息，而不是抛出异常
            if e.response.status_code == 404:
                logger.error(f"获取工具实例详情失败: {e}")
                return {
                    "status": "error",
                    "reason": "not_found",
                    "detail": tr("err_instance_not_found").format(instance_name)
                }
            logger.error(f"获取工具实例详情失败: {e}")
            raise
        except Exception as e:
            logger.error(f"获取工具实例详情失败: {e}")
            raise
    
    def get_tool_codes(self) -> Dict[str, list]:
        """获取所有工具代码"""
        try:
            logger.info(f"请求工具代码列表: {self.base_url}/tool-codes")
            response = self.session.get(f"{self.base_url}/tool-codes", timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"获取工具代码列表失败: {e}")
            raise
    
    def get_labels(self) -> Dict[str, Dict[str, str]]:
        """获取所有标签"""
        try:
            logger.info(f"请求标签列表: {self.base_url}/labels")
            response = self.session.get(f"{self.base_url}/labels", timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"获取标签列表失败: {e}")
            raise
    
    def create_tool_instance(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """创建工具实例（需要包含 directory 字段）"""
        response = self.session.post(f"{self.base_url}/tool-instance", json=data, timeout=10)
        response.raise_for_status()
        return response.json()
    
    def update_tool_instance(self, instance_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """更新工具实例"""
        response = self.session.put(f"{self.base_url}/tool-instance/{instance_name}", json=data, timeout=10)
        response.raise_for_status()
        return response.json()

    def relabel_all(self) -> Dict[str, Any]:
        """重打所有项目的标签"""
        response = self.session.post(f"{self.base_url}/relabel-all", timeout=300)
        response.raise_for_status()
        return response.json()

    def relabel_project(self, project: str) -> Dict[str, Any]:
        """重打指定项目的标签"""
        response = self.session.post(f"{self.base_url}/project/{project}/relabel", timeout=300)
        response.raise_for_status()
        return response.json()
    
    def delete_tool_instance(self, instance_name: str) -> Dict[str, Any]:
        """删除工具实例"""
        response = self.session.delete(f"{self.base_url}/tool-instance/{instance_name}", timeout=10)
        response.raise_for_status()
        return response.json()
    
    def export_tool_instance(self, instance_name: str) -> Dict[str, Any]:
        """导出工具实例"""
        response = self.session.post(f"{self.base_url}/tool-instance/{instance_name}/export", timeout=10)
        response.raise_for_status()
        return response.json()
    
    def load_all_instances(self) -> Dict[str, Any]:
        """加载所有工具实例"""
        try:
            logger.info("请求加载所有工具实例")
            response = self.session.post(f"{self.base_url}/register-tools", timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"加载所有工具实例失败: {e}")
            raise
    
    def load_all_templates(self) -> Dict[str, Any]:
        """加载所有工具代码模板"""
        try:
            logger.info("请求加载所有工具代码模板")
            response = self.session.post(f"{self.base_url}/load-metadata", timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"加载所有工具代码模板失败: {e}")
            raise

    def reload_all(self) -> Dict[str, Any]:
        """重新加载代码和模板（不再加载实例）"""
        response = self.session.post(f"{self.base_url}/reload-all", timeout=60)
        response.raise_for_status()
        return response.json()
    
    def get_tool_code_comment(self, code_name: str) -> Optional[str]:
        """获取工具代码注释"""
        try:
            response = self.session.get(f"{self.base_url}/tool-code/{code_name}/comment", timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("comment")
        except Exception as e:
            logger.debug(f"获取代码注释失败: {code_name}, {e}")
            return None
    
    def get_tool_code_params(self, code_name: str) -> Optional[Dict[str, Any]]:
        """获取工具代码参数信息"""
        try:
            response = self.session.get(f"{self.base_url}/tool-code/{code_name}/params", timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "ok":
                return data
            return None
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                # 模板数据不存在，可能是数据库还没有加载模板
                logger.debug(f"代码模板不存在: {code_name}，可能需要先加载模板数据")
            else:
                logger.debug(f"获取代码参数失败: {code_name}, HTTP {e.response.status_code}")
            return None
        except Exception as e:
            logger.debug(f"获取代码参数失败: {code_name}, {e}")
            return None
    
    def get_projects(self) -> list:
        """获取所有项目列表"""
        try:
            response = self.session.get(f"{self.base_url}/projects", timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("projects", [])
        except Exception as e:
            logger.error(f"获取项目列表失败: {e}")
            return []
    
    def get_project_tool_config(self, project: str, tool_name: str) -> Optional[Dict[str, Any]]:
        """获取项目的工具配置"""
        try:
            response = self.session.get(f"{self.base_url}/project/{project}/tool/{tool_name}", timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "ok":
                return data.get("config")
            return None
        except Exception as e:
            logger.debug(f"获取项目工具配置失败: {project}/{tool_name}, {e}")
            return None
    
    def update_project_tool_config(self, project: str, tool_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """更新项目的工具配置"""
        response = self.session.put(
            f"{self.base_url}/project/{project}/tool/{tool_name}",
            json={"config": config},
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    
    def load_default_tool_config(self, project: str, tool_name: str, prefer_default: bool = False) -> Optional[Dict[str, Any]]:
        """加载默认工具配置"""
        try:
            response = self.session.post(
                f"{self.base_url}/project/{project}/tool/{tool_name}/load-default",
                params={"prefer_default": str(prefer_default).lower()},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "ok":
                return data.get("config")
            return None
        except Exception as e:
            logger.debug(f"加载默认工具配置失败: {project}/{tool_name}, {e}")
            return None
    
    def upload_zip(
        self,
        project: str,
        file_path: str,
        upload_type: str = "batch",
        batch_prefix: str = "Batch",
        item_prefix: str = "Item"
    ) -> Dict[str, Any]:
        """
        上传 ZIP 文件到项目
        
        Args:
            project: 项目名称
            file_path: ZIP 文件路径
            upload_type: 上传类型 ("batch" | "item" | "files")
            batch_prefix: Batch 前缀
            item_prefix: Item 前缀
        
        Returns:
            上传结果字典
        """
        try:
            logger.info(f"开始上传 ZIP 文件: project={project}, file={file_path}, upload_type={upload_type}")
            with open(file_path, 'rb') as f:
                files = {'files': (file_path.split('/')[-1], f, 'application/zip')}
                data = {
                    'project': project,
                    'upload_type': upload_type,
                    'batch_prefix': batch_prefix,
                    'item_prefix': item_prefix
                }
                logger.info(f"发送上传请求到: {self.base_url}/upload")
                response = self.session.post(
                    f"{self.base_url}/upload",
                    files=files,
                    data=data,
                    timeout=300  # 上传可能需要较长时间
                )
                logger.info(f"上传响应状态码: {response.status_code}")
                
                # 尝试解析响应
                try:
                    result = response.json()
                    logger.info(f"上传响应内容: {result}")
                except Exception as json_err:
                    logger.error(f"解析响应 JSON 失败: {json_err}, 响应文本: {response.text[:500]}")
                    raise Exception(f"服务器返回了无效的 JSON 响应: {response.text[:200]}")
                
                response.raise_for_status()
                return result
        except requests.exceptions.ConnectionError as e:
            logger.error(f"连接失败: {e}", exc_info=True)
            raise Exception(f"无法连接到后端服务 ({self.base_url})\n\n请确保后端服务已启动")
        except requests.exceptions.Timeout as e:
            logger.error(f"上传超时: {e}", exc_info=True)
            raise Exception("上传超时（超过 300 秒）\n\n可能原因:\n  1. 文件太大\n  2. 网络连接慢\n  3. 后端处理时间过长")
        except requests.exceptions.HTTPError as e:
            error_detail = ""
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    error_detail = error_data.get("detail", str(e))
                    logger.error(f"HTTP 错误: {e}, 响应内容: {error_data}")
                except:
                    error_detail = e.response.text[:500] if hasattr(e.response, 'text') else str(e)
                    logger.error(f"HTTP 错误: {e}, 响应文本: {error_detail}")
            else:
                error_detail = str(e)
                logger.error(f"HTTP 错误: {e}")
            raise Exception(f"上传失败 (HTTP {e.response.status_code if hasattr(e, 'response') and e.response else 'N/A'}): {error_detail}")
        except Exception as e:
            logger.error(f"上传 ZIP 文件失败: {e}", exc_info=True)
            raise Exception(f"上传失败: {e}")
    
    def get_project_file_tree(self, project: str) -> Optional[Dict[str, Any]]:
        """获取项目的文件树结构"""
        try:
            response = self.session.get(f"{self.base_url}/project/{project}/file-tree", timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"获取项目文件树失败: {project}, {e}", exc_info=True)
            return None

    def get_project_file_preview(
        self,
        project: str,
        batch: Optional[str],
        item: Optional[str],
        filename: str,
        mode: str = "meta",
        level: str = "item",
    ) -> Optional[Dict[str, Any]]:
        """获取项目文件的预览或元数据。mode=content/meta 由前端决定。"""
        try:
            response = self.session.get(
                f"{self.base_url}/project/{project}/file-preview",
                params={"batch": batch, "item": item, "filename": filename, "mode": mode, "level": level},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"获取文件预览失败: {project}/{batch}/{item}/{filename}, {e}", exc_info=True)
            return None

    def download_file(
        self,
        project: str,
        batch: Optional[str],
        item: Optional[str],
        filename: str,
        dest_path: str,
        level: str = "item",
    ) -> bool:
        """下载文件到本地路径"""
        try:
            response = self.session.get(
                f"{self.base_url}/project/{project}/file-download",
                params={"batch": batch, "item": item, "filename": filename, "level": level},
                stream=True,
                timeout=60,
            )
            response.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            logger.error(f"下载文件失败: {filename}, {e}", exc_info=True)
            return False

    def delete_file_entry(self, project: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """删除项目中的文件或文件夹。"""
        try:
            response = self.session.post(
                f"{self.base_url}/project/{project}/delete-entry",
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"删除文件/文件夹失败: project={project}, payload={payload}, error={e}", exc_info=True)
            raise

    def get_results(self, project: str, scope: str, batch: Optional[str] = None, item: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """获取 item/batch/project 结果表的一行数据；失败时返回 None 并记录日志。"""
        params = {"scope": scope}
        if batch:
            params["batch"] = batch
        if item:
            params["item"] = item
        try:
            response = self.session.get(f"{self.base_url}/project/{project}/results", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"获取结果失败: project={project}, scope={scope}, batch={batch}, item={item}, error={e}", exc_info=True)
            return None

    def get_result_columns(self) -> Dict[str, List[str]]:
        """获取结果表列名（item/batch/project），失败时返回空字典。"""
        try:
            resp = self.session.get(f"{self.base_url}/result-columns", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return {
                "item": data.get("item", []),
                "batch": data.get("batch", []),
                "project": data.get("project", []),
            }
        except Exception as e:
            logger.error(f"获取结果列失败: {e}", exc_info=True)
            return {}
    
    def run_tool(
        self,
        project: str,
        tool: str,
        scope: str,
        batch: Optional[str] = None,
        item: Optional[str] = None,
        run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """运行工具实例"""
        data = {"project": project, "tool": tool, "scope": scope}
        if batch:
            data["batch"] = batch
        if item:
            data["item"] = item
        if run_id:
            data["run_id"] = run_id

        resp = self.session.post(
            f"{self.base_url}/run-tool",
            json=data,
            timeout=3600,  # 运行工具可能需要较长时间
        )
        try:
            payload = resp.json()
        except Exception:
            payload = {"status": "error", "reason": "http_error", "detail": resp.text}

        if resp.status_code >= 400 and payload:
            # 后端会返回结构化错误，保持原样交给上层展示
            logger.warning(f"运行工具返回错误: {payload}")
            return payload

        try:
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"运行工具失败: {e}", exc_info=True)
            raise Exception(f"运行工具失败: {e}")

        return payload

    def get_run_progress(self, run_id: str) -> Dict[str, Any]:
        """获取任务进度"""
        try:
            response = self.session.get(f"{self.base_url}/run-tool/progress/{run_id}", timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"获取进度失败: {e}")
            return {"status": "error", "message": str(e)}

    def export_project_zip(self, project: str, dest_path: str) -> None:
        """导出项目 ZIP 到指定路径"""
        url = f"{self.base_url}/project/{project}/export-zip"
        with self.session.get(url, stream=True, timeout=120) as resp:
            try:
                resp.raise_for_status()
            except Exception as e:
                detail = ""
                try:
                    detail = resp.json()
                except Exception:
                    detail = resp.text
                logger.error(f"导出 ZIP 失败: {e}, detail={detail}")
                raise Exception(f"导出失败: {detail}")
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

    def check_tool_before_run(
        self,
        project: str,
        tool: str,
        scope: str,
        batch: Optional[str] = None,
        item: Optional[str] = None,
    ) -> Dict[str, Any]:
        """运行前检查工具是否可用"""
        data = {"project": project, "tool": tool, "scope": scope}
        if batch:
            data["batch"] = batch
        if item:
            data["item"] = item
        response = self.session.post(
            f"{self.base_url}/run-tool/check",
            json=data,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()
