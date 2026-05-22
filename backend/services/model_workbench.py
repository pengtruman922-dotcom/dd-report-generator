"""Node catalog and normalized workbench payload for model/prompt settings."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from config import DEFAULT_AI_CONFIG
from services.prompt_manager import get_prompt_override

_PROVIDER_KEYS = ("base_url", "api_key", "model")

_CHUNK_LABELS = {
    "tracking_processor": "Tracking Processor Prompt",
    "info_chunk": "Info Chunk Prompt",
    "index_builder": "Index Builder Prompt",
}

_FIELD_LABELS = {
    "base_url": "Base URL",
    "api_key": "API Key",
    "model": "模型名称",
    "max_crawl_depth": "最大抓取深度",
    "default_mode": "默认模式",
    "core_fields_trigger_research": "触发调研的核心字段",
    "research_data_expire_days": "调研过期天数",
}

_FIELD_DESCRIPTIONS = {
    "max_crawl_depth": "控制 IntakeAgent 自动抓取外链时的最大层级。",
    "default_mode": "录入页默认使用的解析模式。",
    "core_fields_trigger_research": "这些字段变化时会触发需要重新调研的判断。",
    "research_data_expire_days": "超过该天数的调研结果视为过期。",
}

_FIELD_INPUT_TYPES = {
    "max_crawl_depth": "number",
    "default_mode": "select",
    "core_fields_trigger_research": "tags",
    "research_data_expire_days": "number",
}

_FIELD_OPTIONS = {
    "default_mode": [
        {"label": "自动", "value": "auto"},
        {"label": "手动确认", "value": "manual"},
    ]
}


def _build_default_prompt_map() -> dict[str, str]:
    from agents.intake_agent_v3 import INTAKE_AGENT_V3_PROMPT
    from agents.matcher_agent import MATCHER_AGENT_PROMPT
    from prompts.index_builder_prompt import INDEX_BUILDER_PROMPT
    from prompts.info_chunk_prompt import INFO_CHUNK_PROMPT
    from prompts.rating_agent_prompt import RATING_AGENT_SYSTEM_PROMPT
    from prompts.researcher_prompt import RESEARCHER_SYSTEM_PROMPT
    from prompts.tracking_processor_prompt import TRACKING_PROCESSOR_PROMPT

    prompt_map = {
        "intake_agent_v3": INTAKE_AGENT_V3_PROMPT,
        "matcher_agent": MATCHER_AGENT_PROMPT,
        "researcher": RESEARCHER_SYSTEM_PROMPT,
        "tracking_processor": TRACKING_PROCESSOR_PROMPT,
        "info_chunk": INFO_CHUNK_PROMPT,
        "index_builder": INDEX_BUILDER_PROMPT,
        "rating_agent": RATING_AGENT_SYSTEM_PROMPT,
    }
    return prompt_map


NODE_DEFS: list[dict[str, Any]] = [
    {
        "id": "intake_agent_v3",
        "label": "IntakeAgent",
        "group": "录入链路",
        "stage": "parse",
        "config_key": "intake_agent",
        "prompt_id": "intake_agent_v3",
        "runtime_file": "backend/agents/intake_agent_v3.py",
        "prompt_file": "backend/agents/intake_agent_v3.py",
        "description": "识别标的、生成材料摘要、关联附件。",
        "is_primary": True,
    },
    {
        "id": "matcher_agent",
        "label": "MatcherAgent",
        "group": "录入链路",
        "stage": "match",
        "config_key": "matcher_agent",
        "fallback_to": "intake_agent_v3",
        "prompt_id": "matcher_agent",
        "runtime_file": "backend/agents/matcher_agent.py",
        "prompt_file": "backend/agents/matcher_agent.py",
        "description": "匹配新建/更新目标并给出置信度。",
        "is_primary": True,
    },
    {
        "id": "researcher",
        "label": "Researcher",
        "group": "写作链路",
        "stage": "research",
        "config_key": "researcher",
        "prompt_id": "researcher",
        "runtime_file": "backend/agents/researcher.py",
        "prompt_file": "backend/prompts/researcher_prompt.py",
        "description": "联网研究与工具调用循环。",
        "is_primary": True,
    },
    {
        "id": "tracking_processor",
        "label": "TrackingProcessor",
        "group": "写作链路",
        "stage": "tracking",
        "config_key": "tracking_processor",
        "fallback_to": "researcher",
        "prompt_id": "tracking_processor",
        "runtime_file": "backend/agents/tracking_processor.py",
        "prompt_file": "backend/prompts/tracking_processor_prompt.py",
        "description": "处理动态时间线、提炼 seller_fact_snapshot、剔除非通用上下文。",
        "is_primary": True,
    },
    {
        "id": "info_chunk_writer",
        "label": "InfoChunkWriter",
        "group": "写作链路",
        "stage": "info",
        "config_key": "info_chunk_writer",
        "fallback_to": "researcher",
        "prompt_id": "info_chunk",
        "runtime_file": "backend/agents/info_chunk_writer.py",
        "prompt_file": "backend/prompts/info_chunk_prompt.py",
        "description": "合并静态事实、公开事实和 snapshot，生成单个高密度 info_chunk。",
        "is_primary": True,
    },
    {
        "id": "index_builder",
        "label": "IndexBuilder",
        "group": "写作链路",
        "stage": "index",
        "config_key": "index_builder",
        "fallback_to": "info_chunk_writer",
        "prompt_id": "index_builder",
        "runtime_file": "backend/services/index_builder.py",
        "prompt_file": "backend/prompts/index_builder_prompt.py",
        "description": "生成 info_summary、tracking_summary 和 info_index_tags。",
        "is_primary": True,
    },
    {
        "id": "rating_agent",
        "label": "RatingAgent",
        "group": "写作链路",
        "stage": "rating",
        "config_key": "rating_agent",
        "fallback_to": "info_chunk_writer",
        "prompt_id": "rating_agent",
        "runtime_file": "backend/agents/rating_agent.py",
        "prompt_file": "backend/prompts/rating_agent_prompt.py",
        "description": "基于 info_chunk 与 tracking_chunk 做内部可行性评级。",
        "is_primary": True,
    },
]

_NODE_BY_ID = {node["id"]: node for node in NODE_DEFS}


def _build_prompt_view(prompt_id: str, label: str, settings: dict, prompt_defaults: dict[str, str]) -> dict[str, Any]:
    default_prompt = prompt_defaults.get(prompt_id, "")
    override = get_prompt_override(prompt_id, settings)
    return {
        "id": prompt_id,
        "label": label,
        "default": default_prompt,
        "current": override or default_prompt,
        "overridden": bool(override),
    }


def get_node_definition(node_id: str) -> dict[str, Any] | None:
    return _NODE_BY_ID.get(node_id)


def _has_custom_override(node_def: dict[str, Any], raw_ai_config: dict[str, Any]) -> bool:
    config_key = node_def.get("config_key")
    if not config_key:
        return False

    raw = deepcopy(raw_ai_config.get(config_key, {}) or {})
    for key, value in raw.items():
        if key in _PROVIDER_KEYS:
            if value not in (None, ""):
                return True
            continue
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return True
            continue
        return True
    return False


def _effective_mode_label(mode: str, source_node: str | None, inherited_label: str | None = None) -> str:
    if mode == "custom":
        return "本节点"
    if mode == "inherited":
        return inherited_label or (f"继承自 {source_node}" if source_node else "继承")
    return "系统默认"


def _resolve_provider_field(node_id: str, field: str, raw_ai_config: dict[str, Any]) -> dict[str, Any]:
    node_def = _NODE_BY_ID[node_id]
    config_key = node_def.get("config_key")
    fallback_to = node_def.get("fallback_to")
    inherits_from = node_def.get("inherits_from")

    if inherits_from:
        parent = _resolve_provider_field(inherits_from, field, raw_ai_config)
        return {
            "value": parent["value"],
            "source": "inherited",
            "source_node": inherits_from,
            "source_label": f"继承自 {_NODE_BY_ID[inherits_from]['label']}",
            "configured": parent.get("configured", bool(parent["value"])),
        }

    current_raw = deepcopy(raw_ai_config.get(config_key, {}) or {})
    if field in current_raw and current_raw.get(field) not in (None, ""):
        value = current_raw.get(field, "")
        return {
            "value": value,
            "source": "custom",
            "source_node": node_id,
            "source_label": "本节点",
            "configured": bool(value),
        }

    if fallback_to:
        parent = _resolve_provider_field(fallback_to, field, raw_ai_config)
        return {
            "value": parent["value"],
            "source": "inherited",
            "source_node": fallback_to,
            "source_label": f"继承自 {_NODE_BY_ID[fallback_to]['label']}",
            "configured": parent.get("configured", bool(parent["value"])),
        }

    default_value = (DEFAULT_AI_CONFIG.get(config_key, {}) or {}).get(field, "")
    return {
        "value": default_value,
        "source": "system_default",
        "source_node": None,
        "source_label": "系统默认",
        "configured": bool(default_value),
    }


def _resolve_behavior_field(node_id: str, key: str, raw_ai_config: dict[str, Any]) -> dict[str, Any]:
    node_def = _NODE_BY_ID[node_id]
    config_key = node_def.get("config_key")
    fallback_to = node_def.get("fallback_to")
    inherits_from = node_def.get("inherits_from")

    if inherits_from:
        parent = _resolve_behavior_field(inherits_from, key, raw_ai_config)
        return {
            "value": deepcopy(parent["value"]),
            "source": "inherited",
            "source_node": inherits_from,
            "source_label": f"继承自 {_NODE_BY_ID[inherits_from]['label']}",
        }

    current_raw = deepcopy(raw_ai_config.get(config_key, {}) or {})
    if key in current_raw:
        return {
            "value": deepcopy(current_raw[key]),
            "source": "custom",
            "source_node": node_id,
            "source_label": "本节点",
        }

    if fallback_to:
        parent = _resolve_behavior_field(fallback_to, key, raw_ai_config)
        return {
            "value": deepcopy(parent["value"]),
            "source": "inherited",
            "source_node": fallback_to,
            "source_label": f"继承自 {_NODE_BY_ID[fallback_to]['label']}",
        }

    return {
        "value": deepcopy((DEFAULT_AI_CONFIG.get(config_key, {}) or {}).get(key)),
        "source": "system_default",
        "source_node": None,
        "source_label": "系统默认",
    }


def resolve_node_provider_config(node_id: str, ai_config: dict[str, Any]) -> dict[str, Any]:
    node_def = get_node_definition(node_id)
    if not node_def:
        raise KeyError(node_id)

    raw_ai_config = deepcopy(ai_config or {})
    resolved: dict[str, Any] = {}
    for key in _PROVIDER_KEYS:
        item = _resolve_provider_field(node_id, key, raw_ai_config)
        resolved[key] = item["value"]
        resolved[f"{key}_source"] = item["source"]
        resolved[f"{key}_source_node"] = item.get("source_node")
    return resolved


def _build_provider_view(node_def: dict[str, Any], raw_ai_config: dict[str, Any], config_mode: str) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    effective_model = ""
    effective_base_url = ""
    api_key_configured = False
    editable = config_mode == "custom"

    for key in _PROVIDER_KEYS:
        resolved = _resolve_provider_field(node_def["id"], key, raw_ai_config)
        if key == "model":
            effective_model = resolved["value"]
        elif key == "base_url":
            effective_base_url = resolved["value"]
        elif key == "api_key":
            api_key_configured = bool(resolved.get("configured"))

        fields.append(
            {
                "key": key,
                "label": _FIELD_LABELS.get(key, key),
                "input_type": "password" if key == "api_key" else "text",
                "value": "" if key == "api_key" else resolved["value"],
                "default_value": (
                    (DEFAULT_AI_CONFIG.get(node_def.get("config_key"), {}) or {}).get(key, "")
                    if node_def.get("config_key")
                    else ""
                ),
                "editable": editable,
                "is_secret": key == "api_key",
                "configured": bool(resolved.get("configured")),
                "display_value": resolved["value"] if key != "api_key" else "",
                "status_text": "已配置" if resolved.get("configured") else "未配置",
                "source": {
                    "mode": resolved["source"],
                    "label": _effective_mode_label(
                        resolved["source"],
                        resolved.get("source_node"),
                        resolved.get("source_label"),
                    ),
                    "source_node": resolved.get("source_node"),
                },
            }
        )

    return {
        "fields": fields,
        "summary": {
            "model": effective_model,
            "base_url": effective_base_url,
            "api_key_configured": api_key_configured,
        },
    }


def _build_behavior_view(node_def: dict[str, Any], raw_ai_config: dict[str, Any], config_mode: str) -> dict[str, Any] | None:
    config_key = node_def.get("config_key")
    if not config_key:
        return None

    default_behavior = {
        key: value
        for key, value in (DEFAULT_AI_CONFIG.get(config_key, {}) or {}).items()
        if key not in _PROVIDER_KEYS
    }
    stored_behavior = {
        key: value
        for key, value in (raw_ai_config.get(config_key, {}) or {}).items()
        if key not in _PROVIDER_KEYS
    }
    field_names = list(dict.fromkeys([*default_behavior.keys(), *stored_behavior.keys()]))
    if not field_names:
        return None

    fields = []
    for key in field_names:
        resolved = _resolve_behavior_field(node_def["id"], key, raw_ai_config)
        fields.append(
            {
                "key": key,
                "label": _FIELD_LABELS.get(key, key),
                "input_type": _FIELD_INPUT_TYPES.get(key, "text"),
                "description": _FIELD_DESCRIPTIONS.get(key, ""),
                "options": _FIELD_OPTIONS.get(key, []),
                "value": deepcopy(resolved["value"]),
                "default_value": deepcopy(default_behavior.get(key)),
                "editable": config_mode == "custom",
                "source": {
                    "mode": resolved["source"],
                    "label": _effective_mode_label(
                        resolved["source"],
                        resolved.get("source_node"),
                        resolved.get("source_label"),
                    ),
                    "source_node": resolved.get("source_node"),
                },
            }
        )

    return {"fields": fields}


def build_workbench(settings: dict) -> dict[str, Any]:
    raw_ai_config = deepcopy(settings.get("ai_config", {}) or {})
    prompt_defaults = _build_default_prompt_map()
    nodes = []

    for node_def in NODE_DEFS:
        prompt_variants = [
            _build_prompt_view(prompt_id, _CHUNK_LABELS.get(prompt_id, prompt_id), settings, prompt_defaults)
            for prompt_id in node_def.get("prompt_ids", [])
        ]
        prompt_override_count = sum(1 for prompt in prompt_variants if prompt["overridden"])

        prompt = None
        if "prompt_id" in node_def:
            prompt_label = "系统提示词"
            if node_def["id"] == "tracking_processor":
                prompt_label = "动态处理提示词"
            elif node_def["id"] == "info_chunk_writer":
                prompt_label = "信息写作提示词"
            elif node_def["id"] == "index_builder":
                prompt_label = "索引构建提示词"
            elif node_def["id"] == "rating_agent":
                prompt_label = "评级提示词"
            prompt = _build_prompt_view(node_def["prompt_id"], prompt_label, settings, prompt_defaults)
            prompt_override_count += 1 if prompt["overridden"] else 0

        if node_def.get("inherits_from"):
            config_mode = "prompt_only"
            source_node = node_def["inherits_from"]
            source_badge = f"模型继承 { _NODE_BY_ID[source_node]['label'] }"
        elif node_def.get("fallback_to"):
            has_custom = _has_custom_override(node_def, raw_ai_config)
            config_mode = "custom" if has_custom else "inherited"
            source_node = node_def["fallback_to"] if not has_custom else None
            source_badge = (
                "独立配置"
                if has_custom
                else f"继承 { _NODE_BY_ID[node_def['fallback_to']]['label'] }"
            )
        else:
            config_mode = "custom"
            source_node = None
            source_badge = "独立配置"

        node = {
            "id": node_def["id"],
            "label": node_def["label"],
            "group": node_def["group"],
            "stage": node_def["stage"],
            "description": node_def["description"],
            "runtime_file": node_def["runtime_file"],
            "prompt_file": node_def["prompt_file"],
            "is_primary": node_def["is_primary"],
            "config_key": node_def.get("config_key"),
            "config_mode": config_mode,
            "node_kind": "prompt_only" if config_mode == "prompt_only" else (
                "model_with_behavior" if _build_behavior_view(node_def, raw_ai_config, config_mode) else "model"
            ),
            "inherits_from": node_def.get("inherits_from") or node_def.get("fallback_to"),
            "source_badge": source_badge,
            "can_customize": config_mode == "inherited",
            "can_reset": config_mode == "custom" and not node_def.get("inherits_from"),
            "reset_label": "恢复继承" if node_def.get("fallback_to") else "恢复默认",
            "prompt_override_count": prompt_override_count,
            "prompt": prompt,
            "prompt_variants": prompt_variants,
            "provider": _build_provider_view(node_def, raw_ai_config, config_mode),
        }

        behavior = _build_behavior_view(node_def, raw_ai_config, config_mode)
        if behavior:
            node["behavior"] = behavior

        nodes.append(node)

    return {
        "nodes": nodes,
        "ai_config": raw_ai_config,
        "prompt_overrides": settings.get("prompt_overrides", {}) or {},
    }
