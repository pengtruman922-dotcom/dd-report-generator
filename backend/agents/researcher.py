"""Step 2: Researcher Agent – web research with function calling tool loop."""

from __future__ import annotations

import json
import asyncio
import logging
from typing import Any, Callable

from agents.base_agent import create_client
from prompts.researcher_prompt import SYSTEM_PROMPT, build_researcher_prompt
from config import MAX_TOOL_ITERATIONS, RESEARCH_ITERATIONS, DEFAULT_TOOLS_CONFIG, SEARCH_QUALITY_THRESHOLD, MIN_SEARCH_RESULTS
from tools import registry
from tools.base import ToolProvider
from tools.fallback import FallbackToolProvider

log = logging.getLogger(__name__)


def _is_content_filter_error(exc: Exception) -> bool:
    """Check if an exception is a DashScope content moderation rejection."""
    msg = str(exc).lower()
    return "data_inspection_failed" in msg or "datainspectionfailed" in msg


def _trim_last_tool_batch(messages: list[dict]) -> list[dict]:
    """Remove the last batch of tool-result + tool-call messages (the ones
    that likely triggered the content filter)."""
    trimmed = list(messages)
    while trimmed and trimmed[-1].get("role") == "tool":
        trimmed.pop()
    if trimmed and trimmed[-1].get("role") == "assistant" and trimmed[-1].get("tool_calls"):
        trimmed.pop()
    return trimmed


def validate_tools_config(tools_config: dict | None = None) -> list[str]:
    """Validate tools config, return list of error messages (empty = OK)."""
    if tools_config is None:
        return []
    errors: list[str] = []

    # Validate search provider(s)
    search_cfg = tools_config.get("search", {})
    active_search = search_cfg.get("active_provider", "duckduckgo")
    provider_configs = search_cfg.get("providers", {})
    fallback_chain = search_cfg.get("fallback_chain", [])

    # Validate fallback chain if configured
    providers_to_validate = fallback_chain if fallback_chain else [active_search]
    for provider_id in providers_to_validate:
        try:
            inst = registry.create_instance(provider_id, provider_configs.get(provider_id, {}))
            for err in inst.validate_config():
                errors.append(f"搜索引擎「{inst.display_name}」: {err}")
        except KeyError:
            errors.append(f"搜索引擎 {provider_id} 未注册")

    # Validate scraper provider(s)
    scraper_cfg = tools_config.get("scraper", {})
    active_scraper = scraper_cfg.get("active_provider", "jina_reader")
    scraper_configs = scraper_cfg.get("providers", {})
    scraper_fallback_chain = scraper_cfg.get("fallback_chain", [])

    # Validate fallback chain if configured
    scrapers_to_validate = scraper_fallback_chain if scraper_fallback_chain else [active_scraper]
    for provider_id in scrapers_to_validate:
        try:
            inst = registry.create_instance(provider_id, scraper_configs.get(provider_id, {}))
            for err in inst.validate_config():
                errors.append(f"网页抓取器「{inst.display_name}」: {err}")
        except KeyError:
            errors.append(f"网页抓取器 {provider_id} 未注册")

    # Validate datasource providers
    ds_cfg = tools_config.get("datasource", {})
    active_ds = ds_cfg.get("active_providers", [])
    ds_configs = ds_cfg.get("providers", {})
    for ds_id in active_ds:
        try:
            inst = registry.create_instance(ds_id, ds_configs.get(ds_id, {}))
            for err in inst.validate_config():
                errors.append(f"数据源「{inst.display_name}」: {err}")
        except KeyError:
            errors.append(f"数据源 {ds_id} 未注册")

    return errors


def _is_company_listed(company_profile: dict[str, Any] | None) -> bool | None:
    """Determine if the company is listed. Returns True/False/None (unknown)."""
    if not company_profile:
        return None
    is_listed = company_profile.get("is_listed", "")
    if isinstance(is_listed, str):
        is_listed = is_listed.strip().lower()
    if is_listed in ("是", "yes", "true", "1", True):
        return True
    if is_listed in ("否", "no", "false", "0", False):
        return False
    # If stock_code is present, likely listed
    if company_profile.get("stock_code"):
        return True
    return None


