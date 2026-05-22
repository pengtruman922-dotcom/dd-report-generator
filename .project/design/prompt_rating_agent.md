# RatingAgent 设计方案

## 概述

RatingAgent 负责对标的项目进行并购可行性评级（A-E）。它不评估"这家公司值不值得投资"，而是评估"这个并购项目能不能推进"——核心关注出售意愿、配合度、客观条件、当前状态。

关键原则：**评级是有成本的决策行为，不是每次都需要执行；评级变更在更新场景下需要用户确认。**

## 在 Pipeline 中的位置

```
WriterAgent
  ├─ read_attachment
  ├─ run_researcher
  ├─ write_chunk × N
  └─ append_tracking_log
       │
       ▼
  代码层：字段回填（汇总 extracted_fields）
       │
       ▼
  代码层：判断是否需要评级  ← 本文档的入口
       │
       ├─ 不需要 → 跳过，保留现有评级
       └─ 需要 → 调用 RatingAgent
              │
              ▼
         代码层：判断评级是否变更
              │
              ├─ 未变更 → 直接保存
              └─ 变更 → 标记 pending_rating_change，等待用户确认
       │
       ▼
  推送 FastGPT
```

---

## 一、何时进行评级

### 核心规则

**不是每次生成/更新报告都需要评级。** 只有满足以下条件时才调用 RatingAgent：

### 1. 新建标的（action=create）

```python
def should_rate_on_create(user_inputs, extracted_fields):
    """新建标的时，判断是否需要 AI 评级。"""
    
    # 规则1：用户输入中已包含明确评级 → 不评级，直接采用用户的
    if _user_provided_rating(user_inputs):
        return False, "user_provided"
    
    # 规则2：用户输入中无评级信息 → 需要 AI 评级
    return True, "no_user_rating"
```

### 2. 更新标的（action=update）

```python
def should_rate_on_update(user_inputs, current_rating, updated_chunks):
    """更新标的时，判断是否需要重新评级。"""
    
    # 规则1：用户输入中明确包含新评级 → 不调 AI，直接采用用户的
    if _user_provided_rating(user_inputs):
        return False, "user_provided"
    
    # 规则2：chunk7（跟进动态）有更新 → 需要重新评级
    # 跟进动态是评级最重要的输入，有新动态就应该重新评估
    if "chunk7" in updated_chunks:
        return True, "tracking_updated"
    
    # 规则3：chunk0（身份卡）或 chunk5（交易条件）有更新 → 需要重新评级
    # 这两个 chunk 包含影响评级的关键信息（股权变更、估值变化等）
    if "chunk0" in updated_chunks or "chunk5" in updated_chunks:
        return True, "key_chunk_updated"
    
    # 规则4：其他 chunk 更新（如财务数据、业务信息）→ 不重新评级
    # 财务和业务变化不直接影响"项目能不能推进"
    return False, "non_rating_relevant"
```

### 3. 判断用户输入是否包含评级

```python
def _user_provided_rating(user_inputs):
    """检测用户输入的材料中是否包含明确的评级信息。"""
    text = user_inputs.get("text", "")
    
    # 检测模式：
    # - "评级为A" "评级：B" "分级C"
    # - "该项目评为A级"
    # - "维持B级" "调整为C"
    rating_pattern = r'(?:评级|分级|评为|定为|调整为)\s*[:：]?\s*[A-Ea-e]'
    
    if re.search(rating_pattern, text):
        return True
    
    return False
```

### 决策矩阵

| 场景 | 用户提供评级 | chunk7 更新 | chunk0/5 更新 | 其他 chunk 更新 | 是否评级 |
|------|------------|-----------|-------------|---------------|---------|
| 新建 | 是 | — | — | — | 否，用用户的 |
| 新建 | 否 | — | — | — | **是** |
| 更新 | 是 | 任意 | 任意 | 任意 | 否，用用户的 |
| 更新 | 否 | 是 | 任意 | 任意 | **是** |
| 更新 | 否 | 否 | 是 | 任意 | **是** |
| 更新 | 否 | 否 | 否 | 是 | 否，保留现有 |

