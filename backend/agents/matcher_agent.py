"""MatcherAgent - Fuzzy match project names against existing targets database."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from services.prompt_manager import get_prompt

log = logging.getLogger(__name__)


MATCHER_AGENT_PROMPT = """你是一名标的匹配专家。你的任务是判断用户提到的项目名称是否与已有标的库中的某个标的匹配。

## 输入

1. **项目名称**：用户提到的名称（可能是简称、全称、项目代号）
2. **已有标的库**：数据库中已有的标的列表（公司名称 + 行业）

## 你的任务

对每个项目名称，判断：
1. **是否匹配**：是新建标的，还是更新已有标的？
2. **匹配对象**：如果是更新，匹配到哪个已有标的？
3. **置信度**：匹配的置信度（high/medium/low）
4. **理由**：为什么这样判断

## 匹配规则

### 高置信度匹配（high）

- 名称完全一致（忽略空格、标点）
- 简称与全称的明确对应关系（如"好当家" ↔ "好当家集团股份有限公司"）
- 股票代码一致

### 中等置信度匹配（medium）

- 名称高度相似但有细微差异（如"某某科技" vs "某某科技有限公司"）
- 行业一致且名称核心部分相同

### 低置信度匹配（low）

- 名称部分重叠，但可能是不同公司
- 需要用户确认

### 不匹配（新建）

- 名称完全不同
- 库中无相似标的

## 输出格式

```json
{
  "matches": [
    {
      "project_name": "好当家",
      "action": "update",
      "matched_report_id": "rpt_abc123",
      "matched_company_name": "好当家集团股份有限公司",
      "confidence": "high",
      "reason": "项目名称'好当家'是库中'好当家集团股份有限公司'的常用简称"
    },
    {
      "project_name": "某某科技",
      "action": "create",
      "matched_report_id": null,
      "matched_company_name": null,
      "confidence": null,
      "reason": "库中无相似标的，判断为新建"
    }
  ]
}
```

## 重要原则

1. **宁可保守**：不确定时标记为 medium 或 low，让用户确认
2. **考虑行业**：同名公司在不同行业可能是不同实体
3. **简称优先**：中国公司常用简称，"某某集团" 通常简称为 "某某"
4. **不要猜测**：如果库中没有相似的，直接判断为新建
"""


async def run_matcher_agent(
    project_names: list[str],
    existing_targets: list[dict],
    client: AsyncOpenAI,
    model: str,
    on_progress: Any = None,
) -> dict:
    """Run MatcherAgent to match project names against existing targets.

    Args:
        project_names: 项目名称列表
        existing_targets: 已有标的列表 [{report_id, company_name, industry}, ...]
        client: OpenAI client
        model: Model name
        on_progress: 进度回调

    Returns:
        {
            "matches": [
                {
                    "project_name": "好当家",
                    "action": "update" | "create",
                    "matched_report_id": "rpt_xxx" | null,
                    "matched_company_name": "..." | null,
                    "confidence": "high" | "medium" | "low" | null,
                    "reason": "..."
                },
                ...
            ]
        }
    """
    if not project_names:
        return {"matches": []}

    # 构建已有标的库的文本表示
    target_lines = []
    for t in existing_targets[:1000]:  # 限制1000条
        report_id = t.get("report_id", "")
        company_name = t.get("company_name", "")
        industry = t.get("industry", "")

        if not company_name:
            continue

        if industry and str(industry) not in ("None", "nan", ""):
            target_lines.append(f"- {company_name} | {industry} | {report_id}")
        else:
            target_lines.append(f"- {company_name} | {report_id}")

    existing_str = "\n".join(target_lines) if target_lines else "（库中暂无标的）"

    # 构建用户消息
    project_list = "\n".join(f"- {name}" for name in project_names)

    user_message = f"""## 待匹配的项目名称

{project_list}

## 已有标的库

{existing_str}

请对每个项目名称进行匹配判断。
"""

    messages = [
        {"role": "system", "content": get_prompt("matcher_agent", MATCHER_AGENT_PROMPT)},
        {"role": "user", "content": user_message},
    ]

    try:
        if on_progress:
            await on_progress("MatcherAgent 正在匹配标的...")

        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
        )

        content = response.choices[0].message.content or ""
        content = content.strip()

        # 解析 JSON
        m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", content)
        if m:
            content = m.group(1)

        result = json.loads(content)

        if on_progress:
            new_count = sum(1 for m in result.get("matches", []) if m.get("action") == "create")
            update_count = len(result.get("matches", [])) - new_count
            await on_progress(f"MatcherAgent 完成：{new_count} 个新建，{update_count} 个更新")

        return result

    except Exception as e:
        log.error(f"MatcherAgent failed: {e}")
        # 降级：全部标记为新建
        return {
            "matches": [
                {
                    "project_name": name,
                    "action": "create",
                    "matched_report_id": None,
                    "matched_company_name": None,
                    "confidence": None,
                    "reason": f"匹配失败，默认为新建。错误：{e}",
                }
                for name in project_names
            ]
        }
