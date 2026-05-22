# Intake 环节功能设计方案

## 概述

Intake 是用户输入进入系统的唯一入口。它是一个"分拣员"，不是"分析师"——负责理解输入、识别标的、分类内容、匹配查重，然后把材料分发给下游 Pipeline 处理。

整个 Intake 环节由**两个 Agent + 代码层**协作完成：
- **IntakeAgent**：多模态理解，识别标的、生成摘要、关联输入材料、图片内容提取
- **MatcherAgent**：对 IntakeAgent 识别出的公司名与已有标的库做模糊匹配，判断新建/更新
- **代码层**：文件解析、合并结果、用户确认流程、附件关联存储、分发材料到 WriterAgent

---

## 完整流程

```
用户上传（文本 + 图片 + 文档 + URL）
  │
  ▼
Step 0: 代码层 — 文件解析
  将上传的附件解析为文本或 base64，存储到 upload_session
  │
  ▼
Step 1: IntakeAgent（LLM 调用 #1，多模态）
  输入：解析后的全部内容（文本块 + 文档文本 + 图片 base64 + 网页文本）
  输出：识别出的标的列表，每个标的包含：
    - project_name（标的项目名称）
    - update_summary（简单摘要）
    - related_inputs（关联的输入材料）
  注意：不做结构化字段提取，不判断新建/更新
  │
  ▼
Step 2: MatcherAgent（LLM 调用 #2，纯文本）
  输入：Step1 输出的 project_name 列表 + 已有标的库全量（company_name + industry）
  输出：每个名称的匹配结果（create/update + matched_report_id + matched_name）
  │
  ▼
Step 3: 代码层 — 合并结果
  将 IntakeAgent 的 items 与 MatcherAgent 的匹配结果合并
  生成完整的确认数据
  │
  ▼
Step 4: 前端确认弹窗
  展示每个标的：名称(可编辑) | 新建/更新(可切换) | 摘要 | 关联附件
  用户可修改名称、切换 action、取消勾选
  │
  ▼
Step 5: 代码层 — 分发 + 附件关联
  - 按标的拆分，将每个标的的关联材料打包传给独立 WriterAgent（并行）
  - 将关联的附件文件复制到 reports/{report_id}/attachments/
  - 附件信息写入 reports 表的 attachments 列（JSON）
```

---

## Step 0: 文件解析

### 支持的文件格式

| 格式 | 解析方式 | 输出 | LLM 传递格式 |
|------|---------|------|-------------|
| PDF | PyMuPDF → pdfplumber → RapidOCR 三级降级 | 纯文本 | `【文档：{filename}】\n{text}` |
| DOCX | python-docx（段落 + 表格 + 嵌入图片 OCR） | 纯文本 | `【文档：{filename}】\n{text}` |
| PPTX | python-pptx（幻灯片 + 表格 + 图片 OCR） | 纯文本 | `【文档：{filename}】\n{text}` |
| Excel | openpyxl 逐 sheet 读取，表格转文本 | 纯文本 | `【文档：{filename}】\n{text}` |
| 图片 | 保留原始 bytes | base64 | `【图片：{filename}】` + image_url 块 |
| MD/TXT | 直接读取 | 纯文本 | `【文档：{filename}】\n{text}` |
| URL | Jina Reader / 本地 scraper | 纯文本 | `【网页：{url}】\n{text}` |

### Excel 文本提取（Intake 场景新增）

现有 `excel_parser.py` 的 `parse_excel()` 是面向结构化数据录入的（输出 `list[dict]`）。Intake 场景需要新增：

```python
def extract_excel_text(file_path: str) -> str:
    """将 Excel 转为可读文本，供 IntakeAgent 理解内容。"""
    # 逐 sheet 读取，格式：
    # [Sheet: 财务数据]
    # 年份 | 营收(万元) | 净利润(万元)
    # 2024 | 21000 | 3200
    # 2023 | 18300 | 2600
    # ...
```

### 解析内容存储

