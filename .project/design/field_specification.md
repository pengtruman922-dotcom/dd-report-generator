# DD Report Generator 字段说明表

> 本文档包含系统所有字段的完整说明，分为「首页展示字段」和「已移除字段」两部分。
> 版本：v3.0  |  更新时间：2026-04-15

---

## 一、首页展示字段

### 默认可见字段（14 列）

| # | 字段名（key） | 显示名称 | 类型 | 数据来源 | 说明 |
|---|------------|---------|------|---------|------|
| 1 | `bd_code` | 标的编码 | TEXT | 系统自动生成 | 格式 BD00001，自增序列，全局唯一标识 |
| 2 | `project_name` | 标的项目 | TEXT | IntakeAgent 提取 | 标的项目名称，是识别新建/更新的核心字段。**可点击跳转到报告详情**。通常是公司简称或项目代号 |
| 3 | `company_name` | 标的主体 | TEXT | IntakeAgent 提取 | 法定公司全称。与 project_name 可能不同（如 project_name="好当家"，company_name="山东好当家海洋发展股份有限公司"） |
| 4 | `industry` + `industry_tags` | 行业 | TEXT | IntakeAgent 提取 / WriterAgent chunk3 回填 | 合并展示。`industry` 为主行业（如"新能源发电运营"），`industry_tags` 为细分标签（如"风电,光伏"），标签以 `#` 前缀胶囊形式展示 |
| 5 | `feasibility_rating` | 可行性评级 | TEXT | RatingAgent 生成 | 并购可行性评级：A（高度可行）/ B（较为可行）/ C（一般可行）/ D（可行性低）/ E（不可行/已终止）。支持手动覆盖下拉。评级变更需用户确认 |
| 6 | `feasibility_rating_at` | 评级时间 | TEXT | RatingAgent 生成 | 最近一次 AI 评级的时间。格式 YYYY-MM-DD |
| 7 | `status` | 报告生成状态 | TEXT | Pipeline 管理 | 可选值：`completed`（已完成）/ `updated`（已更新，可点击确认）/ `generating`（生成中）/ `failed`（失败）。实时任务显示：生成中⟳、更新中⟳、排队中、终止中 |
| 8 | `referral_status` | 推介情况 | TEXT | Excel 导入 / 用户填写 | 项目的推介状态和跟进情况。原始文本，来自 BD 系统或用户手动输入 |
| 9 | `revenue` | 营业收入 | TEXT | IntakeAgent 提取 / WriterAgent chunk1 回填 | 最新年度营业收入。显示时若有 `revenue_yuan`（纯数字），自动格式化为"X亿"或"X万" |
| 10 | `offer_yuan` / `valuation_yuan` | 报价/估值 | TEXT | WriterAgent chunk5 回填 / 用户手动 | **合并展示**：优先显示报价（`offer_yuan`），无报价则显示估值（`valuation_yuan`，带 * 标记区分）。金额自动格式化（≥1亿显示"X.XX亿"，≥1万显示"X万"） |
| 11 | `offer_date` / `valuation_date` | 报价/估值时间 | TEXT | 同上 | 报价或估值对应的时间，精确到月（YYYY-MM）。当报价/估值为 "--" 时，此字段也显示 "--" |
| 12 | `attachments` | 附件 | JSON | 智能录入上传 | 关联附件文件列表（PDF/DOCX/PPTX/Excel/图片）。显示附件数量，可展开查看文件列表 |
| 13 | `push_status` | 推送状态 | 计算字段 | 系统判断 | FastGPT 知识库推送状态：`无索引`（无 chunk 数据）/ `未推送` / `已推送` / `需更新`（报告已更新但未重新推送） |
| 14 | `updated_at` | 更新时间 | TEXT | 系统自动维护 | 标的信息最近一次更新的时间。包括 AI 生成报告、手动编辑字段、评级变更等任何变更 |

### 默认隐藏字段（可通过列配置开启）

