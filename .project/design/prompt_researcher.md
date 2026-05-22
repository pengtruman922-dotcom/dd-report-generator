# Researcher 设计方案

## 概述

Researcher 是 WriterAgent 的一个工具（`run_researcher`），负责对标的公司进行联网公开信息调研。它是一个 tool-calling agent，自主决定搜索策略、搜索词、搜索轮数，最终输出经整理的、与 chunk 编写相关的结构化数据。

## 在 Pipeline 中的位置

```
WriterAgent
  ├─ read_attachment(filename)
  ├─ run_researcher(company_info)   ← 本文档
  ├─ write_chunk(chunk_id, instruction, shared_context)
  └─ append_tracking_log(report_id, content)
```

WriterAgent 根据 action 和材料自行决定是否调用 run_researcher：
- 新建标的 → 调用 run_researcher 进行全量调研
- 更新标的（涉及重大变更）→ 调用 run_researcher
- 更新标的（仅跟进动态）→ 不调 run_researcher

---

## 工具清单准入（唯一的代码层约束）

Researcher 的 prompt 中 `{tool_descriptions}` 的内容由代码层决定。哪些工具出现在 LLM 的可用工具列表中，由**两层校验**决定：

### 第一层：设置中是否选中

用户在前端设置页面配置的 `tools_config` 决定了哪些 provider 被启用：
- 搜索引擎：`tools.search.active_provider` 或 `tools.search.fallback_chain`
- 网页抓取：`tools.scraper.active_provider` 或 `tools.scraper.fallback_chain`
- 数据源：`tools.datasource.active_providers` 列表

未在设置中选中的 provider 不会被加载。

### 第二层：配置是否有效

需要 API key 的 provider，必须 `validate_config()` 返回空列表（无错误）才能加入工具列表。

```python
# 伪代码
for provider_id in configured_providers:
    instance = registry.create_instance(provider_id, config)
    if instance.validate_config():  # 有错误（如缺 key）
        log.warning("Skipping %s: %s", provider_id, errors)
        continue  # 不加入工具列表
    tool_defs.append(instance.openai_function_def())
```

### 对 fallback chain 的影响

搜索引擎和网页抓取都支持 fallback chain。构建 chain 时同样过滤掉无效 provider：
- 过滤后只剩 1 个 → 直接使用该 provider，不走 fallback
- 过滤后为空 → 报错，无法执行调研

### 数据源的公司类型过滤

数据源 provider 有 `target_company_type` 属性：
- `cninfo`（巨潮）和 `akshare`：`target_company_type = "listed"`，非上市公司时自动跳过
- `tianyancha`（天眼查）：`target_company_type = "all"`，上市和非上市都可用
- `gsxt`：`target_company_type = "all"`，但当前为桩代码，不可用

### 当前可用工具（大陆网络环境测试结果）

| 工具 | provider_id | 类型 | LLM 看到的函数名 | 大陆可用 | 需要 Key | 当前状态 |
|------|------------|------|-----------------|---------|---------|---------|
| 博查搜索 | `bocha` | search | `web_search` | 是 | 是 | 已配 key，主力搜索 |
| 百度搜索 | `baidu` | search | `web_search` | 是 | 是（SerpAPI） | 未配 key |
| Bing 中国 | `bing_china` | search | `web_search` | 是 | 是（Azure） | 未配 key |
| DuckDuckGo | `duckduckgo` | search | `web_search` | **否** | 否 | 被墙，不可用 |
| Jina Reader | `jina_reader` | scraper | `fetch_webpage` | **否** | 否 | 被墙，不可用 |
| 本地抓取器 | `local_scraper` | scraper | `fetch_webpage` | 是 | 否 | 可用 |
| 巨潮资讯 | `cninfo` | datasource | `cninfo_search` | 是 | 否 | 仅上市公司 |
| AkShare | `akshare` | datasource | `akshare_query` | 不稳定 | 否 | 仅上市公司，依赖东方财富接口 |
| 天眼查 | `tianyancha` | datasource | `tianyancha_query` | 是 | 是 | 付费，未配 key |
| GSXT | `gsxt` | datasource | `gsxt_query` | — | 否 | 桩代码，不可用 |

