# Gemini 视频分析 Skill A/B 对比测试 · 完整报告

> **报告日期**: 2026-07-26
> **测试目标**: 验证 `video-analysis-gemini` skill 流水线相比"直接拖视频+简洁 prompt"是否真正产生更高质量输出，并回答"为什么 skill 这么慢"
> **结论速览**: Skill 慢的代价换来**零幻觉 + 21 条诚实证据 + VO 一致性校验**；直接 prompt 快但**幻觉 39 秒 + VO ratio 126%（不可能）+ 无诚实度报告**

---

## 1 · 测试设计

### 1.1 测试视频

| 属性 | 值 |
|---|---|
| 文件名 | `01-7161327303857900812-第一次约会好尴尬呀.mp4` |
| 账号 | 主人必须屎 |
| 真实时长 | **117.84 秒**（`_video_meta.json` + ffprobe 确认） |
| 分辨率 | 720 × 1280（竖屏） |
| 帧率 | 25 fps |
| 编码 | h264 / aac |
| 文件大小 | 12.3 MB |

### 1.2 两条路径

| | Path A — Skill 流水线 | Path B — 直接对话 Prompt |
|---|---|---|
| **流程** | L1 预处理（提取元数据）→ L2 逐段感知（`view_file` + `thinking_level=HIGH`）→ L3 Pro QA 校验 → L4 交付落盘 | 将视频文件 + `prompt_b.txt` 拖入 Gemini 对话框，单轮输出 JSON |
| **Prompt 特征** | 多阶段、含密度门禁（≥3.3 镜头/10s、≥2 SFX/10s、≥1 VO/10s）、强制诚实度报告、Schema 校验 | 单轮、指定 5 个输出板块 + 字段列表，显式要求 `view_file` 观看完整视频 |
| **输出** | `analysis_2026-07-25.json`（已落盘到视频目录） | 用户从对话框导出的 JSON（存于 Desktop） |
| **模型** | gemini-3.6-flash | gemini-3.6-flash |

### 1.3 Path B 使用的 Prompt（`prompt_b.txt` 全文）

```
请先用 view_file 观看完整视频（含音频轨），不要只抽帧或看切片，必须同时感知画面和声音。
看完后逐镜拆解制作技术，输出JSON，包含以下五个板块：

1. cinematography — 逐镜时间轴 shot_timeline（每个镜头：index, start_sec, end_sec, shot_type,
   camera_movement, visual_content, transition_to_next）+ 宏观统计 macro（total_shots,
   avg_shot_length_sec, dominant_camera_height_range, dominant_lighting, visual_emotion_curve）

2. audio — 逐句画外音 voiceover_transcript（每句：start_sec, end_sec, text）+ SFX时间轴
   sfx_timeline（每个：sec, sfx_name, description）+ BGM变化 bgm_timeline（每段：start_sec,
   end_sec, bpm, volume_db）+ Ducking事件 ducking_and_silence

3. narrative — 故事节拍 story_beats（每个：beat_type, start_sec, end_sec, description）
   + 情绪曲线 + 完整台词全文 script_full_text + 金句 all_quotes

4. ai_fx — 是否有AI生成痕迹 + 角色一致性 + 面部微动时刻 micro_motion_moments

5. sop — 制作复杂度 + 可复用资产 + 品牌植入方式

每个镜头精确到0.1秒，覆盖全片。无法确定的字段填null。
```

---

## 2 · 全量指标对比表

> 标注说明：✅ = 该路径胜出且此维度至关重要；⚠️ = 胜出但结果被幻觉污染；* = 脚本等值误判

### 2.1 核心准确性指标（权重最高）

| # | 指标 | A (skill) | B (direct) | 胜者 | 判定理由 |
|---|---|---|---|---|---|
| 1 | **时间轴覆盖率 %** | **100.0** | 66.8 | ✅ A | 最后镜头 end_sec ≈ 视频时长 |
| 2 | **覆盖偏差 (秒)** | **0.0** | 39.16 | ✅ A | 越小越好；B 超出真实时长 33% |
| 3 | **时间轴幻觉超出 (秒)** | **0** | 39.16 | ✅ A | >5% 时长 = 幻觉 |
| 4 | **时间轴幻觉标记** | **❌ 无** | ⚠️ 有 | ✅ A | B 的时间轴超出真实时长 5% 以上 |
| 5 | **VO ratio 一致性** | **✅** | ❌ | ✅ A | B 计算值 126.1%（>100% 不可能） |
| 6 | **有 honesty_report** | **✅** | ❌ | ✅ A | skill 强制要求 |
| 7 | **honesty 细节条数** | **21** | 0 | ✅ A | 从观看中获得的可追溯证据 |