| 字段名（key） | 显示名称 | 类型 | 说明 |
|------------|---------|------|------|
| `net_profit` | 净利润 | TEXT | 最新年度净利润。有 `net_profit_yuan` 时自动格式化 |
| `province` | 省 | TEXT | 公司注册/总部所在省份 |
| `city` | 市 | TEXT | 公司所在城市 |
| `district` | 区 | TEXT | 公司所在区 |
| `is_listed` | 上市情况 | TEXT | "已上市" 或 "未上市" |
| `stock_code` | 上市编号 | TEXT | 股票代���，如 "603078.SH" |
| `website` | 官网地址 | TEXT | 公司官网 URL |
| `description` | 标的描述 | TEXT | 一句话描述标的项目 |
| `dept_primary` | 负责人主属部门 | TEXT | BD 系统中的负责人部门 |
| `dept_owner` | 归属部门 | TEXT | BD 系统中的归属部门 |
| `estimated_cost` | 预估成本 | REAL | 本次报告生成的预估 API 费用（元） |

---

## 二、已移除字段

以下字段在 v3.0 中从首页列表移除。数据库中仍保留这些字段（兼容旧数据），但不在前端展示。

| 字段名（key） | 原显示名称 | 移除原因 |
|------------|---------|---------|
| `score` | 评分 | v3 的 WriterAgent 不再生成 0-10 投资评分。被 `feasibility_rating`（A-E 可行性评级）替代 |
| `rating` | 评级 | 与 score 配套的投资建议评级（强烈推荐/推荐/谨慎推荐/不推荐/不建议），v3 不再生成 |
| `manual_rating` | 人工评级 | 与旧 rating 配套的手动覆盖字段。v3 的手动覆盖直接作用在 `feasibility_rating` 上 |
| `manual_rating_note` | 人工评级备注 | 同上 |
| `file_size` | 大小 | v3 报告格式为 8 chunk 独立存储（不生成整篇 MD 文件），文件大小不再有意义 |
| `token_usage_json` | Token 用量 | 移到隐藏字段或后台查看。前端不再默认展示 |
| `is_traded` | 是否已交易 | 低频使用字段，移��以简化界面 |
| `company_intro` | 公司简介 | 信息已包含在 chunk2（业务与竞争力）中，不需要在列表展示 |
| `remarks` | 备注 | 低频使用字段，移除以简化界面 |
| `created_at` | 生成日期 | 被 `updated_at`（更新时间）替代。首次创建时 updated_at = created_at |
| `industry_tags` | 行业标签 | 已合并到 `industry` 列中展示（以 # 胶囊标签形式） |

---

## 三、数据库字段完整清单

以下为 `reports` 表的全部字段（含首页展示、隐藏、已移除的所有字段）：

### 核心标识
| 字段 | 类型 | 说明 |
|------|------|------|
| `report_id` | TEXT PK | 报告唯一标识（UUID 前12位） |
| `bd_code` | TEXT | 标的编码（BD00001 格式） |
| `company_name` | TEXT | 法定公司全称 |
| `project_name` | TEXT | 标的项目名称 |

### 基本信息
| 字段 | 类型 | 说明 |
|------|------|------|
| `industry` | TEXT | 所属行业 |
| `industry_tags` | TEXT | 行业标签（逗号分隔） |
| `province` | TEXT | 省 |
| `city` | TEXT | 市 |
| `district` | TEXT | 区 |
| `is_listed` | TEXT | 上市情况 |
| `stock_code` | TEXT | 股票代码 |
| `website` | TEXT | 官网地址 |

### 财务与估值
| 字段 | 类型 | 说明 |
|------|------|------|
| `revenue` | TEXT | 营业收入（文字描述，如"2.1亿"） |
| `revenue_yuan` | TEXT | 营业收入（纯数字，单位元） |
| `net_profit` | TEXT | 净利润（文字描述） |
| `net_profit_yuan` | TEXT | 净利润（纯数字，单位元） |
| `valuation_yuan` | TEXT | 估值（纯数字，单位元） |
| `valuation_date` | TEXT | 估值日期 |
| `offer_yuan` | TEXT | 报价（纯数字，单位元）⭐ v3.0 新增 |
| `offer_date` | TEXT | 报价日期 ⭐ v3.0 新增 |

### 业务描述
| 字段 | 类型 | 说明 |
|------|------|------|
| `description` | TEXT | 标的项目一句话描述 |
| `company_intro` | TEXT | 公司简介 |
| `referral_status` | TEXT | 推介情况 |
| `is_traded` | TEXT | 是否已交易 |