---

## 二、如何准确评级

### 评级输入

**输入不是全部 chunk 内容，而是精选的关键信息。** 过多信息会稀释评级重点，过少又信息不足。

```python
def build_rating_input(chunks, current_rating, action):
    """组装 RatingAgent 的输入。"""
    
    rating_input = {
        # 核心输入1：chunk7 跟进动态（完整原文）
        # 这是评级最重要的信息源——出售意愿、配合度、当前状态全在这里
        "tracking_full_text": chunks["chunk7"]["content"],
        
        # 核心输入2：chunk0 身份卡摘要
        # 提供公司基本面和股权结构（影响客观条件评估）
        "identity_summary": chunks["chunk0"]["summary"],
        
        # 核心输入3：chunk1 财务数据摘要
        # 财务健康度影响客观条件
        "financial_summary": chunks["chunk1"]["summary"],
        
        # 辅助输入：chunk5 交易条件摘要（如有）
        # 估值、交易意愿等信息
        "deal_summary": chunks["chunk5"]["summary"] if chunks.get("chunk5") else None,
        
        # 辅助输入：chunk4 风险摘要（如有）
        # 重大风险影响客观条件
        "risk_summary": chunks["chunk4"]["summary"] if chunks.get("chunk4") else None,
    }
    
    # 更新场景：传入当前评级
    if action == "update" and current_rating:
        rating_input["current_rating"] = current_rating  # {"rating": "B", "reasoning": "..."}
    
    return rating_input
```

### 为什么 chunk7 要传完整原文而不是摘要

chunk7（跟进动态）是评级的**第一信息源**。评级的四个维度中有三个（出售意愿、配合度、当前状态）主要从跟进动态中判断。摘要可能丢失关键细节，例如：

- "董事长说'再看看'"→ 意愿模糊
- "董事长说'6月后再谈，现在太忙'"→ 意愿不消极，只是时机问题

这两条在摘要里可能都变成"暂未明确"，但评级应该不同。

### 为什么 chunk0/chunk1 只传摘要

身份卡和财务数据主要影响"客观条件"这一个维度，且关键信息（股权结构、财务健康度）摘要已覆盖。传完整内容会引入大量与评级无关的细节，增加 token 消耗并稀释 LLM 注意力。

---

### 评级维度

| 维度 | 权重 | 主要信息源 | 说明 |
|------|------|----------|------|
| 出售意愿 | **最高** | chunk7 跟进动态 | 没有出售意愿，其他再好也无法推进 |
| 配合度 | 高 | chunk7 跟进动态 | 尽调和交易中的配合程度 |
| 客观条件 | 中 | chunk0 + chunk1 + chunk4 + chunk5 | 股权清晰度、财务规范性、法律风险 |
| 当前状态 | 中 | chunk7 跟进动态 | 项目推进的阶段和活跃度 |

### 各维度等级定义

#### 出售意愿

| 等级 | 描述 | 典型信号 |
|------|------|---------|
| 强烈 | 主动寻求买家，态度积极 | "主动委托FA""急于出手""愿意出让控制权" |
| 明确 | 有出售意向，愿意推进 | "愿意谈""接受尽调""报了价" |
| 模糊 | 态度不明确 | "再看看""时机不到""需要考虑" |
| 消极 | 倾向于不出售 | "暂时不考虑""估值谈不拢" |
| 未知 | 尚未接触或无法判断 | 新建标的，无跟进记录 |

#### 配合度

| 等级 | 描述 | 典型信号 |
|------|------|---------|
| 积极 | 主动提供材料，响应及时 | "材料齐全""随时可安排""全面配合" |
| 一般 | 基本配合但不主动 | "需多次催促""部分材料未提供" |
| 消极 | 推诿拖延 | "多次未回复""拒绝提供财务数据" |
| 未知 | 尚未进入尽调阶段 | 初步接触，未涉及材料交换 |

