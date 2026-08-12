---
name: video-analysis-gemini
description: "[Gemini 3.6 Flash 原生多模态直接感知 · 专为 Antigravity 设计] 对对标账号视频进行制作技术全维度拆解并沉淀为可追踪资产。通过 Gemini 3.6 Flash 的原生音视频多模态能力，使用 view_file 直接观看完整视频（画面+声音+时间流），提取五大核心板块（画面镜头语言、AI生成与合成、声音工程、叙事结构、制作SOP）的逐镜逐帧量化技术参数，由 Agent 做账号级公式提炼、时序追踪对比与战略借鉴决策。产出自动归档为结构化资产，支持增量扫描与跨时间对比。当用户需要分析竞品/对标账号视频、拆解视频制作技术、提取可复用制作模式、追踪账号视频随时间变化、或提及'对标账号''视频拆解''制作技术分析''爆款拆解''镜头语言''账号追踪'时使用。"
---

# 对标账号视频制作技术分析

## 核心设计：Flash 感知 + Pro 质检的四层流水线

系统由 **4 层流水线** 构成，实现从视频信号输入、多模态高通量拆解、Pro 级对抗质检到 IP 资产自动编译的全过程：

```
Layer 1: 预处理（信号显性化）
  - ffprobe 提取硬指标元数据（时长/分辨率/帧率/编码）
  - Whisper 提取毫秒级时间戳台词 Ground Truth（STT）
  - 动态九宫格卡点切帧图（快速切换视频用）
  - 注入账号 Baseline

Layer 2: 多模态感知（Flash 3.6 初拆）
  - view_file 原生音视频长上下文感知
  - 提取 5 板块结构化 JSON
  - 附带诚实度报告（honesty_report 证据链）

Layer 3: 质检与对抗探针（Pro 3.1 深度审查）
  - 物理级硬门禁（unified_gate.py）：Schema / 密度 / 时间轴
  - Pro 语义级审查：声画脱节 / 因果矛盾 / 偷懒模板
  - 对抗式定向探针：针对疑问点输出 Target Probe
  - 定向 Patch 局部修剪缝合（微观对焦，避免全量重新感知）
  - 3 轮熔断机制（满 3 次未达 90 分 -> 写入失败库）

Layer 4: 交付与 IP 资产编译
  - 正式落盘 analysis_<date>.json
  - 触发 synthesis_engine 公式提炼
  - 自动编译《IP 专属实拍与音频 SOP》
  - Agent 撰写《仿写参照》`rewrite_reference_<date>.md`（人读层，2026-07-26 新增）
```

| 层 | 执行者 | 职责 |
|---|---|---|
| **L1 预处理** | 脚本 (`preprocessor.py`) | Whisper STT + ffprobe + 九宫格切帧 + 账号 Baseline 注入 |
| **L2 多模态感知** | Gemini Flash 3.6 | view_file 逐条视频提取 5 板块量化 JSON + 诚实度报告 |
| **L3 质检** | Gemini Pro 3.1 + `pro_qa_inspector.py` | 规则硬门禁 + Pro 视频抽查诚实度 + 语义审查（诚实度 50% + 声画自洽 50%）+ 对抗探针 + 熔断 |
| **L4 交付** | 脚本 (`ip_sop_compiler.py`) + Agent | 落盘 JSON + 公式提炼 + SOP 编译 + 音效库归档 |

**铁律**：Flash 只做"看到什么技术参数"的客观量化描述；Pro 做"同行评审"查杀幻觉；"账号公式""战略借鉴""IP SOP"全部由 Agent 完成。

**模型路由表**（推理步骤 -> 指定模型，禁止错位）：

| 推理步骤 | 指定模型 | 理由 |
|---|---|---|
| 视频感知（`view_file` 逐镜提取） | **Gemini 3.6 Flash** | 原生多模态、高通量、成本低 |
| 诚实度终审 + 语义质检 | **Gemini 3.1 Pro** | 反幻觉、因果推理、声画脱节检测 |
| 公式提炼（跨视频归纳） | **Pro 3.1（Agent 模式）** | 需要跨条目归纳、区间统计、因果链推理 |
| 战略借鉴决策 | **Pro 3.1（Agent 模式）** | 需要理解用户 IP 特征做判断，不可下放给 Flash |
| 例行脚本调度（ffprobe/Whisper/归档） | **宿主 / Flash** | 低推理、高吞吐，无需 Pro 参与 |

### Gemini 3.6 Flash 多模态能力上限

本 skill **不做**任何模型都能做的一般分析（元数据统计、帧提取分类、算法切点检测）。以下能力是 Gemini 3.6 Flash 独有或显著优于其他模型的，**必须充分利用**：

