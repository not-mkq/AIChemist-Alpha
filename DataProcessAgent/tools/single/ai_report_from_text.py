# tools/ai_report_from_text.py
"""
AI 报告生成工具（通用版）

- 输入：prompt + 文本文件
- 行为：将 prompt 和文本内容拼接后发送到指定的 OpenAI 兼容接口，生成分析报告
- 输出：Markdown 报告文件（同目录下 `<stem>_ai_report.md`）
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import requests  # 需要环境里有 requests

from tool_runtime import regist_tool, return_file


def _read_text_file(path: str, encoding: str | None = None) -> str:
    """尽量稳健地读入文本文件内容，编码不对时尝试回退。"""
    tried = []
    enc_list = []
    if encoding:
        enc_list.append(encoding)
    enc_list.extend(["utf-8", "gbk", "latin-1"])

    last_err: Optional[Exception] = None
    for enc in enc_list:
        if enc in tried:
            continue
        tried.append(enc)
        try:
            with open(path, "r", encoding=enc, errors="ignore") as f:
                return f.read()
        except Exception as e:
            last_err = e
            continue

    # 如果所有尝试都失败，抛出最后一个异常
    raise RuntimeError(f"无法读取文本文件: {path}, encodings tried={tried}, last_error={last_err}")


def _build_messages(
    prompt: str,
    file_content: str,
    system_prompt: str | None = None,
) -> list[dict]:
    """构造 OpenAI /chat/completions 风格的 messages 列表。"""
    sys_msg = system_prompt or (
        "You are a helpful assistant. Read the following text and write a clear, "
        "structured report according to the user's instructions."
    )

    full_user_content = (
        prompt.rstrip()
        + "\n\n"
        + "----\n"
        + "Below is the input text file content. Use it as the ONLY source of facts in your report.\n\n"
        + file_content
    )

    return [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": full_user_content},
    ]


def _call_chat_completion(
    api_url: str,
    api_key: str,
    model: str | None,
    messages: list[dict],
    temperature: float | None = None,
    max_output_tokens: int | None = None,
) -> str:
    """调用 OpenAI 兼容的 chat/completions 接口，返回文本内容。"""
    import time
    import random
    
    # 如果URL不以 /chat/completions 结尾，自动添加
    if not api_url.endswith("/chat/completions"):
        if api_url.endswith("/"):
            endpoint_url = api_url + "chat/completions"
        else:
            endpoint_url = api_url + "/chat/completions"
    else:
        endpoint_url = api_url

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
        # 兼容 openai 的 `max_completion_tokens` / `max_tokens` 两种写法
        payload["max_tokens"] = int(max_output_tokens)

    max_retries = 10
    base_delay = 2.0

    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(endpoint_url, json=payload, headers=headers, timeout=120)
            
            # 记录非 200 响应
            if resp.status_code != 200:
                print(f"[AI-TEXT-TOOL] Error Response (Status {resp.status_code}): {resp.text}")
            
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
            elif isinstance(e, RuntimeError) and ("缺少 'choices' 字段" in error_msg or "API 返回错误" in error_msg):
                should_retry = True
                error_msg = f"API Logic Error: {error_msg}"

            if should_retry and attempt < max_retries:
                # 指数退避 + 抖动
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                delay = min(delay, 60.0)
                
                print(f"[AI-TEXT-TOOL] Warning: {error_msg}. Retrying in {delay:.2f}s... (Attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
                continue
            else:
                # 不可重试或次数用尽
                if attempt >= max_retries:
                    print(f"[AI-TEXT-TOOL] Error: {max_retries} retries exhausted. Final error: {e}")
                raise

    # 理论上不会执行到这里
    raise RuntimeError("Unexpected end of retry loop")


def ai_report_from_text(
    tool_name: str,
    source_txt: str,
    prompt: str,
    api_url: str,
    api_key: str,
    model: str | None = None,
    system_prompt: str | None = None,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    encoding: str | None = None,
    output_suffix: str | None = None,
) -> None:
    """
    从文本文件生成 AI 分析报告。

    参数（由模板绑定）:
        tool_name: 运行时框架传入的工具实例名（不参与逻辑，只用于上下文）
        source_txt: 文本文件路径（由 file_label 绑定）
        prompt: 用户指令，会和文件内容拼在一起作为 user 内容
        api_url: OpenAI 兼容 chat/completions HTTP 接口地址
        api_key: API key（仅运行时使用）
        model: 模型名称，例如 "gpt-4o-mini" 或本地兼容模型
        system_prompt: 可选 system 提示词
        temperature: 采样温度（默认 0.2 左右）
        max_output_tokens: 输出 token 上限（默认 1024 左右）
        encoding: 源文件编码（默认 utf-8，失败会自动尝试 gbk / latin-1）
        output_suffix: 输出文件名后缀（默认 "_ai_report"）
    """
    # 1. 读取文件内容
    src_path = os.path.abspath(source_txt)
    if not os.path.isfile(src_path):
        raise FileNotFoundError(f"源文本文件不存在: {src_path}")

    text = _read_text_file(src_path, encoding=encoding or "utf-8")

    # 2. 构造 messages
    messages = _build_messages(prompt=prompt, file_content=text, system_prompt=system_prompt)

    # 3. 调用模型
    #   注意：这里不会打印 api_key，避免泄露
    report_text = _call_chat_completion(
        api_url=api_url,
        api_key=api_key,
        model=model,
        messages=messages,
        temperature=temperature if temperature is not None else 0.2,
        max_output_tokens=max_output_tokens if max_output_tokens is not None else 1024,
    )

    # 4. 写出报告文件（同目录下 <stem>_ai_report.md 或自定义后缀）
    src_p = Path(src_path)
    suffix = output_suffix if output_suffix else "_ai_report"
    out_name = f"{src_p.stem}{suffix}.md"
    out_path = src_p.with_name(out_name)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# AI Report\n\n")
        f.write(report_text.strip())
        f.write("\n")

    # 5. 返回文件（用于前端下载 / 作为 output_file_label）
    return_file(str(out_path))


# 注册到运行时
regist_tool(ai_report_from_text)