### 评级（v3.0）
| 字段 | 类型 | 说明 |
|------|------|------|
| `feasibility_rating` | TEXT | 可行性评级（A/B/C/D/E）⭐ v3.0 新增 |
| `feasibility_rating_detail` | TEXT | 评级详情 JSON（四维度+reasoning+key_factors）⭐ v3.0 新增 |
| `feasibility_rating_at` | TEXT | 评级时间 ⭐ v3.0 新增 |
| `pending_rating_change` | TEXT | 待确认的评级变更 JSON ⭐ v3.0 新增 |

### 评级（旧版，v3.0 已停用）
| 字段 | 类型 | 说明 |
|------|------|------|
| `score` | REAL | 投资评分（0-10）—— v3.0 不再生成 |
| `rating` | TEXT | 投资建议评级 —— v3.0 不再生成 |
| `manual_rating` | TEXT | 人工覆盖评级 —— v3.0 改用 feasibility_rating |
| `manual_rating_note` | TEXT | 人工评级备注 —— v3.0 不再使用 |

### 系统管理
| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | TEXT | 报告状态（completed/updated/generating/failed） |
| `report_format` | TEXT | 报告格式（"legacy" 或 "v3"）⭐ v3.0 新增 |
| `owner` | TEXT | 创建者/操作人 |
| `created_at` | TEXT | 创建时间 |
| `updated_at` | TEXT | 最近更新时间 |
| `file_size` | INTEGER | MD 文件大小（仅 legacy 格式） |
| `md_path` | TEXT | MD 文件路径（仅 legacy 格式） |
| `chunks_path` | TEXT | chunks.json 路径（仅 legacy 格式） |
| `debug_dir` | TEXT | 调试目录路径 |
| `attachments_dir` | TEXT | 附件目录路径 |
| `attachments` | TEXT | 附件列表 JSON |
| `token_usage_json` | TEXT | Token 用量 JSON |
| `estimated_cost` | REAL | 预估 API 成本（元） |
| `locked_fields` | TEXT | 用户手动编辑锁定的字段列表 JSON |
| `push_records` | TEXT | FastGPT 推送记录 JSON |
| `metadata_json` | TEXT | 元数据 JSON（通用扩展字段） |

### 部门管理
| 字段 | 类型 | 说明 |
|------|------|------|
| `dept_primary` | TEXT | 负责人主属部门 |
| `dept_owner` | TEXT | 归属部门 |

### 其他
| 字段 | 类型 | 说明 |
|------|------|------|
| `remarks` | TEXT | 备注 |
| `intro_attachment` | TEXT | 标的介绍材料附件路径 |
| `annual_report_attachment` | TEXT | 年度报告摘要附件路径 |

---

## 四、report_chunks 表（v3.0 新增）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增主键 |
| `report_id` | TEXT FK | 关联 reports 表 |
| `chunk_id` | TEXT | chunk0~chunk7 |
| `label` | TEXT | chunk 中文名称（如"身份卡""财务数据"） |
| `summary` | TEXT | chunk 摘要（100-200字） |
| `content` | TEXT | chunk 正文内容 |
| `index_tags` | TEXT | 向量检索索引标签 JSON |
| `updated_at` | TEXT | 最近更新时间 |

### 8 个 chunk 定义

| chunk_id | label | 内容说明 |
|----------|-------|---------|
| chunk0 | 身份卡 | 公司全称、工商登记、股权结构、实控人、上市信息 |
| chunk1 | 财务数据 | 营收、净利润、毛利率、资产负债率、现金流 |
| chunk2 | 业务与竞争力 | 主营业务、核心技术、产能、资质认证 |
| chunk3 | 行业与市场 | 行业规模、竞争格局、可比公司、政策趋势 |
| chunk4 | 风险与合规 | 诉讼、处罚、违规记录、合规状态、负面舆情 |
| chunk5 | 交易条件 | 融资历史、估值参考、报价、交易意向 |
| chunk6 | 客户与供应链 | 主要客户、客户集中度、供应商、供应链特征 |
| chunk7 | 跟进动态 | 项目推进时间线（按时间倒序） |