```python
parsed_inputs = {
    "text": "用户输入的自由文本",
    "documents": [
        {"filename": "某某科技介绍.pdf", "content": "解析后的文本...", "type": "pdf"},
        {"filename": "项目汇报.pptx", "content": "解析后的文本...", "type": "pptx"},
        {"filename": "标的清单.xlsx", "content": "解析后的文本...", "type": "excel"}
    ],
    "images": [
        {"filename": "截图1.png", "bytes": b"...", "mime": "image/png"}
    ],
    "urls": [
        {"url": "https://example.com", "content": "抓取后的文本..."}
    ]
}
```

此结构存储在 upload_session 中，整个 Intake 流程复用。

---

## Step 1: IntakeAgent

### 职责

- 从多模态输入中识别所有涉及的标的
- 为每个标的生成简要更新摘要
- 标注每个标的关联了哪些输入源
- 对文本类输入：去噪，保留原始实质内容
- 对图片输入：利用多模态能力提取图片内容为文本
- **不做**结构化字段提取（由 Writer 完成）
- **不判断**新建/更新（由 MatcherAgent 完成）

### IntakeAgent 是多模态网关

IntakeAgent 是整个系统中唯一处理图片的环节。它利用多模态模型的能力将图片内容转为文本描述，下游所有 Agent（WriterAgent、Researcher）只处理文本。

### 系统提示词

```
你是一个专业的企业标的信息分拣助手。你的任务是从用户提交的��类材料中识别「被投/被收购标的」，并整理归类相关材料。

## 你的核心任务

1. **识别标的**：从所有输入材料中识别涉及的标的项目（可能有多个）
2. **生成摘要**：为每个标的的本次输入内容写一句简要摘要
3. **关联材料**：标注每个标的关联了哪些输入源
4. **整理内容**：
   - 文本输入：去掉噪音（寒暄、签名、无关讨论），保留与标的相关的原始实质内容
   - 图片输入：提取图片中的关键信息，转为文字描述

你**不需要**提取结构化字段（如营收、行业、地区等），也**不需要**判断是新建还是更新。

## 标的识别规则

### 只识别「标的」公司，不识别买方/合作方

材料通常是投行/FA工作进展汇报，其中会出现多种角色：
- **标的（被投/被收购方）**：我方正在推介、尽调、谈判的项目 → **需要识别**
- **买方/投资方**：潜在购买者、投资机构、央企、上市公司 → **不识别**
- **合作方/中介**：律所、会计师事务所、供应商等 → **不识别**

**买方信号词**：
- "联系了XX投资部""XX表示需内部研究"
- "寻找买方""已接触XX""向XX推介"
- "XX进场""XX参与竞购""匹配买方""拓展买方"
- "XX投资集团""XX基金"等大型机构名

**标的信号词**：
- "XX项目""推进XX项目""XX进展"
- "与项目方见面""项目尽调"
- 公司介绍文档中的主体公司

### 标的项目名称（project_name）

- 通常情况：标的项目名 = 公司名称（如"某某科技有限公司"）
- 特殊情况：某公司出售旗下部分业务时，标的项目名 = "XX公司XX业务"（如"某集团新能源业务板块"）
- 如果能识别出完整的公司名称，尽量使用全称

### 一个文档包含多个标的

一份文档（如项目周报、工作汇报PPT）可能涉及多个标的。此时：
- 识别出所有涉及的标的
- 每个标的的 related_inputs.attachments 都包含该文档的文件名
- 不需要拆分文档内容

## 输出格式

严格输出以下 JSON 格式，不要有任何额外说明：

```json
{
  "items": [
    {
      "project_name": "某某科技有限公司",
      "update_summary": "输入标的基础信息，包含公司介绍和近三年财务数据",
      "related_inputs": {
        "attachments": ["某某科技介绍.pdf", "财务报表.xlsx"],
        "text": "整理后的文本原始内容（去噪后）",
        "image_content": "从图片中提取的信息：某某科技厂区照片，可见3条生产线..."
      }
    },
    {
      "project_name": "另一家环保公司",
      "update_summary": "新增标的跟进情况，报价及谈判进展",
      "related_inputs": {
        "attachments": ["项目周报.pptx"],
        "text": "另一家环保公司：已向A集团推介，报价3亿，董事长表示6月后再谈",
        "image_content": ""
      }
    }
  ],
  "summary": "本次识别到2个标的项目"
}
```

如果材料中没有任何有效标的信息，返回：
```json
{"items": [], "summary": "未识别到有效企业标的信息"}
```

## 关键注意事项

1. **related_inputs.text 必须保留原始实质内容**：去掉噪音（寒暄、无关讨论），但保留所有与标的相关的实质信息原文，不要摘要、不要改写。
2. **related_inputs.image_content**：利用你的多模态能力，将图片中的信息提取为文字。包括：表格数据、文字内容、图表中的数据点等。如果图片与标的无关（如风景照、头像），忽略。
3. **related_inputs.attachments 只填文件名**：如"某某科技介绍.pdf"，不需要包含文件内容。
4. **update_summary 要简洁**：一句话概括本次输入涉及什么内容（如"输入标的基础信息""新增跟进情况""标的财务数据变更"），不需要具体数据。
5. **同一标的的多种内容不拆分**：如果输入中同时包含某标的的基本信息和跟进动态，合并为一个 item，在 update_summary 中说明（如"输入标的基础信息及跟进情况"）。由下游 Agent 自行判断处理路径。
6. **一个附件可被多个标的引用**：各自的 attachments 中都列出该文件名。
```

