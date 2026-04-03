# tools/ai_report_from_image.py
"""
AI 图像报告生成工具（通用版）

- 输入：prompt + 图像文件
- 行为：将 prompt 作为文字说明 + 图像一起发给支持 vision 的
        OpenAI 兼容 /chat/completions 接口，生成分析报告
- 输出：Markdown 报告文件（同目录下 `<stem>_ai_image_report.md` 或自定义后缀）
"""

from __future__ import annotations

import os
import time
import random
import base64
from pathlib import Path
from typing import Optional

import requests  # 需要环境里有 requests

from tool_runtime import regist_tool, return_file, return_value


def _detect_image_mime(path: str) -> str:
    """根据扩展名简单推断 MIME 类型（不做魔数判断）。"""
    suffix = Path(path).suffix.lower()
    if suffix in {".png"}:
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix in {".webp"}:
        return "image/webp"
    if suffix in {".bmp"}:
        return "image/bmp"
    if suffix in {".gif"}:
        return "image/gif"
    # 兜底
    return "image/png"


def _read_image_as_data_url(path: str) -> str:
    """读取图像文件并转成 data: URL（base64）。"""
    mime = _detect_image_mime(path)
    with open(path, "rb") as f:
        raw = f.read()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _build_messages_for_image(
    prompt: str,
    image_path: str,
    system_prompt: Optional[str] = None,
) -> list[dict]:
    """
    构造 vision 用的 messages：
    - system: 角色说明
    - user: text + image_url(data:URL)
    """
    sys_msg = system_prompt or (
        "You are a helpful vision assistant. Carefully inspect the image and follow "
        "the user's instructions to write a clear, structured report."
    )

    # user 的文本部分：就是用户传入的 prompt
    user_text = prompt.strip()

    # image 以 data URL 方式嵌入
    data_url = _read_image_as_data_url(image_path)

    return [
        {
            "role": "system",
            "content": sys_msg,
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]


def _call_chat_completion(
    api_url: str,
    api_key: str,
    model: Optional[str],
    messages: list[dict],
    temperature: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
) -> str:
    """调用 OpenAI 兼容的 /chat/completions 接口并返回 content 文本。"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload: dict = {
        "messages": messages,
    }
    if model:
        payload["model"] = model
    if temperature is not None:
        payload["temperature"] = float(temperature)
    if max_output_tokens is not None:
        payload["max_tokens"] = int(max_output_tokens)

    max_retries = 10
    base_delay = 2.0

    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(api_url, json=payload, headers=headers, timeout=120)
            
            # 记录非 200 响应
            if resp.status_code != 200:
                print(f"[AI-TOOL] Error Response (Status {resp.status_code}): {resp.text}")
            
            resp.raise_for_status()
            data = resp.json()

            # 检查 choices 字段是否存在
            if "choices" not in data:
                # 检查是否包含 error 字段
                if "error" in data:
                    err_msg = data["error"].get("message") or str(data["error"])
                    raise RuntimeError(f"API 返回错误: {err_msg}")
                raise RuntimeError(f"接口响应中缺少 'choices' 字段: raw={data!r}")

            return data["choices"][0]["message"]["content"]

        except (requests.exceptions.RequestException, Exception) as e:
            # 确定是否需要重试
            should_retry = False
            error_msg = str(e)
            
            # 1. 网络及超时错误
            if isinstance(e, (requests.exceptions.ChunkedEncodingError, 
                                requests.exceptions.ConnectionError,
                                requests.exceptions.Timeout,
                                requests.exceptions.ProxyError)):
                should_retry = True
                error_msg = f"Network Error ({e.__class__.__name__})"
            
            # 2. HTTP 状态码错误
            elif isinstance(e, requests.exceptions.HTTPError):
                status_code = e.response.status_code
                if status_code == 429:
                    should_retry = True
                    error_msg = "429 Too Many Requests"
                elif status_code >= 500:
                    should_retry = True
                    error_msg = f"Server Error ({status_code})"
                else:
                    # 4xx 客户端错误通常不重试，除非是 429
                    should_retry = False
            
            # 3. 业务逻辑/解析错误 (如 choices 缺失)
            # 这种情况有时是因为后端服务瞬时故障，可以尝试重试
            elif isinstance(e, RuntimeError) and ("缺少 'choices' 字段" in error_msg or "API 返回错误" in error_msg):
                should_retry = True
                error_msg = f"API Logic Error: {error_msg}"

            if should_retry and attempt < max_retries:
                # 指数退避 + 抖动
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                delay = min(delay, 60.0)
                
                print(f"[AI-TOOL] Warning: {error_msg}. Retrying in {delay:.2f}s... (Attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
                continue
            else:
                # 不可重试或次数用尽
                if attempt >= max_retries:
                    print(f"[AI-TOOL] Error: {max_retries} retries exhausted. Final error: {e}")
                raise
    
    # 理论上不会执行到这里
    raise RuntimeError("Unexpected end of retry loop")


def ai_report_from_image(
    tool_name: str,
    source_image: str,
    prompt: str,
    api_url: str,
    api_key: str,
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    temperature: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
    output_suffix: Optional[str] = None,
    prompt2: Optional[str] = None,
) -> None:
    """
    从图像文件生成 AI 分析报告。

    参数顺序（必须与 template 保持完全一致）：
        1) source_image: 图像文件路径（file_label 绑定）
        2) prompt: 用户指令（告诉模型如何解读这张图 / 输出什么样的报告）
        3) api_url: OpenAI 兼容 /chat/completions 接口地址
        4) api_key: API key
        5) model: 模型名称（如 gpt-4.1, gpt-4o-mini, 或本地 vision 模型）
        6) system_prompt: 可选的 system 提示词
        7) temperature: 采样温度
        8) max_output_tokens: 输出 token 上限
        9) output_suffix: 输出文件名后缀（默认 "_ai_image_report"）
        10) prompt2: (可选) 第二轮追问 Prompt，其回答将保存到 Result Column 中。
    """
    img_path = os.path.abspath(source_image)
    if not os.path.isfile(img_path):
        raise FileNotFoundError(f"源图像文件不存在: {img_path}")

    # 1. 构造 messages（包含 data:URL 的 image_url）
    messages = _build_messages_for_image(
        prompt=prompt,
        image_path=img_path,
        system_prompt=system_prompt,
    )

    # 2. 调用模型
    report_text = _call_chat_completion(
        api_url=api_url,
        api_key=api_key,
        model=model,
        messages=messages,
        temperature=temperature if temperature is not None else 0.2,
        max_output_tokens=max_output_tokens if max_output_tokens is not None else 1024,
    )

    # 3. 输出 Markdown 报告文件
    src_p = Path(img_path)
    suffix = output_suffix if output_suffix else "_ai_image_report"
    out_name = f"{src_p.stem}{suffix}.md"
    out_path = src_p.with_name(out_name)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# AI Image Report\n\n")
        f.write(report_text.strip())
        f.write("\n")

    # 4. 返回文件给框架
    return_file(str(out_path))

    # 5. (可选) 第二轮追问
    if prompt2 and prompt2.strip():
        # 将第一轮对话加入上下文
        messages.append({"role": "assistant", "content": report_text})
        messages.append({"role": "user", "content": prompt2.strip()})

        # 发起第二轮调用
        # 这里可以使用略高的 temperature 以获得更多样化的回答？还是保持一致？
        # 保持一致比较稳妥
        response2 = _call_chat_completion(
            api_url=api_url,
            api_key=api_key,
            model=model,
            messages=messages,
            temperature=temperature if temperature is not None else 0.2,
            max_output_tokens=max_output_tokens if max_output_tokens is not None else 1024,
        )

        # 返回结果值（框架会自动将其写入配置的 result_col）
        return_value(response2)


# 注册到工具运行时
regist_tool(ai_report_from_image)