1. **全量音视频同感**：不是抽帧分析，而是同时观看完整视频画面 + 听取完整音频轨，理解声画同步关系
2. **跨模态关联**：音效与切镜对齐（SFX 在第 3.2s 卡点切镜）、BGM 节奏与情绪曲线同步、旁白语调与画面内容互补
3. **毫秒级时间轴**：逐镜精确到 0.1s 的起止时间、逐个音效的秒数标注、逐句画外音的起止对齐
4. **微动作微表情捕捉**：宠物歪头/吐舌/眼神跟踪/耳朵起伏/肢体互动等肉眼可辨但算法难提取的细节
5. **情绪递进曲线**：画面情绪 + 声音情绪 + 叙事情绪三层叠加的时间轴情绪曲线
6. **thinking_level=HIGH**：感知时启用最高推理深度，确保不遗漏任何技术细节

### 视频规格要求

| 维度 | 支持范围 | 最佳区间 |
|---|---|---|
| 格式 | .mp4 .mov .webm .m4v .mkv .avi | .mp4 (H.264 + AAC) |
| 文件大小 | ≤ 2GB | 10MB ~ 300MB |
| 时长 | 15s ~ 60min | 15s ~ 5min（短视频黄金区间）|
| 分辨率 | 360p ~ 4K | 720p ~ 1080p |
| 帧率 | 24/30/60 fps | 30 fps |
| 音频 | 需带音频轨 (AAC/MP3/WAV) | AAC 清晰音轨 |

> 超过 5 分钟的长视频如需逐秒级拆解，按自然章节分段 `view_file` 观看，每段 ≤5min。**禁止降级为抽帧分析。**

> **headless（agy CLI）实测边界（2026-07-28）**：GUI 交互式无此限；但经 `agy --print` headless 派发时，**只能稳定完成短/中片（≤~180s、镜数适中）**；极密镜（如 93 镜）会单板块耗尽输出预算、长片（≥~220s）常无产出。详见《agy CLI Headless 批量编排》节的能力边界表与预筛规则。

> **大文件传输保护（2026-07-26 起）**：文件 >10MB 时 `preprocessor.py` 自动生成感知专用转码 `_sense.mp4`（720p/CRF30/AAC96k，保完整音视频流与原始时长）+ 独立音轨 `_sense_audio.m4a`，`view_file` 加载感知轨而非原文件。根因（堆栈诊断）：视频放入请求体时 base64 膨胀 ~1.33×（54.2MB → ~72MB body），本地 Sidecar（127.0.0.1:12450）拒收超大 Request Body 主动断管——上传阶段报 `write: broken pipe`（EPIPE，`stream_receive_count:0`），等待响应阶段报 `read: connection reset by peer`；且流式上下文断裂后 Continue 校验失败无法恢复。阈值 2026-07-26 提速优化由 20MB 降至 **10MB**：一次断管的代价是整段 L2（45-70min）重来，而转码已验证不伤感知，更小请求体进一步压低上传失败率与传输耗时。**感知转码 ≠ 抽帧降级**——完整画面流+音频轨全部保留，仅降码率/分辨率，五板块感知与毫秒级时间轴不受影响。可用 `--sense-threshold-mb` 调阈值或 `--no-sense` 强制直传。

> **网络层自查（辅助，不替代转码）**：若已用感知轨仍断管，检查本地代理——① 全局 HTTP/SOCKS 代理（Clash/V2Ray/Charles 等）须将 `127.0.0.1`/`localhost` 加入 NO_PROXY 直连列表，避免大体量 SSE 流量经 VPN 二次中转 Buffer 溢出；② 自建 Sidecar/Proxy 环境将 IdleConnTimeout / ResponseHeaderTimeout / KeepAlive 延至 300s+。

## 五大核心板块

1. **cinematography** — 画面与镜头语言层（深拆升维）：视点机位、景深构图、ASL 动态节奏波浪图（剪辑呼吸感）、物理视线动量延续 (`kinetic_momentum` Match Cut)、光影色彩

2. **ai_fx** — AI 生成与合成技术层：角色一致性、生成管线、面部口型微动、道具阴影融合
3. **audio** — 声音分层与音效工程（深拆升维）：画外音声学特征 (语速WPM/声调起伏/重音/潜台词)、SFX声画三位一体联动 (`[切镜]+[SFX]+[Ducking]`)、BGM音量dB/BPM、Ducking音频闪避衰减dB、混响空间感与多轨混音结构