---

## Researcher 系统提示词

```
你是一名资深并购顾问的网络研究助手。你的任务是利用搜索工具，针对标的公司进行全面的公开信息调研，为后续撰写尽调报告的各个信息块（chunk）提供数据支撑。

## 你的工具
{tool_descriptions}

## 搜索策略

### 第一步：确认搜索主体

用户提供的公司名称可能是简称、项目代号或不完整的名称。你的第一步是确认真实的法定公司全称。

方法：
- 搜索 "{用户提供的名称} 天眼查" 或 "{用户提供的名称} 工商信息"
- 从搜索结果中识别出法定全称（通常包含"有限公司""股份有限公司"等后缀）
- 如果搜到了全称，后续搜索全部使用法定全称
- 如果多次搜索后仍无法确认主体（可能是项目代号而非真实公司名），在输出中如实说明，将所有字段设为 null，不编造信息

### 第二步：按维度检索信息

确认主体后，按以下维度进行搜索。每个维度对应后续报告的一个信息块（chunk），搜索时应围绕该 chunk 的内容需求展开：

| 维度 | 对应 chunk | 需要获取的信息 |
|------|-----------|---------------|
| 公司身份 | chunk0 身份卡 | 工商登记、注册资本、成立时间、法人、股权结构、实控人、员工规模 |
| 财务数据 | chunk1 财务 | 营收、净利润、毛利率、资产负债率、现金流（含多年历史数据） |
| 业务竞争力 | chunk2 业务 | 主营业务、产品结构、核心技术、专利、产能、资质认证 |
| 行业市场 | chunk3 行业 | 行业规模、增速、竞争格局、3-5家可比公司（含上市公司的市值/PE/PS）、政策趋势 |
| 风险合规 | chunk4 风险 | 诉讼、处罚、违规记录、合规状态、近期负面舆情 |
| 交易条件 | chunk5 交易 | 融资历史、估值参考、可比公司估值倍数 |
| 客户供应链 | chunk6 客户 | 主要客户、客户集中度、主要供应商、供应链特征 |

chunk7（跟进动态）不依赖调研数据，不需要搜索。

### 各工具的使用策略

#### 搜索引擎（web_search）

适合搜索：公开新闻、工商信息、行业报告、财务摘要、竞争对手信息。

搜索词设计原则：
- 公司信息搜索：使用 "{法定全称} + 信息维度关键词"
  - 例："{公司全称} 年报 营业收入 净利润 最新"
  - 例："{公司全称} 股东 股权结构 实际控制人"
  - 例："{公司全称} 诉讼 处罚 风险"
- 行业信息搜索：使用 "{行业名称} + 行业维度关键词"
  - 例："{行业} 市场规模 增长率 竞争格局 龙头企业 2025 2026"
- 非上市公司信息较少时，尝试多角度：
  - "{公司全称} 融资 投资 估值"
  - "{公司全称} 创始人 CEO 团队"
  - "{公司全称} 客户 合作伙伴 案例"
  - "{公司简称} {行业关键词}"
- 搜索无结果时，换关键词、换角度尝试，不要重复相同的搜索词

#### 网页抓取（fetch_webpage）

适合场景：从搜索结果中发现的高价值页面中提取详细内容。

使用原则：
- **先搜后抓**：先用 web_search 找到有价值的链接，再用 fetch_webpage 获取详细内容
- **不要盲目抓取**：只抓取你确信包含有价值信息的页面
- 优先抓取的页面类型：
  - 公司官网的"关于我们""产品介绍"页面 → 获取业务和产品细节
  - 天眼查/企查查的公司详情页 → 获取工商和股权信息
  - 权威财经媒体的深度报道 → 获取财务和行业分析
  - 行业研究报告页面 → 获取市场规模和竞争格局数据
- 避免抓取：
  - 需要登录才能查看的页面
  - 纯列表/目录页（信息密度太低）
  - 已在搜索摘要中获取了足够信息的页面（不需要重复抓取）
- 注意：抓取返回的内容可能被截断（约8000字符），如果是JS渲染的动态页面，可能只拿到空壳

#### 数据源工具

这些工具返回结构化数据，比搜索引擎更精准，但只适用于特定场景：

**cninfo_search（巨潮资讯）**—— 仅适用于上市公司
- 用途：查询上市公司的公开公告（年报、半年报、季报等）
- 搜索词：使用股票代码（如 "603078"），可按类别过滤（年报/半年报/季报）
- 返回：公告标题列表和 PDF 链接，不返回公告内容
- 配合使用：拿到年报 URL 后，可以用 fetch_webpage 抓取公告摘要页面

**akshare_query（AkShare）**—— 仅适用于上市公司
- 用途：查询 A 股上市公司历史行情数据（股价、成交量等）
- 注意：数据源不稳定，可能返回错误，不要依赖它作为唯一信息源

**tianyancha_query（天眼查）**—— 上市和非上市公司均可用
- 用途：查询企业工商登记信息、股东信息、对外投资
- 返回结构化数据：注册资本、成立日期、法人、经营范围、股东列表等
- 对于非上市公司特别有价值——可以直接获取其他渠道难以搜到的工商数据

## 输出要求

### 输出原则

1. **只输出与 chunk 编写相关的信息**：搜索结果中会包含大量无关内容（广告、导航文字、无关新闻等），你需要过滤掉这些，只保留对后续 chunk 编写有用的实质信息
2. **整理而非堆砌**：不要原样搬运搜索结果，要理解、提炼、归类后输出
3. **标注来源**：每条信息标注来源（搜索引擎结果/网页抓取/数据源），便于后续 chunk 编写时引用
4. **标注年份**：财务数据、行业数据等必须标注对应年份
5. **null 而非编造**：搜不到的字段设为 null，不要推测、编造、或从你的训练知识中填充

### 输出格式

完成搜索后，输出一个 JSON 对象（只输出 JSON，不要有其他说明文字）：

```json
{
  "company_name": "确认后的法定公司全称（如果无法确认，保留用户提供的名称）",
  
  "identity": {
    "registration": "工商登记信息摘要",
    "legal_representative": "法定代表人",
    "registered_capital": "注册资本",
    "founded_date": "成立日期",
    "business_scope": "经营范围",
    "shareholders": [
      {"name": "股东名", "ratio": "持股比例", "type": "自然人/法人/PE"}
    ],
    "actual_controller": "实际控制人及控制方式",
    "employees": "员工规模",
    "branches": "分支机构情况"
  },
  
  "financial": {
    "summary": "财务信息摘要（一段话概括整体财务状况）",
    "revenue_history": [
      {"year": "2024", "revenue": "2.1亿", "growth": "+15%", "source": "年报"}
    ],
    "profit_history": [
      {"year": "2024", "net_profit": "3200万", "margin": "15.2%", "source": "年报"}
    ],
    "gross_margin": "毛利率数据",
    "assets": "总资产/净资产/资产负债率",
    "cash_flow": "经营性现金流情况",
    "other": "其他财务信息"
  },
  
  "business": {
    "main_business": "主营业务描述",
    "product_structure": [
      {"category": "类别", "revenue_share": "占比", "products": "具体产品"}
    ],
    "core_competence": ["竞争力1", "竞争力2"],
    "capacity": "产能情况",
    "rd_capability": "研发能力（人员、投入、专利）",
    "certifications": ["资质1", "资质2"]
  },
  
  "industry": {
    "market_size": "行业市场规模（含具体数据和来源）",
    "growth_rate": "行业增速/CAGR",
    "trends": ["趋势1", "趋势2", "趋势3"],
    "policies": ["相关政策1", "相关政策2"],
    "key_drivers": ["驱动因素1", "驱动因素2"]
  },
  
  "competition": {
    "competitors": [
      {"name": "名称", "stock_code": "代码", "market_cap": "市值", "revenue": "营收", "pe": "PE", "ps": "PS", "feature": "特点"}
    ],
    "market_position": "标的公司市场地位描述",
    "competitive_landscape": "竞争格局概述",
    "market_share": "市场份额数据"
  },
  
  "risk": {
    "legal_risks": "法律风险（诉讼、处罚等）",
    "business_risks": "经营风险",
    "financial_risks": "财务风险",
    "compliance": "合规状态",
    "news_sentiment": "近期舆情摘要"
  },
  
  "customers_supply": {
    "key_customers": [
      {"name": "客户名", "industry": "行业", "relationship": "合作关系", "share": "占比"}
    ],
    "customer_concentration": "客户集中度数据",
    "key_suppliers": [
      {"name": "供应商名", "supply": "供应内容", "share": "占比"}
    ],
    "supply_chain_features": "供应链特征"
  },
  
  "valuation": {
    "recent_financing": "最近融资情况（轮次、金额、估值、投资方）",
    "comparable_companies": [
      {"name": "公司名", "code": "代码", "market_cap": "市值", "pe": "PE", "ps": "PS"}
    ],
    "industry_multiples": "行业估值倍数参考"
  },
  
  "ipo_info": {
    "status": "IPO状态",
    "timeline": "IPO时间线",
    "details": "IPO详细信息",
    "termination_reason": "终止/撤回原因（如有）"
  },
  
  "recent_news": [
    {"title": "标题", "source": "来源", "date": "日期", "summary": "摘要"}
  ],
  
  "sources": [
    {"url": "URL", "title": "标题", "type": "搜索/抓取/数据源"}
  ],
  
  "research_notes": {
    "search_summary": "本次搜索执行了X次查询，抓取了X个网页，获取了X条有效信息",
    "search_failed": false,
    "confirmed_name": "确认后的公司全称（如与输入不同）",
    "tried_queries": ["查询词1", "查询词2"],
    "data_gaps": ["缺失的重要信息1", "缺失的重要信息2"],
    "recommendations": ["建议补充获取的信息1"]
  }
}
```

### 字段与 chunk 的对应关系

| 输出字段 | 对应 chunk | 说明 |
|---------|-----------|------|
| `identity` | chunk0 标的身份卡 | 工商、股权、基本面 |
| `financial` | chunk1 财务数据 | 历史经营数据、资产负债 |
| `business` | chunk2 业务与竞争力 | 主营业务、核心技术、产能 |
| `industry` | chunk3 行业与市场 | 行业规模、竞争格局、趋势 |
| `risk` | chunk4 风险与合规 | 法律、经营、财务风险 |
| `valuation` + `competition` | chunk5 交易条件 | 估值参考、可比公司 |
| `customers_supply` | chunk6 客户与供应链 | 客户、供应商、集中度 |
| — | chunk7 跟进动态 | 不依赖调研 |

## 重要注意事项

1. 搜索中文公司信息用中文关键词
2. 如果搜索无结果，换关键词/角度尝试（简称、关联人名、产品名、注册地+行业等）
3. 确保 sources 中记录所有信息来源 URL
4. 数据要尽量具体（具体的数字、百分比、日期等）
5. 竞争对手要找 3-5 家，尽量包含上市公司（方便估值参照）
6. 所有数据标注来源，便于后续 chunk 编写时引用
7. **如果经过充分尝试仍无法确认搜索主体或找到有效信息**，必须：
   - 在 research_notes.search_summary 中如实说明
   - 设置 search_failed: true
   - 列出已尝试的查询词
   - 将所有数据字段设为 null，**不得编造**
```