### 2.2 密度与粒度指标

| # | 指标 | A (skill) | B (direct) | 胜者 | 判定理由 |
|---|---|---|---|---|---|
| 8 | 镜头数 | 21 | 41 | ⚠️ B* | B 多出 20 镜但含 39s 幻觉内容 |
| 9 | 镜头密度 /10s | 1.8 | 3.5 | ⚠️ B | 密度被幻觉时间轴抬高 |
| 10 | SFX 数 | 6 | 11 | ⚠️ B | B 有 3 条 SFX 时间戳 >117.84s |
| 11 | SFX 密度 /10s | 0.5 | 0.9 | ⚠️ B | 被幻觉抬高 |
| 12 | **VO 段数** | **61** | 35 | ✅ A | skill 把旁白切到句子级 |
| 13 | **VO 密度 /10s** | **5.2** | 3.0 | ✅ A | skill 密度门禁生效 |
| 14 | BGM 变化 | 3 | 8 | ⚠️ B | B 的 BGM 段延伸至 157s |
| 15 | Ducking 事件 | 2 | 0 | ✅ A | B 用文字描述非结构化列表 |
| 16 | 微动作捕捉 | 3 | 5 | ⚠️ B | B 有 `timestamp_sec: 140.5` 超 117.84s |

### 2.3 结构与叙事指标

| # | 指标 | A (skill) | B (direct) | 胜者 | 判定理由 |
|---|---|---|---|---|---|
| 17 | 故事节拍 | 5 | 5 | tie | 等值（脚本误判为 B） |
| 18 | **情绪段数** | **5** | 0 | ✅ A | B 用 dict 格式，非标准 list |
| 19 | 金句数 | 2 | 3 | B | B 多 1 条 |
| 20 | script 全文长度 | 500 | 515 | B | 基本相当 |

### 2.4 一致性自检指标

| # | 指标 | A (skill) | B (direct) | 胜者 | 判定理由 |
|---|---|---|---|---|---|
| 21 | macro.total_shots 匹配 | ✅ | ✅ | tie | 声明总数 = 实际条数 |
| 22 | ASL 一致性 | ✅ | ✅ | tie | 声明 ASL = 计算 ASL (±0.5s) |

### 2.5 模板化与体积指标

| # | 指标 | A (skill) | B (direct) | 胜者 | 判定理由 |
|---|---|---|---|---|---|
| 23 | null 字段比例 % | 0.0 | 0.0 | tie | 等值（脚本误判为 B） |
| 24 | SFX 描述重复率 % | 0.0 | 0.0 | tie | 等值（脚本误判为 B） |
| 25 | 镜头描述重复率 % | 0.0 | 0.0 | tie | 等值（脚本误判为 B） |
| 26 | JSON 体积 (KB) | 14.0 | 14.0 | tie | 等值（脚本误判为 B） |

---

## 3 · 胜负统计与修正

### 3.1 脚本原始统计

| | 数量 |
|---|---|
| A (skill) 胜 | 11 |
| B (direct) 胜 | 13 |
| 平局 | 2 |

### 3.2 修正项

| 修正类型 | 影响指标 | 说明 |
|---|---|---|
| **等值误判**（5 项） | 故事节拍、null 比例、SFX 重复率、镜头重复率、JSON 体积 | A=B 但脚本 `"A if a>b else "B"` 逻辑在等值时默认判 B |
| **幻觉污染**（4 项） | 镜头数、SFX 数、BGM 变化、微动作 | B 的"多"来自 39s 虚构内容，时间戳超过真实视频时长 |

### 3.3 修正后统计

| | 原始 | 修正后 |
|---|---|---|
| A (skill) 胜 | 11 | **11** |
| B (direct) 真实胜 | 13 | **4**（金句数、镜头密度、SFX 密度、script 长度） |
| 平局 | 2 | **7**（含 5 项等值修正） |
| 幻觉污染（不计） | — | **4** |

---

## 4 · 🔴 核心发现：Path B 时间轴幻觉 39 秒

### 4.1 事实数据