4. **narrative** — 故事与叙事结构层：注意力曲线时间轴、信息差视角、金句双关
5. **sop** — 制作 SOP 与商业转化层：复杂度成本、可复用资产、商业植入

完整维度矩阵与 Agent 综合方法论见 [references/analysis_framework.md](references/analysis_framework.md)。

## 自适应粒度适配器

不同时长的视频需要不同的解构粒度。强行用同一套平铺 JSON 结构处理 15 秒 TikTok 和 5 分钟 YouTube 长视频，会导致短视频信息量不足、长视频 JSON 膨胀失控。

| 视频时长 | 粒度 | 解构策略 | shot_timeline 上限 |
|---|---|---|---|
| **短视频** (0-60s) | 微观镜头级 (0.5-2.0s/镜) | 画面切帧、音效卡点与台词 100% 逐帧对齐，不遗漏任何 0.5s 的画面变化 | 无上限 |
| **中长视频** (60-300s) | 分镜/场景级 (3-8s/镜) | 聚焦核心名场面与高反差转折点，过渡镜头可合并为场景段 | ≤80 |
| **超长视频** (>300s) | 三层树状 (Chapter→Scene→Key Shot) | 按 Chapter 分段，每段内按 Scene 聚合，只对 Key Shot 做逐镜拆解 | 每章 ≤20 |

**自适应规则**：
1. 分析前先读取 `_video_meta.json` 获取 `duration_sec`
2. 根据上表判定粒度等级
3. 超长视频（>300s）在 JSON 中增加 `chapter_timeline` 层级，shot_timeline 只保留 Key Shot
4. 中长视频可将连续的相似镜头（同场景/同机位/同主体）合并为 scene 段，减少冗余

## 执行细则文件（渐进披露 · 2026-07-30 拆分）

> 按当前任务只读所需细则，不必整包加载。正文与拆分前逐字一致（拆分前完整版见 git 2026-07-30 之前的 SKILL.md）。**四层门禁与诚实度报告是强制机制**——门禁规则住本文件（下方），诚实度报告细则住 references 但不可跳过。

| 任务环节 | 细则文件 |
|---------|---------|
| 首次使用 / 环境与归档目录 | `references/setup_准备与归档结构.md` |
| 状态机流转 / 会话寿命管理 | `references/状态机与会话寿命管理.md` |
| agy CLI headless 批量编排 | `references/agy_headless批量编排.md` |
| 单视频完整分析流程（L1-L4） | `references/分析工作流.md` |
| 失败模式处理 / 正式工具集清单 | `references/失败模式与工具集.md` |
| 诚实度报告（强制观看证据，产出 JSON 前必读） | `references/诚实度报告机制.md` |
| 五大板块字段框架 | `references/analysis_framework.md`（拆分前已存在） |

---

## 四层强制门禁规则（Anti-Skip Gate）

> **铁律**：禁止跳层执行。每层入口必须验证上一步产出文件存在，否则拒绝执行。

| 入口 | 前置条件（必须全部满足） | 验证方式 |
|------|------------------------|---------|
| **Layer 1 入口** | `_state.json` 的 `current_state` = `UNPROCESSED` | 读取 `_state.json` |
| **Layer 2 入口** | `_grounding_payload.json` 存在 + `current_state` = `PREPROCESSED` | 检查文件 + 读取 `_state.json` |
| **Layer 3 入口** | `analysis_<date>.json` 存在且含 5 板块 + `current_state` ∈ `['FLASH_EXTRACTED', 'PROBE_REPAIRING', 'PRO_AUDITING']` | 检查文件 + 读取 `_state.json` |
| **Layer 4 入口** | `_qa_result.json` 存在且 `qa_passed = true` + `current_state` = `PRO_AUDITING` | 检查文件 + 读取 `_state.json` |

> **为什么 Layer 3 入口是状态集**：探针修补后状态为 `PROBE_REPAIRING`，若死扣 `FLASH_EXTRACTED` 会把修补重审流程硬拦截（死锁）；`PRO_AUDITING` 允许幂等重新组包。`pro_qa_inspector.py` 内置该校验。

**执行规则**：

1. **Layer 1 前置检查脚本**（在执行 `preprocessor.py` 前先运行）：
```bash
python3 -c "
import json, os, sys
state_path = os.path.join(sys.argv[1], sys.argv[2], 'videos', sys.argv[3], '_state.json')
if os.path.exists(state_path):
    with open(state_path) as f: state = json.load(f)
    if state.get('current_state') != 'UNPROCESSED':
        print(f'GATE FAIL: current_state={state["current_state"]}, expected UNPROCESSED'); sys.exit(1)
print('GATE OK: Layer 1 entry')
" <archive-dir> <account> <video-id>
```