### IntakeAgent 调用方式

OpenAI-compatible chat completion，多模态模式（支持 image_url 内容块）。

system message = 上述提示词
user message = 多模态内容块列表：
```
【文字内容】\n{text_input}                              // 如有
【文档：{filename}】\n{doc_text[:8000]}                   // 每个解析后的文档
【网页：{url}】\n{content[:6000]}                         // 每个抓取的网页
【图片：{filename}】 + {"type":"image_url","image_url":{"url":"data:..."}}  // 每张图片
```

温度设置：`temperature=0.1`

---

## Step 2: MatcherAgent

### 职责

接收 IntakeAgent 识别出的标的项目名称列表，与已有标的库做模糊匹配，判断每个标的是新建还是更新。

### 系统提示词

```
你是一个企业名称匹配助手。你的任务是判断一组待查项目名称是否已存在于标的库中。

## 已���标的库
{existing_targets_list}

（格式：每行一条，report_id | company_name | industry）

## 待匹配项目
{projects_to_match}

## 匹配规则

1. **模糊匹配**：忽略以下差异：
   - 公司后缀："有限公司""股份有限公司""有限责任公司""集团"等
   - 括号内地名："XX科技（深圳）有限公司"中的"（深圳）"
   - 空格和标点差异

2. **简称匹配**：常见简称视为匹配：
   - "华为" ↔ "华为技术有限公司"
   - 但需确认是同一主体，"比亚迪电子" ≠ "比亚迪汽车"

3. **业务板块匹配**：如果项目名称是"XX公司XX业务"形式，匹配标的库中的"XX公司"
   - "某集团新能源业务" → 匹配标的库中的"某集团"或"某集团新能源"

4. **行业辅助判断**：名称相似但不完全匹配时，参考行业是否一致

5. **保守原则**：不确定时倾向于"新建"，避免错误更新

## 输出格式

严格输出以下 JSON 格式，不要有任何额外说明：

```json
{
  "results": [
    {
      "input_name": "某某科技",
      "action": "create",
      "matched_report_id": null,
      "matched_name": null,
      "confidence": "high",
      "reason": "标的库中无匹配记录"
    },
    {
      "input_name": "华为",
      "action": "update",
      "matched_report_id": "report_xxx",
      "matched_name": "华为技术有限公司",
      "confidence": "high",
      "reason": "简称匹配，行业一致"
    }
  ]
}
```

字段说明：
- input_name：IntakeAgent 输出的原始项目名称
- action：create（新建）或 update（更新）
- matched_report_id：匹配到的 report_id（新建为 null）
- matched_name：标的库中的完整名称（新建为 null，前端展示用）
- confidence：匹配信心 high / medium / low（medium/low 时前端可高亮提醒用户确认）
- reason：简要说明匹配或不匹配的依据
```