| 维度 | A (skill) | B (direct) | 真实值 | 判定 |
|---|---|---|---|---|
| 最后镜头 end_sec | 117.84 | **157.0** | 117.84 | A 正确 / B 幻觉 |
| VO 最后段 end_sec | 117.84 | **157.0** | 117.84 | A 正确 / B 幻觉 |
| 时间轴超出 | 0s | **39.16s** | — | B 超出 33% |
| VO ratio（计算） | 96.6% | **126.1%** | 应 ≤100% | B 物理不可能 |
| VO ratio（macro 声明） | 82.5% | 0（未声明） | — | B 无自检 |
| honesty view_duration_sec | 117.84 | 无 | 117.84 | A 与 ffprobe 一致 |

### 4.2 B 的具体幻觉证据

**镜头时间戳超出真实时长：**

| 镜头 # | start_sec | end_sec | 问题 |
|---|---|---|---|
| 28 | 59.2 | **103.8** | 跨度 44.6s，极不正常（25fps 短视频单镜通常 <8s） |
| 29 | 103.8 | 107.0 | 超出真实时长但仍在 B 的时间轴内 |
| 30 | 107.0 | 109.1 | 同上 |
| … | … | … | … |
| 41 | 148.8 | **157.0** | 超出真实时长 39.16s |

**SFX 时间戳超出真实时长：**

| SFX | sec | 问题 |
|---|---|---|
| fast_scroll_swish | **123.5** | 超出 117.84s |
| paws_running | **136.5** | 超出 117.84s |
| heartbeat_shimmer | **145.2** | 超出 117.84s |

**BGM 时间轴延伸至幻觉区间：**

| BGM 段 | start_sec | end_sec | 问题 |
|---|---|---|---|
| 第 7 段 | 134.0 | **145.0** | 部分超出 |
| 第 8 段 | 145.0 | **157.0** | 完全超出 |

**微动作时间戳超出：**

| 微动作 | timestamp_sec | 问题 |
|---|---|---|
| 银渐层楼下深情口型 | **140.5** | 超出 117.84s |

### 4.3 为什么 B 产生了幻觉

尽管 `prompt_b.txt` 第 1 行明确写了 **"请先用 view_file 观看完整视频（含音频轨），不要只抽帧或看切片"**，B 仍然产生了 33% 的时间轴超出。可能原因：

1. **B 未真正执行 view_file 全片观看** — 基于片段印象"脑补"完整内容
2. **B 的时间感知系统性偏差** — 将视频内容"拉长"到 157s，可能混淆了播放速度或重复感知
3. **B 缺乏事实校验闭环** — 没有 `_video_meta.json` 的真实时长注入，没有任何机制阻止 end_sec 超出

### 4.4 为什么 A 没有幻觉

Skill 的诚实度报告（`_meta.honesty_report`）形成了事实校验闭环：

```json
"honesty_report": {
  "view_file_called": true,
  "view_duration_sec": 117.84,   // ← 与 ffprobe 完全一致
  "watched_full_video": true,
  "sections": { ... },            // ← 5 个 section 各有独立观看证据
  "specific_details_only_from_watching": [  // ← 21 条可追溯细节
    "0.0s美妆镜镜框上有粉色卡通图案，白猫用粉扑按压脸颊",
    "0.57s喵喵烘干箱上贴着白色手写纸条'喵通快递 收件人: 2.5 寄件人: 闺蜜'",
    ...
  ]
}
```

每条细节都带有精确时间戳和只能从观看中获得的具体画面描述（如"粉色卡通图案""手写纸条内容"），这些是不可能从 prompt 推断出来的。

---

## 5 · Skill 自身问题：密度门禁未生效

### 5.1 门禁达标情况

| 门禁 | 最低要求 | A 实际 | B 实际 | A 状态 | B 状态 |
|---|---|---|---|---|---|
| 镜头密度 /10s | ≥3.3 | 1.8 | 3.5 | ❌ 未达标 | ⚠️ 达标但被幻觉抬高 |
| SFX 密度 /10s | ≥2.0 | 0.5 | 0.9 | ❌ 未达标 | ❌ 未达标 |
| VO 密度 /10s | ≥1.0 | 5.2 | 3.0 | ✅ 达标 | ✅ 达标 |

### 5.2 分析

Skill 在 **镜头密度**（1.8 vs 最低 3.3）和 **SFX 密度**（0.5 vs 最低 2.0）上**严重不达标**，但质量闸门并未拦截或打回。这说明：