#### 客观条件

| 等级 | 描述 | 考量因素 |
|------|------|---------|
| 成熟 | 条件齐备 | 股权清晰、无对赌、财务规范、无重大法律风险 |
| 基本成熟 | 有小障碍可解决 | 小额诉讼、部分资质待续期、少数股东需协调 |
| 存在障碍 | 明显障碍需解决 | 股权代持、对赌未到期、估值分歧大 |
| 不成熟 | 重大障碍，短期无法推进 | 重大诉讼、股权纠纷、失信、财务严重不规范 |

#### 当前状态

| 等级 | 描述 |
|------|------|
| 活跃推进 | 尽调中、谈判中、已有买方在推进 |
| 初步接触 | 已建立联系，初步了解阶段 |
| 暂停等待 | 曾推进但暂停（等条件/等买方决策） |
| 被动等待 | 长时间无进展，未正式终止 |
| 终止 | 已终止或已被其他方收购 |

---

### 综合分级规则

| 分级 | 含义 | 典型画像 |
|------|------|---------|
| A | 高度可行，优先推进 | 出售意愿强烈/明确 + 配合积极 + 条件成熟 + 活跃推进 |
| B | 较为可行，值得投入资源 | 出售意愿明确 + 条件基本成熟 + 初步接触或活跃推进 |
| C | 一般可行，需持续关注 | 出售意愿模糊或条件存在障碍，但有潜力 |
| D | 可行性低，低优先级 | 出售意愿消极或条件不成熟，短期难推进 |
| E | 不可行或已终止 | 明确拒绝、已终止、或存在不可逾越的障碍 |

综合分级判断指南：
- **出售意愿是最关键的维度**——没有出售意愿，其他条件再好也无法推进
- **当前状态为"终止"时**，无论其他维度如何，直接评 E
- 四个维度中有一个特别差，即使其他维度好，也应降级
- 信息不足时宁可保守（给 C 或 D），不要乐观猜测

---

### 更新场景的评级稳定性规则

更新标的时，评级应该**倾向于稳定**，避免因为微小的信息变化导致评级频繁波动。

#### 代码层约束（不是 prompt 建议，是硬规则）

```python
def validate_rating_change(current_rating, new_rating, dimensions):
    """
    代码层校验评级变更的合理性。
    返回 (accepted: bool, reason: str)
    """
    if current_rating is None:
        # 新建标的，无约束
        return True, "initial_rating"
    
    old = current_rating["rating"]  # "A"~"E"
    new = new_rating["rating"]
    
    # 规则1：跳级变更需要特别强的证据（代码层标记，由用户确认）
    grade_order = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}
    diff = abs(grade_order[new] - grade_order[old])
    
    if diff >= 2:
        # 跳了2级以上，标记为 needs_strong_evidence
        return True, "multi_grade_jump"
    
    # 规则2：从非E变为E，或从E变为非E，必须有明确证据
    if old == "E" and new != "E":
        # 从E升级：必须有"当前状态"维度的明确变化
        if dimensions["status"]["level"] in ("终止", "被动等待"):
            return False, "e_upgrade_rejected_status_unchanged"
        return True, "e_upgrade"
    
    if old != "E" and new == "E":
        # 降为E：必须"当前状态"为"终止"或出售意愿为"消极"以下
        status = dimensions["status"]["level"]
        willingness = dimensions["willingness"]["level"]
        if status != "终止" and willingness not in ("消极",):
            return False, "e_downgrade_rejected_insufficient_evidence"
        return True, "e_downgrade"
    
    # 其他变更：正常流程，由用户确认
    return True, "normal_change"
```

#### prompt 层约束

在更新场景下，RatingAgent 的 prompt 中注入当前评级和稳定性要求：