2. **Layer 2 前置检查**：确认 `_grounding_payload.json` 存在 + `current_state = PREPROCESSED`
3. **Layer 3 前置检查**：确认 `analysis_<date>.json` 含 5 板块 + `current_state = FLASH_EXTRACTED`
4. **Layer 4 前置检查**：确认 `_qa_result.json` 的 `qa_passed = true` + `current_state = PRO_AUDITING`

🔴 **GATE ENFORCEMENT** · 🛑 **STOP：任一层入口检查失败，必须回退到上一层级补执行，禁止跳过。特别是 Layer 4（SOP 编译）入口，必须验证 Layer 3 的 `_qa_result.json` 存在且 `qa_passed = true`，否则 SOP 中质检分数将显示 N/A，输出无参考价值。


## 反例黑名单（不要做什么）

| # | 不要做 | 为什么 | 替代做法 |
|---|---|---|---|
| 1 | 让 Gemini 做"为什么火""总结规律"等推理 | 推理产出不稳定且不可靠 | Agent 完成所有推理，感知阶段只输出量化 JSON |
| 2 | 覆盖旧 `analysis_*.json` 文件 | 破坏时序追踪能力，丢失历史快照 | 每次新建 `analysis_<date>.json`，旧文件永久保留 |
| 3 | 跳过第 2 步质控直接提炼公式 | 遗漏视频导致公式偏差 | 先确认 100% 覆盖再提炼，补跑失败视频 |
| 4 | 用通用社媒指标（点赞/完播率）替代 5 大制作板块 | 偏离"制作技术分析"目标，产出不可复用 | 严格用 5 大板块，社媒数据单独放 `_account_meta.json` |
| 5 | 战略借鉴时不了解用户 IP 特征 | 借鉴点无针对性，泛泛而谈无价值 | 战略借鉴前需了解用户 IP 的品种/特征/场景限制 |
| 6 | 编造未提取到的技术参数 | 引入幻觉数据，污染分析资产 | 字段缺失标注"未提取到"，不填充猜测值 |
| 7 | 在 `prompts.json` 中加"总结""推理"类指令 | 违反感知层纯量化原则 | prompts 只含"观察/提取/记录"，推理全交给 Agent |
| 8 | 使用 video-tagger / qwen3-vl-plus / DashScope / Python API 脚本替代原生感知 | 违背 Gemini 专用 skill 定位，产出质量低于原生多模态 | 必须用 `view_file` 直接观看完整视频 |
| 9 | **主动**降级为抽帧/切片分析（如只用九宫格切帧图代替 view_file） | 丢失音频轨、时间流、跨模态关联，降为"一般分析" | `view_file` 无法加载则记录失败并告知用户，不降级。**例外 1（感知轨）**：`_sense.mp4` 保完整音视频流，用它做 view_file 不算降级；**例外 2（紧急降级）**：感知轨仍失败时允许"音轨+九宫格"应急，但须按「紧急降级模式」强制诚实标注 |
| 10 | VO 转录只分 3 块（开场/中段/结尾）覆盖全片 | 不论时长都只标 3 条，单条覆盖几十秒，不是逐句转录 | 每一句独立说话/换气为一条，30 秒 ≥3 句，60 秒 ≥6 句 |
| 11 | SFX 不论视频时长都只标 3 个 | 137 镜视频和 15 镜视频都标 3 个 SFX，明显偷懒 | 每 10 秒 ≥2 个 SFX，30 秒 ≥6 个，60 秒 ≥12 个 |
| 12 | 镜头密度对 POV/长镜头视频硬卡 ≥10 镜/30s | POV 手持长镜头视频本身只有 6 镜，硬卡会误判为偷懒 | POV 风格允许 ≥6 镜/30s，但须在 honesty_report 说明拍摄风格 |
| 13 | 战略借鉴时直接照搬竞品动作而不检查可行性 | 不同品种/体型的宠物动作差异大，直接照搬可能穿帮 | 标注可复用性等级，用户自行判断适配度 |
| 14 | 情绪时间轴固定 4 段不论时长 | 180 秒视频和 15 秒视频都是 4 段，粒度不匹配 | 每 30 秒 ≥1 段，单段 ≤60 秒 |
| 15 | climax 和 reversal 时间完全重叠 | 复制粘贴同一时间区间，不区分高潮与反转 | 必须是不同时间区间；无反转则 reversal 字段填 null |
| 16 | 金句使用"【视频名】的终极反转金句"等模板文本 | 不是视频中出现的原文，是 LLM 编造的占位符 | text 必须是视频中出现的原始台词/字幕原文 |
| 17 | narrative_template 固定 0-3s/3-15s/15-25s | 不论视频实际时长都用同一组时间区间 | 时间区间必须根据视频实际时长计算 |
| 18 | macro.total_shots 与 shot_timeline 实际条数不符 | Gemini 声称 137 镜但 timeline 只有 15 条 | total_shots 必须等于 len(shot_timeline) |
| 19 | macro.avg_shot_length 与 sum/len 计算不符 | 声称值与实际计算偏差 >0.5 秒 | avg 必须 = sum(duration_sec) / len，保留 2 位小数（展示层再四舍五入到 1 位） |
| 20 | VO ratio 声明值与 transcript 实际计算偏差 >15% | macro 和微观层不连贯，疑似分别填写 | ratio 必须从 transcript 时间戳计算得出 |
| 21 | SOP 的 macro 对象为空 {} | production_complexity / asset_reusability / monetization 未填写 | macro 必须包含 3 个子对象，每个有实际内容 |
| 22 | VO 转录使用「【开场第N句】大家好…」模板前缀 | 不是视频实际台词，是 LLM 编造的结构化文本 | text 必须是视频中逐字说出的原话，不加任何前缀标记 |
| 23 | SFX 描述使用「动态切帧/动作关键点施加」模板 | 所有 SFX 描述句式相同，非实际音效特征 | description 必须描述该音效的实际声音特征和对应画面 |
| 24 | BGM 描述仅写「视频《视频名》BGM」| 描述过短，无实际音乐信息 | description 必须描述 BGM 的音乐风格、节奏、情绪变化 |
| 25 | SFX 描述跨视频完全雷同 | 所有视频的同类 SFX 描述完全相同（去掉视频名后仅 12 个唯一值），未针对具体画面描述 | description 必须针对该视频的具体画面内容描述音效，不同视频的同类音效描述应不同 |
| 26 | visual_content 使用「第N镜：视频名 镜头展现」模板 | 5493 条全部模板化，从未描述实际画面 | visual_content 必须描述该镜头中实际看到的画面内容（主体、动作、场景） |
| 27 | 凭记忆构造 analysis JSON 结构，不预读 schema_contract.json / prompts.json | AccountA02 事故：一次漏 9 个契约必填字段 + honesty_report 位置写错，finalize-l2 连拦 3 轮 | 严格执行 Layer 2 步骤 2「写前预检铁律」：先读契约→再读 prompts→再读 payload，对照清单填写 |
| 28 | view_file 空返回时仍在 honesty_report 写 view_file_called: true | 实际未看到视频，内容全靠 Whisper + 九宫格推断，却冒充原生感知——诚实度造假 | 空返回 = 感知失败：重试 view_file / 换感知轨，仍失败则显式走紧急降级模式并如实标注 |
| 29 | 用骨架条目过门禁：shot description="Shot N"、quote="Quote N"、VO/SFX text 空串、evidence="Saw everything" | AccountA07-09 伪造交付事故（2026-07-27）：条目字段存在性校验全绿但内容零信息量，污染 L4 资产池与账号公式 | 伪造签名门禁（check_placeholder_forgery）已在 finalize-l2 + ingest 双路拦截；每条内容必须来自真实观看 |
| 30 | 伪造 Pro 阶段B 结果（未真实 view_file 抽查就自填高分 verdict） | 同上事故：184 字节 stub 组包后 13-14 秒自评 98 分——双模型架构的核心环节被架空 | ingest 已加 sanity check：结果 <600B 拒收、距组包 <60s 拒收、spot_check 明细必填；审查必须真实观看视频 |
| 31 | 骨架变体过密度门：每镜 visual_content=“第N镜XX画面细节描述”或多镜只改编号 | AccountA10/08 骨架事故（2026-07-28）：110 镜同模板套话，占位符旧正则（锚定纯英文 Shot N）漏掉，密度因镜多而过门 | check_placeholder_forgery 已加模板套话正则 + 去数字后唯一度<50%拒收；机器门禁外必须内容抽样比对真实画面 |
| 32 | VO 句边界链式合并（end=next.start）吞掉句间静默，产出假 100% 覆盖时间轴 | AccountE03 监督重跑（2026-08-04）：新版 16 句零间隙合并覆盖 100%，whisper Ground Truth 实测 14s 句间静默；macro 声明 83.6% 反而诚实——时间轴与 macro 不连贯 | finalize-l2 新增硬检查：VO 去重叠合并覆盖≥99.5% 且 whisper 静默≥5s 拒收；prompt_header/L2 模板加「保间隙」铁律 |
