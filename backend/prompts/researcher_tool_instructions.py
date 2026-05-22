"""Tool-specific prompt instructions for the Researcher agent.

Only instructions for tools enabled in the current settings should be appended
to the researcher system prompt.
"""

TOOL_PROMPT_INSTRUCTIONS: dict[str, str] = {
    "web_search": """### web_search
用途：搜索公开网页、新闻、官网入口、工商摘要、公告入口等。
使用约束：
- 优先短查询；每次查询只围绕一个目标。
- 不要在查询词中主动加入具体年份，除非用户输入或已确认来源需要。
- 搜索结果主要作为线索，关键事实优先用网页抓取或数据源工具验证。
- 搜索结果质量差时，记录到 noise_or_excluded，不要反复使用相近关键词。""",
    "fetch_webpage": """### fetch_webpage
用途：读取搜索结果中的网页正文。
使用约束：
- 先搜索，再抓取；只抓取高价值页面。
- 官网首页信息不足时，可以在同一官网域名内下钻 1-2 层。
- 官网下钻优先读取：关于我们、公司简介、产品中心、业务介绍、投资者关系、新闻中心、联系我们。
- 不要抓取明显无关、登录受限、广告、导航或纯列表页面。
- 抓取内容可能被截断，无法确认的信息写 unknown。""",
    "cninfo_search": """### cninfo_search
用途：查询 A 股上市公司公告、年报、半年报、季报等。
使用约束：
- 仅在确认上市主体或股票代码后使用。
- 优先查找最新年报、半年报、重大公告入口。
- 不要自行推导财务数据；只记录公告中可验证的信息或公告入口。""",
    "akshare_query": """### akshare_query
用途：查询 A 股行情或基础证券数据。
使用约束：
- 仅作为资本市场事实辅助来源。
- 不用于推导交易估值、投资判断或推荐结论。""",
    "tianyancha_query": """### tianyancha_query
用途：查询企业工商、股东、对外投资等结构化信息。
使用约束：
- 适合确认法定主体、注册资本、成立日期、注册地址、股东等信息。
- 与搜索结果冲突时，需要标注冲突和置信度。""",
    "gsxt_query": """### gsxt_query
用途：查询国家企业信用信息公示系统相关企业信息。
使用约束：
- 适合确认工商身份、登记状态、基础注册信息。
- 如果无法抓取或信息不完整，写 unknown，不要用经验补全。""",
}
