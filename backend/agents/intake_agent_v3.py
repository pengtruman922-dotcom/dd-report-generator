"""IntakeAgent v3.0 - Simplified: only identify targets, generate summary, and associate materials."""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from services.prompt_manager import get_prompt

log = logging.getLogger(__name__)


def _create_client(cfg: dict) -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        api_key=cfg.get("api_key", ""),
    )


def _encode_image(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if m:
        text = m.group(1)
    return json.loads(text)


INTAKE_AGENT_V3_PROMPT = """你是一名并购项目录入助手。你的任务是从用户提供的材料中识别标的公司，生成保真材料摘录，并关联附件。

## 你的职责（只做三件事）

1. **识别标的**：从材料中识别出涉及的标的公司名称（可能是多个）
2. **生成保真摘录**：为每个标的生成 `material_summary`，只整理材料中明确出现的事实
3. **关联附件**：判断哪些附件与哪个标的相关

## 你不负责的事情

- ❌ 不提取结构化字段（如营收、净利润等）—— 这由后续的 WriterAgent 负责
- ❌ 不判断新建/更新 —— 这由 MatcherAgent 负责
- ❌ 不做任何匹配或查重 —— 这由 MatcherAgent 负责
- ❌ 不扩写、不补背景、不生成下一步建议、不替用户推断未发生的沟通

## 输出格式

```json
{
  "targets": [
    {
      "project_name": "好当家",
      "bd_code": "BD02456",
      "material_summary": "材料明确提到：好当家集团股份有限公司股票代码为603078；2024年营收2.1亿元，同比增长15%；主营海洋食品加工，产品包括海参、鲍鱼等；2025年2月会面中，董事长唐传勤表示愿意出让控制权，报价8亿元；双方约定下周安排财务尽调。",
      "tracking_material_summary": "2025年2月会面中，董事长唐传勤表示愿意出让控制权，报价8亿元；双方约定下周安排财务尽调。",
      "related_attachments": ["好当家2024年报.pdf", "会议纪要.docx"]
    },
    {
      "project_name": "某某科技",
      "bd_code": null,
      "material_summary": "...",
      "related_attachments": ["某某科技BP.pdf"]
    }
  ]
}
```

## 识别规则

1. **project_name**：使用材料中出现的名称（可能是简称、全称、项目代号），不要自行补全或修改
2. **bd_code**：
   - 仅当材料中明确出现项目编号/BD编号时才填写，例如 `BD12345`
   - 必须原样保留，不要改写、补零、猜测或新生成
   - 如果材料中没有明确 BD 编号，返回 `null` 或不返回该字段
3. **material_summary**：
   - 这是“保真摘录”，不是报告摘要；只允许压缩和分点整理，不允许扩写
   - 不要求字数；短输入就短输出，不要为了凑字数增加内容
   - 必须保留材料中的关键事实：公司名称、行业、财务数据、业务特点、交易意向、跟进动态等
   - 对用户原文中的事实不要改写含义；不确定的内容原样保留或标注“未注明”
   - 如果材料包含多个时间点的信息，按时间倒序（最新在前）
   - 如果用户只输入一句跟进动态，`material_summary` 应尽量接近原文，只做日期规范化和主体识别
4. **tracking_material_summary**：
   - 只提取来自“用户输入框文字”和“聊天记录/沟通截图”的项目跟进动态
   - 不要提取 PDF、Word、PPT、年报、BP、品牌手册等文档附件中的公司介绍、发展历程、业务进展或财务数据
   - 只保留交易推进相关事实：推介对象、买方反馈、报价/估值变化、会议沟通、资料发送、尽调安排、卖方态度等
   - 如果本次没有输入框跟进内容，也没有聊天记录/沟通截图，返回空字符串
5. **related_attachments**：
   - 列出与该标的相关的附件文件名
   - 如果附件明确标注了公司名，关联到对应标的
   - 如果附件是通用材料（如行业报告），可以关联到多个标的

## 特殊情况

- 如果材料中没有明确的标的公司，返回空列表：`{"targets": []}`
- 如果材料涉及多个标的，每个标的独立输出
- 如果无法确定附件归属，`related_attachments` 留空

## 日期与编号规则

- 只有明确带 `BD`、`项目编号`、`内部编号` 等前缀的值，才可作为 `bd_code`
- 不要把裸数字自动解释为项目编号
- 6 位纯数字如果能构成合法日期，优先按 `YYMMDD` 解释：
  - `260427` 应解释为 `2026-04-27`
  - `250801` 应解释为 `2025-08-01`
- 无法判断日期含义时，在 `material_summary` 中原样保留，不要改写成编号

## 跟进动态规则

- 可以记录特定买方反馈，例如“广州工控表示不感兴趣”
- 不要把特定买方反馈扩写为标的通用结论
- 不要补充“内部评估”“暂无尽调安排”“需重新评估其他买家”“调整推介策略”“持续跟进”等原文没有的内容
- 买家态度、我方策略、推荐建议、下一步动作，如果原文没有明确写出，不得生成
- 如果原文明确包含策略或建议，也只可原样保留为材料内容，不要润色扩写

## 大量附件场景

- 如果有大量附件，`material_summary` 应提炼附件中明确出现的核心事实，但仍要保真
- 不要为了完整覆盖附件而编写行业分析或推荐分析
- 附件正文会在后续写作链路中继续提供给 writer；你这里只负责标的识别、附件归属和高层事实摘录
"""


async def run_intake_agent_v3(
    text_input: str,
    image_items: list[tuple[str, bytes]],
    doc_texts: list[tuple[str, str]],
    attachment_filenames: list[str],
    intake_cfg: dict,
    on_progress: Any = None,
) -> dict:
    """Run IntakeAgent v3.0 - simplified version.

    Args:
        text_input: 用户输入的文本
        image_items: [(filename, bytes), ...]
        doc_texts: [(filename, parsed_text), ...]
        attachment_filenames: 所有附件的文件名列表
        intake_cfg: Intake 配置
        on_progress: 进度回调

    Returns:
        {
            "targets": [
                {
                    "project_name": "好当家",
                    "material_summary": "...",
                    "related_attachments": ["file1.pdf", "file2.docx"]
                },
                ...
            ]
        }
    """
    model = intake_cfg.get("model", "qwen3.5-plus")
    client = _create_client(intake_cfg)

    # 构建多模态内容
    multimodal_content = []

    # 1. 文本输入
    if text_input and text_input.strip():
        multimodal_content.append({"type": "text", "text": f"【用户输入】\n{text_input.strip()}"})

    # 2. 文档
    for filename, doc_text in doc_texts:
        if doc_text and doc_text.strip():
            snippet = doc_text[:8000]
            multimodal_content.append({"type": "text", "text": f"【文档：{filename}】\n{snippet}"})

    # 3. 图片
    for filename, img_bytes in image_items:
        img_b64 = _encode_image(img_bytes)
        ext = filename.lower().rsplit(".", 1)[-1]
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/jpeg")
        multimodal_content.append({"type": "text", "text": f"【图片：{filename}】"})
        multimodal_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{img_b64}"},
        })

    if not multimodal_content:
        return {"targets": []}

    # 附件列表
    if attachment_filenames:
        attachment_list = "\n".join(f"- {fn}" for fn in attachment_filenames)
        multimodal_content.append({
            "type": "text",
            "text": f"\n\n## 附件列表\n\n{attachment_list}\n\n请在输出中标注哪些附件与哪个标的相关。"
        })

    messages = [
        {"role": "system", "content": get_prompt("intake_agent_v3", INTAKE_AGENT_V3_PROMPT)},
        {"role": "user", "content": multimodal_content},
    ]

    try:
        if on_progress:
            await on_progress("IntakeAgent 正在识别标的...")

        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.3,
        )

        content = response.choices[0].message.content or ""
        result = _extract_json(content)

        if on_progress:
            await on_progress(f"IntakeAgent 识别到 {len(result.get('targets', []))} 个标的")

        return result

    except Exception as e:
        log.error(f"IntakeAgent v3 failed: {e}")
        return {"targets": [], "error": str(e)}