### MatcherAgent 调用方式

单次 chat completion，纯文本，无需多模态。

```python
system_message = MATCHER_SYSTEM_PROMPT.format(
    existing_targets_list=format_targets_list(all_targets),
    projects_to_match="\n".join([item["project_name"] for item in intake_items])
)
user_message = "请对以上待匹配项目进行查重判断。"
```

---

## Step 3: 代码层合并

```python
def merge_intake_and_matcher(intake_items, matcher_results):
    """合并 IntakeAgent 和 MatcherAgent 的输出。"""
    matcher_map = {r["input_name"]: r for r in matcher_results}

    merged = []
    for item in intake_items:
        match = matcher_map.get(item["project_name"], {})
        merged.append({
            "project_name": item["project_name"],
            "action": match.get("action", "create"),
            "matched_report_id": match.get("matched_report_id"),
            "matched_name": match.get("matched_name"),
            "match_confidence": match.get("confidence", "low"),
            "match_reason": match.get("reason", ""),
            "update_summary": item["update_summary"],
            "related_inputs": item["related_inputs"],
            # 展示用名称：更新时用标的库的标准名称，新建时用识别出的名称
            "display_name": match.get("matched_name") or item["project_name"]
        })
    return merged
```

---

## Step 4: 前端确认弹窗

### API 返回数据结构

`POST /api/intake/parse` 返回：

```json
{
  "items": [
    {
      "id": "temp_001",
      "project_name": "某某科技",
      "display_name": "某某科技有限公司",
      "action": "update",
      "match_confidence": "high",
      "match_reason": "全称匹配",
      "matched_report_id": "report_xxx",
      "update_summary": "输入标的基础信息（公司介绍、财务概况）",
      "related_inputs": {
        "attachments": ["某某科技介绍.pdf"],
        "text": "...",
        "image_content": "..."
      }
    }
  ],
  "summary": "本次识别到2个标的项目，其中1个新建、1个更新",
  "session_id": "upload_session_xxx"
}
```

### 确认弹窗 UI

```
┌──────────────────────────────────────────────────────┐
│ 识别结果确认                           [自动/手动确认] │
├──────────────────────────────────────────────────────┤
│                                                      │
│ ☑ [某某科技有限公司    ]                    [更新 ▼]  │
│   匹配信心：高 — 全称匹配                             │
│   摘要：输入标的基础信息（公司介绍、财务概况）          │
│   附件：某某科技介绍.pdf                              │
│                                                      │
│ ☑ [新新能源公司        ]                    [新建 ▼]  │
│   匹配信心：—                                        │
│   摘要：新增标的跟进情况，报价及谈判进展               │
│   附件：项目周报.pptx                                │
│                                                      │
├──────────────────────────────────────────────────────┤
│                           [取消]    [确认执行]         │
└──────────────────────────────────────────────────────┘
```

用户可操作项：
- ☑ / ☐ 勾选或取消某个标的
- 编辑名称：点击名称文本框直接修改
- 切换 action：新建 ↔ 更新（下拉框）
- match_confidence 为 medium/low 时，名称或 action 旁显示警示标记

### 确认提交

`POST /api/intake/execute`

```json
{
  "session_id": "upload_session_xxx",
  "confirmed_items": [
    {
      "id": "temp_001",
      "project_name": "某某科技有限公司",
      "action": "update",
      "matched_report_id": "report_xxx"
    }
  ]
}
```

---

## Step 5: 分发到 WriterAgent + 附件关联

### 分发逻辑

```python
async def dispatch_to_pipelines(confirmed_items, parsed_inputs, session_id):
    tasks = []
    for item in confirmed_items:
        # 构建 WriterAgent 输入
        writer_input = build_writer_agent_input(item, parsed_inputs)
        # 附件关联：复制文件到报告目录，写入 DB
        await associate_attachments(item, parsed_inputs, session_id)
        # 启动独立 Pipeline（WriterAgent → 字段回填 → 评级 → 推送）
        tasks.append(asyncio.create_task(run_pipeline(writer_input)))

    await asyncio.gather(*tasks, return_exceptions=True)
```