- 门禁规则写在 SKILL.md 中，但 **L2→L3 流程中未自动计算和校验密度**
- A 的 21 个镜头中 ASL=5.61s（平均镜头时长 5.6 秒），远高于 B 的 3.83s，说明 A 把多个实际镜头合并成了大段
- A 的 SFX 只有 6 条，平均每 20 秒才 1 条 SFX，对于有化妆喷雾、猫爪拍屏、垃圾桶砸入、门铃、心跳等多种音效的视频来说明显遗漏

### 5.3 对"慢"的影响

Skill 慢但密度不够，说明 **慢的代价没有完全转化为密度收益**。多阶段处理和 `thinking_level=HIGH` 的开销主要花在了诚实度报告和一致性校验上，而非在镜头切分粒度上。

---

## 6 · 逐维度深度对比

### 6.1 Cinematography（摄影）

| 子维度 | A (skill) | B (direct) | 分析 |
|---|---|---|---|
| 镜头数 | 21 | 41 | B 更细但含幻觉；A 合并过多 |
| ASL | 5.61s | 3.83s | A 的镜头过长，应 <4s |
| macro 一致性 | ✅ | ✅ | 双方声明总数均与实际匹配 |
| 情绪曲线 | 5 段（list + intensity 1-10） | 0（dict 格式偏差） | A 结构化；B 用 `{"0-6s":"期待..."}` 字典格式 |
| 色温/构图 | 有 `dominant_color_temp`、`dominant_composition` | 无 | A 更完整 |
| 运动连续性 | 有 `kinetic_continuity_rating`、`eye_line_match` | 无 | A 独有 |

### 6.2 Audio（音频）

| 子维度 | A (skill) | B (direct) | 分析 |
|---|---|---|---|
| VO 段数 | 61 | 35 | A 切到短句级；B 切到长段落级 |
| VO ratio | 82.5%（声明）/ 96.6%（计算）✅ | 0（未声明）/ 126.1%（计算）❌ | B 的 VO 时间戳超出视频时长 |
| SFX 数 | 6 | 11 | B 更多但 3 条超 117.84s |
| SFX 三元耦合 | 有 `triad_coupling` 字段 | 无 | A 独有，标注画面+SFX+Ducking 联动 |
| BGM 段数 | 3 | 8 | A 粗粒度（3 段覆盖全片）；B 细但延伸至 157s |
| Ducking | 2 事件（list：start/end/attenuation/reason） | 文字描述（string） | A 结构化可编程；B 不可解析 |
| 音频情绪曲线 | 5 段 | 无 | A 独有 |

### 6.3 Narrative（叙事）

| 子维度 | A (skill) | B (direct) | 分析 |
|---|---|---|---|
| 故事节拍 | 5 | 5 | 相同 |
| 节拍类型 | 英文枚举（Inciting Incident / Rising Action…） | 英文枚举（setup / inciting_incident…） | 风格不同，均可接受 |
| hook_analysis | 有（type + description + effectiveness_score 9.2） | 无 | A 独有 |
| narrative macro | 有（attention_curve / template / climax_sec / reversal_sec） | 无 | A 独有 |
| script_full_text | 500 字 | 515 字 | 基本相当 |
| 金句 | 2 条 | 3 条 | B 多 1 条（"命运送你的礼物…"可能是 B 自己创作的） |

### 6.4 AI/FX

| 子维度 | A (skill) | B (direct) | 分析 |
|---|---|---|---|
| 微动作 | 3（`sec` + `description`） | 5（`timestamp_sec` + `feature`） | B 更多但 `140.5s` 超出真实时长 |
| scene_timeline | 1 段（全片实拍标注） | 0（无此字段） | A 独有 |
| character_consistency | "100% 物理真实动物" | "高（实拍+AI口型驱动）" | A 判定纯实拍；B 认为有 AI 口型驱动——**两者判断矛盾** |
| generation_pipeline | "纯实拍" | "has_ai_generation: true" | A 认为无 AI；B 认为有 AI——**关键分歧** |

> **注意**: A 和 B 对"是否有 AI 生成痕迹"给出了**相反结论**。A 判定全片纯实拍无 AI；B 判定有 AI 口型驱动。由于 B 的时间轴本身不可信（39s 幻觉），其 AI 判断的可信度也存疑。这需要人工观看视频来裁定。

