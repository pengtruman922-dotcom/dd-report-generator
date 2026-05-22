"""WriterAgent - Core intelligent agent for v3.0 report generation."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from openai import AsyncOpenAI

from agents.chunk_writer import write_chunk
from agents.researcher import research
from prompts.writer_agent_prompt import WRITER_AGENT_SYSTEM_PROMPT
from services.prompt_manager import get_prompt
from utils.attachment_manager import get_attachment_path
from utils.file_parser import parse_attachment

log = logging.getLogger(__name__)


async def run_writer_agent(
    action: str,
    company_profile: dict[str, Any],
    material_summary: str,
    attachment_filenames: list[str],
    existing_chunks: dict[str, dict] | None,
    ai_config: dict,
    research_ai_config: dict | None,
    tools_config: dict | None,
    on_progress: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Run WriterAgent to write/update report chunks.

    Args:
        action: "create" or "update"
        company_profile: {company_name, industry, stock_code, is_listed, ...}
        material_summary: IntakeAgent 生成的材料摘要
        attachment_filenames: 关联附件文件名列表
        existing_chunks: 更新模式下的现有 chunks（chunk_id → {summary, content}）
        ai_config: AI 配置
        tools_config: 工具配置
        on_progress: 进度回调

    Returns:
        {
            "chunks": {
                "chunk0": {summary, content, extracted_fields, index_tags},
                "chunk1": {...},
                ...
            },
            "research_data": {...},  # 如果执行了调研
            "tracking_logs": [...],  # 如果有跟进日志
            "usage": {...}
        }
    """
    client = AsyncOpenAI(base_url=ai_config["base_url"], api_key=ai_config["api_key"])
    model = ai_config["model"]

    # 构建 WriterAgent 的上下文
    context = {
        "action": action,
        "company_profile": company_profile,
        "material_summary": material_summary,
        "attachment_filenames": attachment_filenames,
        "existing_chunks": existing_chunks or {},
    }

    # WriterAgent 的工具定义
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_attachment",
                "description": "读取关联附件的解析文本。附件已由代码层预解析（PDF/DOCX/PPTX/Excel），此工具返回解析后的文本内容。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "附件文件名（从 attachment_filenames 列表中选择）",
                        }
                    },
                    "required": ["filename"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_researcher",
                "description": "调用 Researcher 进行联网公开信息调研。返回按 8 chunk 维度组织的结构化数据。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "company_info": {
                            "type": "object",
                            "description": "公司信息（company_name, industry, stock_code, is_listed）",
                        }
                    },
                    "required": ["company_info"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_chunk",
                "description": "写入或更新一个 chunk。每次只写一个 chunk，可以并行调用多次写不同的 chunk。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chunk_id": {
                            "type": "string",
                            "description": "chunk0~chunk7",
                            "enum": ["chunk0", "chunk1", "chunk2", "chunk3", "chunk4", "chunk5", "chunk6", "chunk7"],
                        },
                        "instruction": {
                            "type": "string",
                            "description": "写作指令，告诉 chunk writer 如何写这个 chunk",
                        },
                    },
                    "required": ["chunk_id", "instruction"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "append_tracking_log",
                "description": "追加跟进日志到 intake_logs 表。用于记录项目推进的关键节点。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "日志内容（包含日期、事件、参与方、结果）",
                        }
                    },
                    "required": ["content"],
                },
            },
        },
    ]

    # 初始消息
    messages = [
        {"role": "system", "content": get_prompt("writer_agent", WRITER_AGENT_SYSTEM_PROMPT)},
        {
            "role": "user",
            "content": (
                f"## 任务\n\n"
                f"action: {action}\n\n"
                f"## 公司信息\n\n```json\n{json.dumps(company_profile, ensure_ascii=False, indent=2)}\n```\n\n"
                f"## 材料摘要\n\n{material_summary}\n\n"
                f"## 关联附件\n\n{', '.join(attachment_filenames) if attachment_filenames else '无'}\n\n"
                + (
                    f"## 现有 chunks\n\n已有以下 chunks，你可以选择更新受影响的 chunk：\n"
                    + ", ".join(existing_chunks.keys())
                    if existing_chunks
                    else ""
                )
                + "\n\n请规划你的工作并开始执行。"
            ),
        },
    ]

    # 工具执行器
    shared_context = {
        "company_profile": company_profile,
        "attachment_summaries": {},
        "research_data": None,
    }

    result = {
        "chunks": {},
        "research_data": None,
        "tracking_logs": [],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }

    max_iterations = 20
    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        if on_progress:
            await _maybe_await(on_progress, f"WriterAgent 迭代 {iteration}/{max_iterations}")

        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            temperature=0.3,
        )

        # Track usage
        if response.usage:
            result["usage"]["prompt_tokens"] += response.usage.prompt_tokens or 0
            result["usage"]["completion_tokens"] += response.usage.completion_tokens or 0
            result["usage"]["total_tokens"] += response.usage.total_tokens or 0

        assistant_msg = response.choices[0].message
        messages.append(assistant_msg.model_dump(exclude_unset=True))

        # 如果没有 tool_calls，说明完成
        if not assistant_msg.tool_calls:
            log.info("WriterAgent finished (no more tool calls)")
            break

        # 分离 write_chunk 工具调用（可并行）和其他工具调用（串行）
        chunk_calls = []
        other_calls = []
        for tc in assistant_msg.tool_calls:
            if tc.function.name == "write_chunk":
                chunk_calls.append(tc)
            else:
                other_calls.append(tc)

        # 先串行处理 read_attachment、run_researcher、append_tracking_log
        for tc in other_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)

            log.info(f"WriterAgent calling {fn_name}: {fn_args}")

            try:
                if fn_name == "read_attachment":
                    tool_result = await _read_attachment(fn_args["filename"], company_profile)
                    shared_context["attachment_summaries"][fn_args["filename"]] = tool_result

                elif fn_name == "run_researcher":
                    if on_progress:
                        await _maybe_await(on_progress, "正在调研...")

                    # Wrap on_progress to suppress encoding errors on Windows
                    def safe_progress(msg):
                        if on_progress:
                            try:
                                r = on_progress(msg)
                                if asyncio.iscoroutine(r):
                                    return r
                            except (UnicodeEncodeError, Exception):
                                pass
                        return None

                    research_data, research_usage = await research(
                        company_profile=fn_args["company_info"],
                        ai_config=research_ai_config or ai_config,
                        tools_config=tools_config,
                        on_progress=safe_progress,
                    )
                    shared_context["research_data"] = research_data
                    result["research_data"] = research_data
                    result["usage"]["prompt_tokens"] += research_usage.get("prompt_tokens", 0)
                    result["usage"]["completion_tokens"] += research_usage.get("completion_tokens", 0)
                    result["usage"]["total_tokens"] += research_usage.get("total_tokens", 0)
                    tool_result = "调研完成，数据已加入共享上下文"

                elif fn_name == "append_tracking_log":
                    result["tracking_logs"].append(fn_args["content"])
                    tool_result = "日志已记录"

                else:
                    tool_result = f"未知工具: {fn_name}"

            except Exception as e:
                log.error(f"Tool {fn_name} failed: {e}")
                tool_result = f"工具执行失败: {e}"

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": str(tool_result),
            })

        # 并行处理所有 write_chunk 调用
        if chunk_calls:
            if on_progress:
                await _maybe_await(
                    on_progress,
                    f"并行写入 {len(chunk_calls)} 个 chunk: {[json.loads(tc.function.arguments)['chunk_id'] for tc in chunk_calls]}"
                )

            async def _write_one(tc):
                fn_args = json.loads(tc.function.arguments)
                chunk_id = fn_args["chunk_id"]
                instruction = fn_args["instruction"]
                existing_content = None
                if existing_chunks and chunk_id in existing_chunks:
                    existing_content = existing_chunks[chunk_id].get("content")
                try:
                    chunk_result = await write_chunk(
                        chunk_id=chunk_id,
                        instruction=instruction,
                        shared_context=shared_context,
                        existing_content=existing_content,
                        client=client,
                        model=model,
                    )
                    return (tc, chunk_id, chunk_result, None)
                except Exception as e:
                    log.error(f"write_chunk {chunk_id} failed: {e}")
                    return (tc, chunk_id, None, str(e))

            parallel_results = await asyncio.gather(*[_write_one(tc) for tc in chunk_calls])

            for tc, chunk_id, chunk_result, err in parallel_results:
                if chunk_result:
                    result["chunks"][chunk_id] = chunk_result
                    tool_result = f"{chunk_id} 写入完成"
                else:
                    tool_result = f"{chunk_id} 写入失败: {err}"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(tool_result),
                })

    return result


async def _read_attachment(filename: str, company_profile: dict) -> str:
    """Read and parse attachment file."""
    report_id = company_profile.get("report_id")
    if not report_id:
        return "错误：无法确定 report_id"
    if not filename:
        return "错误：附件文件名为空"

    attachment_path = get_attachment_path(report_id, filename)

    if not attachment_path.exists():
        return f"错误：附件不存在 {filename}"

    try:
        parsed = parse_attachment(attachment_path)
        if parsed.get("error"):
            return f"解析失败: {parsed['error']}"
        return str(parsed.get("text", ""))[:8000]
    except Exception as e:
        log.error(f"Failed to parse attachment {filename}: {e}")
        return f"解析失败: {e}"


async def _maybe_await(fn, *args):
    import asyncio

    result = fn(*args)
    if asyncio.iscoroutine(result):
        await result