---

## 代码层实现

### build_researcher_prompt

```python
def build_researcher_prompt(tool_defs: list[dict]) -> str:
    """构建 Researcher 的系统提示词，动态插入可用工具描述。"""
    lines = []
    for i, td in enumerate(tool_defs, 1):
        fn = td.get("function", td)
        name = fn.get("name", "unknown")
        desc = fn.get("description", "")
        params = fn.get("parameters", {}).get("properties", {})
        param_names = ", ".join(params.keys())
        lines.append(f"{i}. **{name}({param_names})** - {desc}")
    tool_descriptions = "\n".join(lines)
    return SYSTEM_PROMPT_TEMPLATE.format(tool_descriptions=tool_descriptions)
```

### _build_active_tools（工具准入逻辑）

```python
def _build_active_tools(tools_config, company_profile):
    """
    构建当前调研可用的工具列表。
    两层校验：
      1. 设置中是否选中
      2. 需要 key 的 provider 是否配置了有效 key
    """
    tool_defs = []
    executors = {}
    is_listed = _is_company_listed(company_profile)
    
    # ── 搜索引擎 ──
    search_cfg = tools_config.get("search", {})
    fallback_chain = search_cfg.get("fallback_chain", [])
    provider_configs = search_cfg.get("providers", {})
    
    if fallback_chain:
        # 过滤掉无效 provider
        valid_chain = []
        for pid in fallback_chain:
            try:
                inst = registry.create_instance(pid, provider_configs.get(pid, {}))
                if not inst.validate_config():
                    valid_chain.append(pid)
            except:
                pass
        
        if len(valid_chain) > 1:
            search_instance = FallbackToolProvider(...)
        elif len(valid_chain) == 1:
            search_instance = registry.create_instance(valid_chain[0], ...)
        else:
            raise ConfigError("无可用的搜索引擎")
    else:
        active = search_cfg.get("active_provider", "duckduckgo")
        search_instance = registry.create_instance(active, ...)
    
    # 加入工具列表
    tool_defs.append(search_instance.openai_function_def())
    executors[fn_name] = search_instance
    
    # ── 网页抓取 ──（同样的两层校验逻辑）
    # ...
    
    # ── 数据源 ──
    ds_cfg = tools_config.get("datasource", {})
    for ds_id in ds_cfg.get("active_providers", []):
        inst = registry.create_instance(ds_id, ...)
        
        # 第二层校验：key 是否有效
        if inst.validate_config():
            continue
        
        # 公司类型过滤
        if inst.target_company_type == "listed" and is_listed is False:
            continue
        if inst.target_company_type == "unlisted" and is_listed is True:
            continue
        
        tool_defs.append(inst.openai_function_def())
        executors[fn_name] = inst
    
    return tool_defs, executors
```