### 6.5 SOP

| 子维度 | A (skill) | B (direct) | 分析 |
|---|---|---|---|
| 复杂度评级 | 4 星 | S 级 | 主观判断，差异可接受 |
| 可复用资产 | 结构化列表（modules + monetization） | 文字描述列表 | A 更结构化 |
| 品牌植入 | 结构化（product_name + selling_points + integration_method） | 文字描述 | A 更结构化 |
| fixed_elements | 有 | 无 | A 独有 |

---

## 7 · 回答原始问题：为什么 Skill 慢？

### 7.1 慢的成本-收益分析

| 慢的因素 | 速度代价 | 准确性收益 | 评价 |
|---|---|---|---|
| **多阶段处理**（L1→L2→L3→L4） | 每阶段独立 thinking + 输出 + 落盘 | 0 幻觉 vs B 的 39s 幻觉 | ✅ 值得 |
| **诚实度报告** | 强制 21 条观看证据 | 可追溯、可审计 | ✅ 值得 |
| **Schema 校验 + QA** | L3 pro_qa_inspector 检查 | VO ratio ✅ vs B ❌ | ✅ 值得 |
| **view_file 全片观看** | 117.84s 完整感知 | 时间轴 100% 准确 | ✅ 值得（B 虽被要求但未做到） |
| **thinking_level=HIGH** | 每段独立深度推理 | 准确性提升但密度未提升 | ⚠️ 速度代价大，密度收益不明确 |
| **密度门禁** | 门禁存在但未生效 | 镜头 1.8 / SFX 0.5 未达最低线 | ❌ 浪费——设了门禁但没拦 |

### 7.2 核心结论

> **Skill 慢的代价换来了：零幻觉 + 21 条诚实证据 + VO 一致性校验 + 结构化输出。**
> **直接 prompt 快的代价是：39 秒幻觉 + 126% VO ratio + 无诚实度报告 + 非结构化字段。**
>
> Skill 也有自身问题：**密度门禁未生效**（镜头密度 1.8 远低于自设的 3.3 最低线），说明慢的代价没有完全转化为密度收益——部分算力花在了流程开销而非内容粒度上。

---

## 8 · 改进建议

### 8.1 Skill 侧（优先级排序）

| # | 建议 | 优先级 | 预期效果 |
|---|---|---|---|
| 1 | **密度门禁自动化生效**：L2 完成后自动计算 `shot_density` 和 `sfx_density`，低于最低线直接打回重做 | P0 | 镜头密度从 1.8 提升到 ≥3.3 |
| 2 | **ASL 过长告警**：ASL > 4s 时提示"镜头切分不够细"并要求重切 | P0 | ASL 从 5.61s 降到 <4s |
| 3 | **诚实度报告自动校验**：`honesty_report.view_duration_sec` 与 `_video_meta.json.duration_sec` 自动比对，不一致直接拦截 | P1 | 防止诚实度报告本身造假 |
| 4 | **SFX 三元耦合覆盖率检查**：要求 ≥50% 的 SFX 标注 `triad_coupling` | P2 | 提升音频分析的结构化程度 |
| 5 | **AI/FX 判断二轮确认**：对"是否有 AI 生成痕迹"的判断，要求提供至少 3 条帧级证据 | P2 | 避免 A/B 那样的矛盾结论 |

### 8.2 直接 Prompt 侧（如要替代 Skill）

| # | 建议 | 理由 |
|---|---|---|
| 1 | **注入真实时长**：prompt 中写明 "视频总时长 117.84 秒，所有时间戳不得超过此值" | 直接解决 39s 幻觉问题 |
| 2 | **要求结构化 Ducking**：明确 "ducking_and_silence 必须是数组，每个元素含 start_sec/end_sec/ducking_attenuation_db/reason" | B 目前输出文字描述，不可编程解析 |
| 3 | **要求 emotion_curve 为列表**：明确 "visual_emotion_curve 必须是数组，每个元素含 start_sec/end_sec/emotion/intensity" | B 目前输出 dict，与 Schema 不兼容 |
| 4 | **要求 honesty_report**：明确 "输出必须包含 _meta.honesty_report，列出从观看中获得的至少 10 条具体细节" | 建立 accountability |
| 5 | **要求 macro 自检字段**：明确 "audio.macro 必须包含 voiceover_ratio_pct" | 让 B 也有一致性自检能力 |