def _assess_search_quality(results: Any, query: str) -> float:
    """Assess the quality of search results.

    Returns a quality score between 0.0 and 1.0 based on:
    - Number of results (quantity)
    - Relevance indicators (title/snippet matching query keywords)
    - Recency indicators (presence of recent years in results)

    Args:
        results: Search results (list of dicts or error string)
        query: The original search query

    Returns:
        Quality score (0.0 = poor, 1.0 = excellent)
    """
    # Handle error cases
    if not results or isinstance(results, str):
        return 0.0

    if not isinstance(results, list):
        return 0.0

    # Base score from result count
    result_count = len(results)
    if result_count == 0:
        return 0.0

    count_score = min(result_count / 10.0, 1.0)  # Max score at 10+ results

    # Relevance score: check if query keywords appear in titles/snippets
    query_keywords = set(query.lower().split())
    # Remove common Chinese stop words
    stop_words = {"的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个"}
    query_keywords = query_keywords - stop_words

    if not query_keywords:
        relevance_score = 0.5  # Neutral if no meaningful keywords
    else:
        relevant_count = 0
        for result in results:
            if not isinstance(result, dict):
                continue
            title = result.get("title", "").lower()
            snippet = result.get("snippet", "").lower()
            combined = title + " " + snippet

            # Check if any query keyword appears in result
            if any(kw in combined for kw in query_keywords):
                relevant_count += 1

        relevance_score = relevant_count / result_count if result_count > 0 else 0.0

    # Recency score: check for recent years (2024, 2025, 2026)
    recent_years = {"2024", "2025", "2026"}
    recent_count = 0
    for result in results:
        if not isinstance(result, dict):
            continue
        title = result.get("title", "")
        snippet = result.get("snippet", "")
        combined = title + " " + snippet

        if any(year in combined for year in recent_years):
            recent_count += 1

    recency_score = min(recent_count / 3.0, 1.0)  # Max score at 3+ recent results

    # Weighted average: count (40%), relevance (40%), recency (20%)
    quality_score = (count_score * 0.4) + (relevance_score * 0.4) + (recency_score * 0.2)

    log.info(
        f"Search quality: {quality_score:.2f} "
        f"(count={count_score:.2f}, relevance={relevance_score:.2f}, recency={recency_score:.2f})"
    )

    return quality_score


def _build_active_tools(
    tools_config: dict | None = None,
    company_profile: dict[str, Any] | None = None,
) -> tuple[list[dict], dict[str, ToolProvider]]:
    """Build tool definitions and executor instances from the tools config.

    Datasource providers are filtered by target_company_type:
    - "listed" providers are skipped for non-listed companies
    - "unlisted" providers are skipped for listed companies
    - "all" providers are always included

    Returns:
        (tool_defs, executors) where tool_defs is a list of OpenAI function defs
        and executors maps function_name → ToolProvider instance.
    """
    if tools_config is None:
        tools_config = DEFAULT_TOOLS_CONFIG

    tool_defs: list[dict] = []
    executors: dict[str, ToolProvider] = {}

    is_listed = _is_company_listed(company_profile)

    # Search provider (single active or fallback chain)
    search_cfg = tools_config.get("search", {})
    active_search = search_cfg.get("active_provider", "duckduckgo")
    provider_configs = search_cfg.get("providers", {})
    fallback_chain = search_cfg.get("fallback_chain", [])

    # Use fallback chain if configured, otherwise single provider
    if fallback_chain and len(fallback_chain) > 1:
        search_instance = FallbackToolProvider(
            tool_type="search",
            provider_ids=fallback_chain,
            provider_configs=provider_configs,
            primary_provider_id=fallback_chain[0],
            quality_assessor=_assess_search_quality,
            quality_threshold=SEARCH_QUALITY_THRESHOLD,
        )
    else:
        search_instance = registry.create_instance(
            active_search, provider_configs.get(active_search, {})
        )

    func_def = search_instance.openai_function_def()
    fn_name = func_def.get("function", {}).get("name", active_search)
    tool_defs.append(func_def)
    executors[fn_name] = search_instance

    # Scraper provider (single active or fallback chain)
    scraper_cfg = tools_config.get("scraper", {})
    active_scraper = scraper_cfg.get("active_provider", "jina_reader")
    scraper_configs = scraper_cfg.get("providers", {})
    scraper_fallback_chain = scraper_cfg.get("fallback_chain", [])

    # Use fallback chain if configured, otherwise single provider
    if scraper_fallback_chain and len(scraper_fallback_chain) > 1:
        scraper_instance = FallbackToolProvider(
            tool_type="scraper",
            provider_ids=scraper_fallback_chain,
            provider_configs=scraper_configs,
            primary_provider_id=scraper_fallback_chain[0],
        )
    else:
        scraper_instance = registry.create_instance(
            active_scraper, scraper_configs.get(active_scraper, {})
        )

    func_def = scraper_instance.openai_function_def()
    fn_name = func_def.get("function", {}).get("name", active_scraper)
    tool_defs.append(func_def)
    executors[fn_name] = scraper_instance

    # Datasource providers (multiple active, filtered by company type)
    ds_cfg = tools_config.get("datasource", {})
    active_ds = ds_cfg.get("active_providers", [])
    ds_configs = ds_cfg.get("providers", {})
    for ds_id in active_ds:
        try:
            ds_instance = registry.create_instance(ds_id, ds_configs.get(ds_id, {}))
            # Filter by target_company_type
            target = ds_instance.target_company_type
            if target == "listed" and is_listed is False:
                log.info("Skipping datasource %s (listed-only, company is not listed)", ds_id)
                continue
            if target == "unlisted" and is_listed is True:
                log.info("Skipping datasource %s (unlisted-only, company is listed)", ds_id)
                continue
            func_def = ds_instance.openai_function_def()
            fn_name = func_def.get("function", {}).get("name", ds_id)
            tool_defs.append(func_def)
            executors[fn_name] = ds_instance
        except KeyError:
            log.warning("Datasource provider %s not found in registry, skipping", ds_id)

    return tool_defs, executors


