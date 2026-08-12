# {{account}} 账号级公式提炼报告

<!--
  本模板由 Agent 填充，基于该账号全量视频的 analysis_*.json 感知数据综合产出。
  存入 <archive-dir>/<account>/account_formula_<date>.md
  每次分析生成新日期文件，旧文件不覆盖，实现时序追踪。
-->

> 提炼日期：{{date}}
> 数据范围：{{video_count}} 条视频全量拆解
> 平台：{{platform}}
> 分析模型：{{model}}

---

## 一、账号内容公式

### 公式名称

**{{formula_name}}**

### 量化参数区间

| 维度 | 参数区间 | 数据依据 |
|---|---|---|
| 机位高度 | {{camera_height_range}} | 基于 N 条视频统计 |
| 平均镜长 ASL | {{asl_range}} | |
| 快切频率 | {{quick_cut_range}} | |
| 光圈/景深 | {{aperture_range}} | |
| 色温/色调 | {{color_temp_range}} | |
| 画外音占比 | {{voiceover_ratio_range}} | |
| 角色台词占比 | {{character_lines_range}} | |
| 定格帧使用 | {{hold_frame_range}} | |
| 视频时长 | {{duration_range}} | |

### 公式描述

{{用 2-3 句话描述这个账号的核心内容公式，包含关键技术参数和内容特征的组合关系}}

---

## 二、全量视频技术矩阵

| 序号 | 视频ID | 机位 | 镜数 | 均长 | 光影 | 声画比 | 叙事结构 | 借鉴点 |
|---|---|---|---|---|---|---|---|---|
| 1 | {{video_id}} | {{cm}} | {{shots}} | {{asl}} | {{light}} | {{ratio}} | {{structure}} | {{borrow}} |
| ... | | | | | | | | |

---

## 三、技术演进分析（如有新旧对比）

| 参数 | 早期版本 | 近期版本 | 变化方向 | 推断效果 |
|---|---|---|---|---|
| 平均镜长 | {{old_asl}} | {{new_asl}} | 缩短/延长 | {{effect}} |
| 音效使用 | {{old_sfx}} | {{new_sfx}} | 强化/弱化 | {{effect}} |
| AI 技术引入 | {{old_ai}} | {{new_ai}} | 新增/移除 | {{effect}} |

### 进化结论

{{哪些技术改进直接对应了爆款效果提升，给出因果推断}}

---

## 四、跨平台对比（如有多平台数据）

| 平台 | 时长 | 切频 | 光影 | BGM | 差异要点 |
|---|---|---|---|---|---|
| {{platform_1}} | | | | | |
| {{platform_2}} | | | | | |

### 平台适配策略

{{该账号如何针对不同平台调整内容}}

---

## 五、战略借鉴决策

### 直接可复用项

{{#each direct_borrow}}
**【可借鉴】** {{account}} 在 {{technique}} 上的方式是 {{quantified_description}}。
用户 IP 可以 {{specific_action}}，难度 {{difficulty}}。
{{/each}}

### 需要改造的项

{{#each adapt_borrow}}
**【需改造】** {{account}} 的 {{technique}}，需适配为 {{ip_adaptation}}，改造方式 {{method}}。
{{/each}}

### 不应照搬项

{{#each no_borrow}}
**【不照搬】** {{account}} 的 {{technique}}，原因是 {{reason}}。
{{/each}}

### 优先级排序

| 优先级 | 借鉴项 | 来源账号 | 执行难度 | 预期效果 |
|---|---|---|---|---|
| 🔴 高 | | | 易/中/难 | |
| 🟡 中 | | | 易/中/难 | |
| 🟢 低 | | | 易/中/难 | |

---

## 六、账号基因 vs 通用技术拆分

| 类别 | 技术要素 | 是否可复用 |
|---|---|---|
| **账号基因**（不可复用） | {{specific_brand_dna}} | ✗ 该账号独有 |
| **通用技术**（可复用） | {{generic_technique}} | ✓ 可直接借鉴 |

---

*原始数据来源：videos/*/analysis_{{date}}.json（全量 {{video_count}} 条）*