```
## 当前评级信息

该标的当前评级为 {current_rating}，上次评级依据：
{current_reasoning}

## 更新评级规则

你正在对一个已有评级的标的进行重新评估。请遵循以下规则：

1. **稳定性优先**：除非有明确的新信息支持变更，否则维持当前评级
2. **变更需要证据**：如果你认为需要变更评级，必须在 reasoning 中明确说明"什么新信息导致了变更"
3. **E 级特殊规则**：
   - 降为 E：仅当项目明确终止、或标的方明确且持续拒绝时
   - 从 E 升级：仅当有明确的重启信号（重新接触、态度转变等）
4. **不要因为信息不足而降级**：如果某维度此前有信息但本次更新未提及，沿用此前的判断，不要因为"本次没提到"就从"明确"降为"未知"
```

---

## 三、评级结果的应用

### 数据库存储

```sql
-- reports 表增加/修改字段
ALTER TABLE reports ADD COLUMN feasibility_rating TEXT;           -- AI 评级：A/B/C/D/E
ALTER TABLE reports ADD COLUMN feasibility_rating_detail TEXT;    -- JSON: dimensions + reasoning
ALTER TABLE reports ADD COLUMN feasibility_rating_at TEXT;        -- 评级时间
ALTER TABLE reports ADD COLUMN pending_rating_change TEXT;        -- JSON: 待确认的评级变更（为 null 表示无待确认变更）
```

注意：这套评级（并购可行性 A-E）与现有的投资评级（强烈推荐/推荐/...）是**独立的两套体系**，不冲突：
- `score` / `rating`：投资价值评分（0-10 分 + 推荐等级），由 Writer 生成
- `feasibility_rating` / `feasibility_rating_detail`：并购可行性评级（A-E），由 RatingAgent 生成

### RatingAgent 输出格式

```json
{
  "rating": "B",
  "dimensions": {
    "willingness": {
      "level": "明确",
      "evidence": "董事长在2025-02-20会面中表示愿意出让控制权，报价8亿"
    },
    "cooperation": {
      "level": "未知",
      "evidence": "尚未进入材料交换阶段"
    },
    "conditions": {
      "level": "基本成熟",
      "evidence": "股权结构清晰，PE股东有退出需求，未发现重大法律风险"
    },
    "status": {
      "level": "初步接触",
      "evidence": "已首次见面，等待买方A投资集团反馈"
    }
  },
  "reasoning": "标的方出售意愿明确（主动报价），客观条件基本成熟，但目前仅初步接触阶段。综合评为B级。",
  "key_factors": [
    "出售意愿明确，已主动报价",
    "PE股东有退出压力",
    "尚未验证配合度"
  ],
  "rating_changed": true,
  "change_summary": "由C升至B，依据：本次跟进确认出售意愿明确（此前为模糊）"
}
```

### 代码层保存逻辑

```python
async def save_rating_result(report_id, rating_result, action, current_rating):
    """保存评级结果。"""
    
    if action == "create":
        # 新建：直接保存，无需确认
        await db.update_report(report_id, {
            "feasibility_rating": rating_result["rating"],
            "feasibility_rating_detail": json.dumps(rating_result, ensure_ascii=False),
            "feasibility_rating_at": datetime.now().isoformat(),
            "pending_rating_change": None,
        })
        return {"status": "saved", "rating": rating_result["rating"]}
    
    # 更新：检查是否有变更
    if current_rating and current_rating != rating_result["rating"]:
        # 评级变更 → 不直接保存，写入 pending_rating_change 等待用户确认
        pending = {
            "old_rating": current_rating,
            "new_rating": rating_result["rating"],
            "reasoning": rating_result["reasoning"],
            "change_summary": rating_result.get("change_summary", ""),
            "dimensions": rating_result["dimensions"],
            "key_factors": rating_result["key_factors"],
            "created_at": datetime.now().isoformat(),
        }
        await db.update_report(report_id, {
            "pending_rating_change": json.dumps(pending, ensure_ascii=False),
        })
        return {"status": "pending_confirmation", "pending": pending}
    else:
        # 评级未变更 → 直接保存（更新 detail 和时间，保留评级）
        await db.update_report(report_id, {
            "feasibility_rating_detail": json.dumps(rating_result, ensure_ascii=False),
            "feasibility_rating_at": datetime.now().isoformat(),
        })
        return {"status": "saved", "rating": rating_result["rating"]}
```