### WriterAgent 输入结构

```python
def build_writer_agent_input(item, parsed_inputs):
    related = item["related_inputs"]
    return {
        # 标的基本信息
        "project_name": item["project_name"],
        "action": item["action"],
        "matched_report_id": item.get("matched_report_id"),
        "update_summary": item["update_summary"],

        # 关联材料（完整内容）
        "materials": {
            # 附件：文件名列表（WriterAgent 通过工具按需读取完整内容）
            "attachment_files": related["attachments"],
            # 文本：IntakeAgent 整理后的去噪原始文本
            "text": related["text"],
            # 图片内��：IntakeAgent 多模态提取后的文字
            "image_content": related["image_content"]
        }
    }
```

**关键设计**：
- **附件只传文件名**：WriterAgent/Writer 通过工具（如 `read_attachment(filename)`）按需读取完整内容。避免在 WriterAgent 的上下文中塞入大量附件文本
- **一个附件被多标的关联时**：代码层将文件复制到每个标的的附件目录
- **文本和图片内容已整理**：IntakeAgent 已去噪（文本）和提取（图片），WriterAgent 直接使用

### 附件关联存储

```python
async def associate_attachments(item, parsed_inputs, session_id):
    """将关联附件复制到报告目录，写入 DB。"""
    report_id = item.get("matched_report_id") or create_new_report_id()
    attachments_dir = f"outputs/{report_id}/attachments"
    os.makedirs(attachments_dir, exist_ok=True)

    attachment_records = []
    for filename in item["related_inputs"]["attachments"]:
        # 从 upload session 复制原始文件
        src = f"uploads/{session_id}/{filename}"
        dst = f"{attachments_dir}/{filename}"
        shutil.copy2(src, dst)
        attachment_records.append({
            "filename": filename,
            "path": dst,
            "uploaded_at": datetime.now().isoformat()
        })

    # 写入 DB（追加到现有附件列表，不覆盖）
    update_report_attachments(report_id, attachment_records)
```

前端标的详情页可从 reports 表的 `attachments` 列读取文件列表，提供下载。

---

## 数据流总览

```
用户上传
  │
  ▼
parsed_inputs = {text, documents[], images[], urls[]}       ← 代码解析
  │
  ▼
IntakeAgent(parsed_inputs)                                  ← LLM #1（多模态）
  → {items: [{project_name, update_summary, related_inputs}]}
  │  注意：related_inputs.text 是去噪后原文
  │        related_inputs.image_content 是图片提取的文字
  │        related_inputs.attachments 只有文件名
  │
  ▼
MatcherAgent(items[].project_name, existing_targets)         ← LLM #2（纯文本）
  → {results: [{input_name, action, matched_report_id, matched_name, confidence}]}
  │
  ▼
代码合并 → merged_items[]（含 action、display_name 等）
  │
  ▼
前端确认弹窗（可编辑名称、切换 action、勾选）
  → confirmed_items[]
  │
  ▼
代码分发：for each confirmed_item:
  ├─ associate_attachments()           ← 文件复制 + DB 关联
  └─ build_writer_agent_input()       ← 组装材料
     → run_pipeline(input)            ← 并行执行（WriterAgent → 字段回填 → 评级 → 推送）
```

---

## WriterAgent 需要的工具（参见 prompt_writer_agent.md）

由于附件只传文件名，WriterAgent 需要一个工具来读取附件内容：

```
read_attachment(filename: str)
  → 附件的完整解析文本（从 attachments_dir 读取并解析）
  → 如果是 PDF/DOCX/PPTX/Excel，返回解析后的文本
  → 如果是图片，返回"请参考 materials.image_content"（图片已由 IntakeAgent 提取）
```

WriterAgent 的完整工具清单和工作流程详见 `prompt_writer_agent.md`。