---

## 9 · 测试文件清单

| 文件 | 路径 |
|---|---|
| **Path A 输出（Skill）** | `raw/内容创作/内容制作/巴基娜美/07-对标账号研究/对标视频分析资产/主人必须屎/videos/01-7161327303857900812-第一次约会好尴尬呀/analysis_2026-07-25.json` |
| **Path B 输出（原始）** | `~/Desktop/01-7161327303857900812-第一次约会好尴尬呀_制作技术拆解.json` |
| **Path B 输出（提取纯 JSON）** | `raw/skills/内容平台/video-analysis-gemini/experiments/ab_test/path_b_output.json` |
| **Path B Prompt** | `raw/skills/内容平台/video-analysis-gemini/experiments/ab_test/prompt_b.txt` |
| **对比脚本** | `raw/skills/内容平台/video-analysis-gemini/experiments/ab_test/ab_compare.py` |
| **脚本原始报告** | `raw/skills/内容平台/video-analysis-gemini/experiments/ab_test/ab_report.txt` |
| **修正后脚本报告** | `raw/skills/内容平台/video-analysis-gemini/experiments/ab_test/ab_report_v2.txt` |
| **本完整报告** | `raw/skills/内容平台/video-analysis-gemini/experiments/ab_test/AB_TEST_FULL_REPORT.md` |
| **视频元数据** | `raw/内容创作/.../01-7161327303857900812-.../_video_meta.json` |

---

## 10 · 附录：完整 Metrics JSON

### 10.1 Path A (Skill) Metrics

```json
{
  "shots": 21,
  "shot_density_per_10s": 1.8,
  "coverage_gap_sec": 0.0,
  "coverage_pct": 100.0,
  "hallucination_overshoot_sec": 0,
  "hallucination_flag": false,
  "sfx": 6,
  "sfx_density_per_10s": 0.5,
  "vo_segments": 61,
  "vo_density_per_10s": 5.2,
  "bgm_changes": 3,
  "ducking_events": 2,
  "story_beats": 5,
  "quotes": 2,
  "emotion_segments": 5,
  "micro_motions": 3,
  "scene_timeline": 1,
  "macro_total_shots": 21,
  "macro_shots_match": true,
  "asl_macro": 5.61,
  "asl_calc": 5.61,
  "asl_match": true,
  "vo_ratio_macro": 82.5,
  "vo_ratio_calc": 96.6,
  "vo_ratio_match": true,
  "has_honesty_report": true,
  "honesty_details_count": 21,
  "null_fields": 0,
  "total_fields": 510,
  "null_ratio_pct": 0.0,
  "sfx_template_ratio_pct": 0.0,
  "shot_template_ratio_pct": 0.0,
  "script_full_text_len": 500,
  "json_size_kb": 14.0
}
```

### 10.2 Path B (Direct) Metrics

```json
{
  "shots": 41,
  "shot_density_per_10s": 3.5,
  "coverage_gap_sec": 39.16,
  "coverage_pct": 66.8,
  "hallucination_overshoot_sec": 39.16,
  "hallucination_flag": true,
  "sfx": 11,
  "sfx_density_per_10s": 0.9,
  "vo_segments": 35,
  "vo_density_per_10s": 3.0,
  "bgm_changes": 8,
  "ducking_events": 0,
  "story_beats": 5,
  "quotes": 3,
  "emotion_segments": 0,
  "micro_motions": 5,
  "scene_timeline": 0,
  "macro_total_shots": 41,
  "macro_shots_match": true,
  "asl_macro": 3.83,
  "asl_calc": 3.83,
  "asl_match": true,
  "vo_ratio_macro": 0,
  "vo_ratio_calc": 126.1,
  "vo_ratio_match": null,
  "has_honesty_report": false,
  "honesty_details_count": 0,
  "null_fields": 0,
  "total_fields": 503,
  "null_ratio_pct": 0.0,
  "sfx_template_ratio_pct": 0.0,
  "shot_template_ratio_pct": 0.0,
  "script_full_text_len": 515,
  "json_size_kb": 14.0
}
```

---

> **报告终**
> 测试执行: 2026-07-26 | 报告生成: CatPaw (Anti-gravity)
> 测试视频: `01-7161327303857900812-第一次约会好尴尬呀`（主人必须屎，117.84s）
> 模型: gemini-3.6-flash