---

### 前端交互

#### 首页（ReportsPage）评级变更标识

当 `pending_rating_change` 不为空时，在首页的评级列显示变更标识：

```
正常状态：    [B]
有待确认变更：[B] ⚡→C    （点击弹出确认弹窗）
```

实现方式：
```typescript
// 评级列 render
render: (val, row) => {
  const current = row.feasibility_rating;
  const pending = row.pending_rating_change 
    ? JSON.parse(row.pending_rating_change) 
    : null;
  
  if (pending) {
    return (
      <span>
        <RatingBadge rating={current} />
        <span className="text-orange-500 animate-pulse cursor-pointer"
              onClick={() => showRatingConfirmModal(row, pending)}>
          {" "}→{pending.new_rating}
        </span>
      </span>
    );
  }
  
  return <RatingBadge rating={current} />;
}
```

#### 评级变更确认弹窗

```
┌─────────────────────────────────────────────────┐
│ 评级变更确认                                     │
├─────────────────────────────────────────────────┤
│                                                 │
│ 标的：某某科技有限公司                            │
│                                                 │
│ 原评级：  [B] 较为可行                           │
│ 新评级：  [C] 一般可行                           │
│                                                 │
│ 变更依据：                                       │
│ 本次跟进显示标的方态度趋于模糊，表示"需要再考虑"，│
│ 出售意愿从"明确"降为"模糊"。                      │
│                                                 │
│ 四维度评估：                                     │
│ 出售意愿：模糊（↓原为明确）                      │
│ 配合度：一般                                     │
│ 客观条件：基本成熟                               │
│ 当前状态：暂停等待（↓原为初步接触）               │
│                                                 │
├─────────────────────────────────────────────────┤
│              [驳回，维持原评级]  [接受变更]        │
└─────────────────────────────────────────────────┘
```

#### 确认/驳回 API

```
POST /api/reports/{report_id}/rating-confirm
Body: { "action": "accept" | "reject" }
```

代码逻辑：
```python
async def confirm_rating_change(report_id, action):
    report = await db.get_report(report_id)
    pending = json.loads(report["pending_rating_change"])
    
    if action == "accept":
        # 接受变更：更新评级，清除 pending
        await db.update_report(report_id, {
            "feasibility_rating": pending["new_rating"],
            "feasibility_rating_detail": json.dumps({
                "rating": pending["new_rating"],
                "dimensions": pending["dimensions"],
                "reasoning": pending["reasoning"],
                "key_factors": pending["key_factors"],
            }, ensure_ascii=False),
            "feasibility_rating_at": datetime.now().isoformat(),
            "pending_rating_change": None,
        })
    else:
        # 驳回：清除 pending，保留原评级
        await db.update_report(report_id, {
            "pending_rating_change": None,
        })
```

#### 智能录入页面（IntakeAgent）评级变更提示

在智能录入的执行结果中，如果有评级变更，显示醒目提示：

```
✓ 某某科技有限公司 — 更新完成
  更新了：chunk1（财务数据）、chunk7（跟进动态）
  ⚡ 评级变更待确认：B → C（标的方态度趋于模糊）  [查看详情]
```

点击"查看详情"弹出同样的确认弹窗。

---

## 四、RatingAgent 提示词

### 系统提示词

