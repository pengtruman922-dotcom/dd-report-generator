"""Step 2: Researcher Agent – web research with function calling tool loop."""

from __future__ import annotations

import json
import asyncio
import logging
from typing import Any, Callable

from agents.base_agent import create_client
from prompts.researcher_prompt import SYSTEM_PROMPT
from tools.tool_definitions import TOOLS
from tools.duckduckgo_search import web_search
from tools.jina_reader import fetch_webpage
from config import MAX_TOOL_ITERATIONS

log = logging.getLogger(__name__)


def _is_content_filter_error(exc: Exception) -> bool:
    """Check if an exception is a DashScope content moderation rejection."""
    msg = str(exc).lower()
    return "data_inspection_failed" in msg or "datainspectionfailed" in msg


def _trim_last_tool_batch(messages: list[dict]) -> list[dict]:
    """Remove the last batch of tool-result + tool-call messages (the ones
    that likely triggered the content filter)."""
    trimmed = list(messages)
    # Remove trailing tool-result messages
    while trimmed and trimmed[-1].get("role") == "tool":
        trimmed.pop()
    # Remove the assistant message that made those tool calls
    if trimmed and trimmed[-1].get("role") == "assistant" and trimmed[-1].get("tool_calls"):
        trimmed.pop()
    return trimmed


async def research(
    company_profile: dict[str, Any],
    ai_config: dict,
    on_progress: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Run the researcher agent with tool loop; return ResearchData dict."""
    client = create_client(ai_config["base_url"], ai_config["api_key"])
    model = ai_config["model"]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "请对以下公司进行网络研究，补充公开信息：\n\n"
                "```json\n"
                + json.dumps(company_profile, ensure_ascii=False, indent=2)
                + "\n```"
            ),
        },
    ]

    content_filter_hit = False

    for iteration in range(MAX_TOOL_ITERATIONS):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.3,
            )
        except Exception as e:
            if _is_content_filter_error(e):
                log.warning("Content filter triggered at iteration %d, salvaging...", iteration + 1)
                content_filter_hit = True
                break
            raise

        choice = response.choices[0]
        assistant_msg = choice.message

        # Append assistant message to history
        messages.append(assistant_msg.model_dump())

        # If no tool calls, we're done
        if not assistant_msg.tool_calls:
            break

        # Execute tool calls
        for tc in assistant_msg.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)

            if on_progress:
                await _maybe_await(on_progress, f"🔍 [{iteration+1}] {fn_name}: {_summarise_args(fn_name, fn_args)}")

            try:
                result = await _execute_tool(fn_name, fn_args)
            except Exception as e:
                result = f"Error: {e}"

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(result) if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
                }
            )
    else:
        # Max iterations reached – ask model to wrap up
        content_filter_hit = True  # reuse the same salvage path

    # ── Produce final output ──────────────────────────────────────────
    if content_filter_hit:
        # Trim messages that triggered the filter, then ask model to output results
        if on_progress:
            await _maybe_await(on_progress, "⚠️ 内容审查触发，使用已收集的信息生成结果...")
        messages = _trim_last_tool_batch(messages)
        messages.append({
            "role": "user",
            "content": "请根据已收集到的信息，直接输出最终的JSON研究结果。不要再调用搜索工具。",
        })
        try:
            response = await client.chat.completions.create(
                model=model, messages=messages, temperature=0.3,
            )
            assistant_msg = response.choices[0].message
        except Exception as e:
            if _is_content_filter_error(e):
                # Even salvage failed – try with minimal messages
                log.warning("Salvage also hit content filter, using minimal context")
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "由于内容限制，无法完成完整的网络研究。请根据你对以下公司的已有知识，"
                            "输出JSON格式的研究结果（尽你所能提供信息）：\n\n"
                            + json.dumps(company_profile, ensure_ascii=False, indent=2)
                        ),
                    },
                ]
                try:
                    response = await client.chat.completions.create(
                        model=model, messages=messages, temperature=0.3,
                    )
                    assistant_msg = response.choices[0].message
                except Exception:
                    return {"raw_research": "内容审查限制导致研究中断", "sources": []}
            else:
                raise

    # Parse final JSON
    content = assistant_msg.content or ""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        content = "\n".join(lines)

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Return raw text wrapped in a dict
        return {"raw_research": content, "sources": []}


async def _execute_tool(name: str, args: dict) -> Any:
    """Dispatch a tool call."""
    if name == "web_search":
        # Run sync DDG in a thread
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: web_search(args["query"], args.get("max_results", 8)),
        )
    elif name == "fetch_webpage":
        return await fetch_webpage(args["url"])
    else:
        return f"Unknown tool: {name}"


def _summarise_args(fn_name: str, args: dict) -> str:
    if fn_name == "web_search":
        return args.get("query", "")[:60]
    elif fn_name == "fetch_webpage":
        return args.get("url", "")[:80]
    return str(args)[:60]


async def _maybe_await(fn, *args):
    result = fn(*args)
    if asyncio.iscoroutine(result):
        await result
