"""Intake Agent: parses mixed-format input (text/images/docs/links) into structured operations.

Supports:
- Free-form text (chat logs, emails, memos)
- Images (chat screenshots via multimodal LLM)
- Documents (PDF/DOCX/PPTX via existing parsers)
- URLs (with intelligent sub-page crawling)
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from prompts.intake_agent_prompt import (
    INTAKE_SYSTEM_PROMPT,
    INTAKE_USER_TEMPLATE,
    WEBPAGE_CRAWL_SYSTEM_PROMPT,
)

log = logging.getLogger(__name__)


def _create_client(cfg: dict) -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        api_key=cfg.get("api_key", ""),
    )


def _encode_image(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response, stripping markdown code fences if present."""
    # Remove ```json ... ``` fences
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if m:
        text = m.group(1)
    return json.loads(text)


async def _crawl_url(url: str, scraper_cfg: dict) -> str:
    """Fetch a URL using jina_reader or local_scraper."""
    try:
        from tools.jina_reader import JinaReaderProvider
        provider = JinaReaderProvider(scraper_cfg.get("jina_reader", {}))
        result = await provider.execute({"url": url})
        if result and len(result.strip()) > 100:
            return result
    except Exception as e:
        log.debug("jina_reader failed for %s: %s", url, e)

    try:
        from tools.local_scraper import LocalScraperProvider
        provider = LocalScraperProvider(scraper_cfg.get("local_scraper", {"timeout": 30, "content_limit": 8000}))
        result = await provider.execute({"url": url})
        return result or ""
    except Exception as e:
        log.debug("local_scraper failed for %s: %s", url, e)
        return ""


async def _analyze_and_crawl(
    url: str,
    page_content: str,
    client: AsyncOpenAI,
    model: str,
    max_depth: int,
    current_depth: int = 0,
) -> str:
    """Recursively crawl a URL and its sub-pages based on AI analysis."""
    if current_depth >= max_depth or not page_content.strip():
        return page_content

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": WEBPAGE_CRAWL_SYSTEM_PROMPT},
                {"role": "user", "content": f"当前页面URL：{url}\n\n页面内容：\n{page_content[:6000]}"},
            ],
            temperature=0.1,
        )
        analysis_text = resp.choices[0].message.content or ""
        analysis = _extract_json(analysis_text)
    except Exception as e:
        log.debug("Webpage analysis failed for %s: %s", url, e)
        return page_content

    if not analysis.get("should_crawl_subpages"):
        return page_content

    sub_urls = analysis.get("subpage_urls", [])[:max_depth - current_depth]
    all_content = [f"=== 页面：{url} ===\n{page_content}"]

    for sub_url in sub_urls:
        log.info("Crawling sub-page: %s (depth %d)", sub_url, current_depth + 1)
        sub_content = await _crawl_url(sub_url, {})
        if sub_content.strip():
            all_content.append(f"=== 子页面：{sub_url} ===\n{sub_content[:4000]}")

    return "\n\n".join(all_content)


async def run_intake_agent(
    text_input: str,
    image_items: list[tuple[str, bytes]],      # [(filename, bytes), ...]
    doc_texts: list[tuple[str, str]],           # [(filename, parsed_text), ...]
    urls: list[str],
    existing_targets: list[dict],               # [{bd_code, company_name, project_name, ...}, ...]
    intake_cfg: dict,
    on_progress: Any = None,
) -> dict:
    """
    Run the intake agent on mixed input.

    Returns:
        {
            "operations": [...],
            "summary": "...",
            "raw_content_summary": "..."  # what was actually fed to the LLM
        }
    """
    model = intake_cfg.get("model", "qwen3.5-plus")
    max_crawl = int(intake_cfg.get("max_crawl_depth", 3))
    client = _create_client(intake_cfg)

    # ── Build content blocks ───────────────────────────────────────────────
    content_blocks_text = []    # for text-only fallback
    multimodal_content = []     # for vision-capable model

    # 1. Free-form text
    if text_input and text_input.strip():
        content_blocks_text.append(f"【文字内容】\n{text_input.strip()}")
        multimodal_content.append({"type": "text", "text": f"【文字内容】\n{text_input.strip()}"})

    # 2. Documents (already parsed to text)
    for filename, doc_text in doc_texts:
        if doc_text and doc_text.strip():
            snippet = doc_text[:8000]
            content_blocks_text.append(f"【文档：{filename}】\n{snippet}")
            multimodal_content.append({"type": "text", "text": f"【文档：{filename}】\n{snippet}"})

    # 3. URLs – crawl and optionally drill down
    for url in urls:
        if on_progress:
            await on_progress(f"正在抓取链接：{url}")
        raw_content = await _crawl_url(url, {})
        if raw_content.strip():
            full_content = await _analyze_and_crawl(url, raw_content, client, model, max_crawl)
            snippet = full_content[:6000]
            content_blocks_text.append(f"【网页：{url}】\n{snippet}")
            multimodal_content.append({"type": "text", "text": f"【网页：{url}】\n{snippet}"})
        else:
            log.warning("Could not fetch URL: %s", url)

    # 4. Images (multimodal) – add as image_url content blocks
    for filename, img_bytes in image_items:
        img_b64 = _encode_image(img_bytes)
        # Guess mime type
        ext = filename.lower().rsplit(".", 1)[-1]
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/jpeg")
        multimodal_content.append({"type": "text", "text": f"【图片：{filename}】"})
        multimodal_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{img_b64}"},
        })
        content_blocks_text.append(f"【图片：{filename}（图片内容见上方）】")

    if not multimodal_content:
        return {
            "operations": [],
            "summary": "未提供任何有效输入材料",
            "raw_content_summary": "",
        }

    # ── Format existing targets for system prompt ─────────────────────────
    if existing_targets:
        target_lines = []
        for t in existing_targets[:1000]:  # up to 1000 targets, sorted by recency
            name = t.get("company_name", "")
            industry = t.get("industry", "")
            if not name:
                continue
            if industry and str(industry) not in ("None", "nan", ""):
                target_lines.append(f"- {name} | {industry}")
            else:
                target_lines.append(f"- {name}")
        existing_str = "\n".join(target_lines)
    else:
        existing_str = "（暂无已有标的，所有识别到的企业均为新建）"

    system_prompt = INTAKE_SYSTEM_PROMPT.replace("{existing_targets}", existing_str)

    # ── Call LLM ──────────────────────────────────────────────────────────
    if on_progress:
        await on_progress("正在分析材料，识别标的信息...")

    user_message_content = multimodal_content

    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message_content},
            ],
            temperature=0.1,
        )
        raw_output = resp.choices[0].message.content or ""
        log.info("Intake agent raw output: %s", raw_output[:500])

        result = _extract_json(raw_output)
        result["raw_content_summary"] = f"文字:{bool(text_input)} 图片:{len(image_items)} 文档:{len(doc_texts)} 链接:{len(urls)}"
        return result

    except json.JSONDecodeError as e:
        log.error("Intake agent JSON parse error: %s\nRaw: %s", e, raw_output[:1000])
        return {
            "operations": [],
            "summary": f"AI解析结果格式错误，请重试。原始输出片段：{raw_output[:200]}",
            "raw_content_summary": "",
        }
    except Exception as e:
        log.exception("Intake agent failed")
        raise