async def research(
    company_profile: dict[str, Any],
    ai_config: dict,
    on_progress: Callable[[str], Any] | None = None,
    tools_config: dict | None = None,
) -> tuple[dict[str, Any], dict]:
    """Run the researcher agent with tool loop; return (ResearchData dict, usage_dict).

    Args:
        tools_config: Optional tools configuration dict. When None, falls back
            to DuckDuckGo + Jina (backward compatible).

    Returns:
        tuple: (research_data, usage_dict) where usage_dict contains total token usage
    """
    client = create_client(ai_config["base_url"], ai_config["api_key"])
    model = ai_config["model"]

    # Track token usage across all iterations
    total_usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }

    # Determine max iterations based on company type
    is_listed = _is_company_listed(company_profile)
    if is_listed is True:
        max_iterations = RESEARCH_ITERATIONS["listed"]
        log.info(f"Using {max_iterations} iterations for listed company")
    elif is_listed is False:
        max_iterations = RESEARCH_ITERATIONS["unlisted"]
        log.info(f"Using {max_iterations} iterations for unlisted company")
    else:
        max_iterations = RESEARCH_ITERATIONS["default"]
        log.info(f"Using {max_iterations} iterations (company type unknown)")

    # Build dynamic tools from config (filtered by company type)
    try:
        tool_defs, executors = _build_active_tools(tools_config, company_profile)
        system_prompt = build_researcher_prompt(tool_defs)
    except Exception as e:
        log.warning("Failed to build dynamic tools (%s), falling back to defaults", e)
        tool_defs, executors = _build_active_tools(DEFAULT_TOOLS_CONFIG)
        system_prompt = SYSTEM_PROMPT

    messages = [
        {"role": "system", "content": system_prompt},
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

    for iteration in range(max_iterations):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tool_defs,
                tool_choice="auto",
                temperature=0.3,
            )
            # Track token usage
            if response.usage:
                total_usage["prompt_tokens"] += response.usage.prompt_tokens or 0
                total_usage["completion_tokens"] += response.usage.completion_tokens or 0
                total_usage["total_tokens"] += response.usage.total_tokens or 0
        except Exception as e:
            if _is_content_filter_error(e):
                log.warning("Content filter triggered at iteration %d, salvaging...", iteration + 1)
                content_filter_hit = True
                break
            raise

        choice = response.choices[0]
        assistant_msg = choice.message

        messages.append(assistant_msg.model_dump())

        if not assistant_msg.tool_calls:
            break

        for tc in assistant_msg.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)

            if on_progress:
                await _maybe_await(on_progress, f"🔍 [{iteration+1}] {fn_name}: {_summarise_args(fn_name, fn_args)}")

            try:
                executor = executors.get(fn_name)
                if executor:
                    result = await executor.execute(fn_args)
                else:
                    result = f"Unknown tool: {fn_name}"
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
        content_filter_hit = True  # reuse the same salvage path

    # ── Produce final output ──────────────────────────────────────────
    if content_filter_hit:
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
            # Track salvage token usage
            if response.usage:
                total_usage["prompt_tokens"] += response.usage.prompt_tokens or 0
                total_usage["completion_tokens"] += response.usage.completion_tokens or 0
                total_usage["total_tokens"] += response.usage.total_tokens or 0
        except Exception as e:
            if _is_content_filter_error(e):
                log.warning("Salvage also hit content filter, using minimal context")
                messages = [
                    {"role": "system", "content": system_prompt},
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
                    # Track salvage token usage
                    if response.usage:
                        total_usage["prompt_tokens"] += response.usage.prompt_tokens or 0
                        total_usage["completion_tokens"] += response.usage.completion_tokens or 0
                        total_usage["total_tokens"] += response.usage.total_tokens or 0
                except Exception:
                    return {"raw_research": "内容审查限制导致研究中断", "sources": []}, total_usage
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
        return json.loads(content), total_usage
    except json.JSONDecodeError:
        return {"raw_research": content, "sources": []}, total_usage


def _summarise_args(fn_name: str, args: dict) -> str:
    if fn_name == "web_search":
        return args.get("query", "")[:60]
    elif fn_name == "fetch_webpage":
        return args.get("url", "")[:80]
    elif fn_name == "cninfo_search":
        return f"{args.get('stock_code', '')} {args.get('keyword', '')}"[:60]
    elif fn_name == "akshare_query":
        return f"{args.get('stock_code', '')} {args.get('query_type', '')}"[:60]
    elif fn_name == "tianyancha_query":
        return f"{args.get('company_name', '')} {args.get('query_type', '')}"[:60]
    return str(args)[:60]


async def _maybe_await(fn, *args):
    result = fn(*args)
    if asyncio.iscoroutine(result):
        await result