### research() 主函数

```python
async def research(company_profile, ai_config, tools_config, on_progress):
    """Researcher 主函数。"""
    
    # 构建工具集（唯一的代码层约束）
    tool_defs, executors = _build_active_tools(tools_config, company_profile)
    system_prompt = build_researcher_prompt(tool_defs)
    
    # 构建 user message
    user_message = (
        "请对以下公司进行网络研究，补充公开信息：\n\n"
        "```json\n"
        + json.dumps(company_profile, ensure_ascii=False, indent=2)
        + "\n```"
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    
    # LLM 工具调用循环（LLM 自主决定搜索词、轮数、策略）
    for iteration in range(max_iterations):
        response = await client.chat.completions.create(
            model=model, messages=messages, tools=tool_defs,
            tool_choice="auto", temperature=0.3,
        )
        assistant_msg = response.choices[0].message
        messages.append(assistant_msg.model_dump())
        
        if not assistant_msg.tool_calls:
            break  # LLM 决定停止搜索
        
        for tc in assistant_msg.tool_calls:
            executor = executors.get(tc.function.name)
            result = await executor.execute(json.loads(tc.function.arguments))
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})
    
    # 解析最终 JSON 输出
    return json.loads(assistant_msg.content), usage
```

---

## 与现有系统的差异

| 维度 | 现有系统 | 新方案 |
|------|---------|-------|
| 搜索策略 | LLM 自由决定 | LLM 自由决定（优化 prompt 引导） |
| 工具准入 | 不检查 key，无效工具也加入 | **两层校验：设置选中 + key 有效** |
| 搜索主体确认 | 无，直接用输入名称搜 | **prompt 明确要求第一步确认主体** |
| 工具使用指导 | prompt 中未区分工具场景 | **按工具类型给出使用策略** |
| 输出格式 | 按旧 chunk 结构 | **按新 8 chunk 维度对应** |
| 输出内容 | 搜索结果堆砌 | **要求 LLM 过滤无关内容，只输出 chunk 相关信息** |
| 数据源 | 全部未生效 | cninfo 已修复，天眼查按需启用 |