```
你是一名并购项目评级专家。你的任务是根据标的的已有信息，从四个维度评估其并购可行性，给出 A-E 的综合分级。

## 评级维度

### 维度一：出售意愿（最关键）
评估标的方（实控人/大股东）出售或接受并购的意愿程度。

| 等级 | 描述 | 典型信号 |
|------|------|---------|
| 强烈 | 主动寻求买家 | "主动委托FA""急于出手""愿意出让控制权" |
| 明确 | 有出售意向，愿意推进 | "愿意谈""接受尽调""报了价" |
| 模糊 | 态度不明确 | "再看看""时机不到""需要考虑" |
| 消极 | 倾向于不出售 | "暂时不考虑""估值谈不拢""不太积极" |
| 未知 | 无法判断 | 无跟进记录 |

### 维度二：配合度
| 等级 | 描述 | 典型信号 |
|------|------|---------|
| 积极 | 主动提供材料，响应及时 | "材料齐全""随时可安排" |
| 一般 | 基本配合但不主动 | "需多次催促""部分材料未提供" |
| 消极 | 推诿拖延 | "多次未回复""拒绝提供数据" |
| 未知 | 尚未进入尽调阶段 | 初步接触 |

### 维度三：客观条件
| 等级 | 描述 | 考量因素 |
|------|------|---------|
| 成熟 | 条件齐备 | 股权清晰、无对赌、财务规范、无重大法律风险 |
| 基本成熟 | 有小障碍可解决 | 小额诉讼、部分资质待续期 |
| 存在障碍 | 明显障碍需解决 | 股权代持、对赌未到期、估值分歧大 |
| 不成熟 | 重大障碍 | 重大诉讼、股权纠纷、失信 |

### 维度四：当前状态
| 等级 | 描述 |
|------|------|
| 活跃推进 | 尽调中、谈判中、有买方在推进 |
| 初步接触 | 已建立联系，初步了解 |
| 暂停等待 | 曾推进但暂停 |
| 被动等待 | 长时间无进展，未正式终止 |
| 终止 | 已终止或已被其他方收购 |

## 综合分级规则

| 分级 | 含义 | 典型画像 |
|------|------|---------|
| A | 高度可行，优先推进 | 意愿强烈/明确 + 配合积极 + 条件成熟 + 活跃推进 |
| B | 较为可行，值得投入资源 | 意愿明确 + 条件基本成熟 + 初步接触或活跃推进 |
| C | 一般可行，持续关注 | 意愿模糊或条件有障碍，但有潜力 |
| D | 可行性低，低优先级 | 意愿消极或条件不成熟 |
| E | 不可行或已终止 | 明确拒绝、已终止、不可逾越的障碍 |

判断指南：
- 出售意愿是最关键的维度
- 当前状态为"终止"→ 直接 E
- 有一个维度特别差 → 降级
- 信息不足 → 保守（C 或 D），不乐观猜测

## 输出格式

严格输出 JSON，不要有额外说明：

{output_json_template}

## 重要原则

1. 证据驱动：每个维度必须有具体证据。无信息的维度标"未知"
2. 不推测：基于已有信息判断，不编造证据
3. 保守原则：宁可低估不高估
4. reasoning 简洁：2-3 句话
5. key_factors：列出 2-4 个关键因素
```

### 更新场景的附加提示词（代码层注入）

当 action=update 且有 current_rating 时，在 user message 中追加：

```
## 当前评级信息

该标的当前评级为 {current_rating}，上次评级依据：
"{current_reasoning}"

## 更新评级规则（重要）

你正在对一个已有评级的标的进行重新评估。

1. 稳定性优先：除非有明确的新信息支持变更，否则维持当前评级
2. 变更需要证据：在 reasoning 中明确说明"什么新信息导致了变更"
3. E 级特殊规则：
   - 降为 E：仅当项目明确终止、或标的方明确且持续拒绝
   - 从 E 升级：仅当有明确的重启信号（重新接触、态度转变）
4. 信息延续：某维度此前有信息但本次未提及，沿用此前判断，不因"本次没提到"就降为"未知"

如果评级发生变更，请在输出中额外包含：
- "rating_changed": true
- "change_summary": "一句话说明：从X变为Y，因为..."
```

---

## 五、RatingAgent 调用代码

```python
async def rate_report(
    report_id: str,
    chunks: dict,          # chunk_id -> {content, summary}
    action: str,           # "create" | "update"
    current_rating: dict | None,   # 更新时的当前评级
    ai_config: dict,
) -> dict:
    """调用 RatingAgent 进行评级。"""
    
    client = create_client(ai_config["base_url"], ai_config["api_key"])
    
    # 组装输入
    rating_input = build_rating_input(chunks, current_rating, action)
    
    # 构建 messages
    system_msg = RATING_SYSTEM_PROMPT
    
    user_parts = []
    user_parts.append("## 跟进动态（完整内容）\n" + (rating_input["tracking_full_text"] or "暂无跟进记录"))
    user_parts.append("## 标的身份卡摘要\n" + (rating_input["identity_summary"] or "暂无"))
    user_parts.append("## 财务数据摘要\n" + (rating_input["financial_summary"] or "暂无"))
    
    if rating_input.get("deal_summary"):
        user_parts.append("## 交易条件摘要\n" + rating_input["deal_summary"])
    if rating_input.get("risk_summary"):
        user_parts.append("## 风险摘要\n" + rating_input["risk_summary"])
    
    # 更新场景注入当前评级
    if action == "update" and current_rating:
        user_parts.append(UPDATE_RATING_ADDENDUM.format(
            current_rating=current_rating["rating"],
            current_reasoning=current_rating.get("reasoning", "无"),
        ))
    
    user_parts.append("请根据以上信息进行评级。")
    
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]
    
    response, usage = await chat_completion(
        client, ai_config["model"], messages, temperature=0.1
    )
    
    # 解析 JSON 输出
    result = parse_json_response(response.choices[0].message.content)
    
    # 代码层校验评级变更合理性
    if action == "update" and current_rating:
        accepted, reason = validate_rating_change(
            current_rating, result, result["dimensions"]
        )
        if not accepted:
            # 校验不通过：强制维持原评级，记录原因
            result["rating"] = current_rating["rating"]
            result["rating_changed"] = False
            result["validation_override"] = reason
    
    return result, usage
```

---

## 六、与现有投资评级的关系

| | 投资评级（现有） | 可行性评级（本方案） |
|--|--|--|
| 评什么 | 这家公司值不值得投 | 这个并购项目能不能推进 |
| 维度 | 行业前景/盈利能力/成长性/现金流/风险 | 出售意愿/配合度/客观条件/当前状态 |
| 生成方 | Writer（嵌在报告里） | RatingAgent（独立 Agent） |
| 结果 | 0-10分 + 推荐等级 | A-E 等级 |
| 数据库字段 | `score` + `rating` | `feasibility_rating` + `feasibility_rating_detail` |
| 变更确认 | 不需要 | **更新时需要用户确认** |
| 手动覆盖 | `manual_rating` 字段 | 用户驳回后保留原评级 |

两套评级独立运行，互不影响。前端可同时展示。

---

## 七、实现优先级

| 优先级 | 改动 | 工作量 | 说明 |
|--------|------|--------|------|
| P0 | RatingAgent 提示词 + 调用逻辑 | 中 | 核心功能 |
| P0 | should_rate 判断逻辑 | 小 | 决定何时调用 |
| P0 | 数据库字段 + 保存逻辑 | 小 | 存储层 |
| P1 | 评级变更确认弹窗（前端） | 中 | 用户交互 |
| P1 | 首页评级列 + 待确认标识 | 小 | 展示层 |
| P1 | 确认/驳回 API | 小 | 后端接口 |
| P2 | 评级变更历史记录 | 中 | 追踪评级变化轨迹 |
| P2 | 智能录入页面的评级提示 | 小 | 体验优化 |
