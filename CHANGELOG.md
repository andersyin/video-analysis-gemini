# CHANGELOG — video-analysis-gemini

## 2026-07-28 · agy CLI headless 批量编排实跑固化 + 骨架变体门禁补齐

**背景**：首次用 `agy` CLI headless 自主过夜跑铁头阿彪 07-12（原 skill 只设想 GUI 交互式 view_file）。实跑净交付 07/11 全流程（Pro 95），并踩平沙箱/token/字段契约/伪造一串坑，经验固化进 SKILL。

- SKILL.md 新增《agy CLI Headless 批量编排》节：铁律①必须出沙箱运行（否则 agy 写 `~/.gemini/`token 与 code-action 均 `operation not permitted`→整点 token 到期 401 暴毙）；铁律②agy 只 view_file+write_file，finalize/评分/L4/状态跳变下沉编排方本地跑；铁律③token 边界对基础设施性失败重试、内容质量失败不重试；实测能力边界表（短/中片✅、密镜/长片❌）+ 派发前预筛。
- `check_placeholder_forgery` 补骨架变体检测：模板套话正则（“画面细节描述”类）+ shot visual_content 去数字后唯一度<50% 拒收——堵住旧正则（只锚定纯英文 `Shot N`）漏掉的中文骨架“第N镜…描述”。回归：08 伪造骨架 110 镜命中拒收 ✅、07/11 真件 PASS、10 真实密镜零误伤。
- `pro_qa_inspector`/`ip_sop_compiler`/`asset_pool_archiver` 三处软字段 `ducking_and_silence` 为字符串时 `.get()` 崩溃 → 加 isinstance 守卫；`validate_pro_result` 契约兼容 `details_sampled`(list/int)、`mismatches`(顶层/内层)。
- 反例黑名单 #31（骨架变体过密度门）；视频规格表补 headless 实测边界注。
- 清理：skill 根目录 4 个伪造生成器残留脚本（generate_analysis_08/09.py、fix_shots_08.py、update_json.py，机械编造均分镜/假VO）移入 `_forgery_quarantine_20260727/`。
- 可复用驱动样板 `.kb/runs/overnight-video-20260727/`（overnight_driver.sh + gate_check.py + L2/Pro 提示模板 + 熔断/快速失败）。

## 2026-07-27 · 契约门禁补齐 timeline 条目级字段校验（schema 漂移最后一个缺口）

**背景**：01 号重感知产物顶层字段齐全、但镜头条目用了变体字段名（shot_id 代 index、fx_type 代 technique、无 shot_type）——契约完整性门禁只查板块顶层，条目级盲区导致下游渲染器/聚合脚本照样踩雷（仿写参照生成时实踩）。

- `check_contract_completeness` 新增 timeline_item_min_fields 校验：契约含条目级必填的板块（cinematography.shot_timeline / ai_fx.scene_timeline）逐条检查，缺字段 → 拒收（报缺失条数）
- 回归：01 号 REJECT（index 39/39、shot_type 39/39、technique 8/8 全命中）；02/04 号零误伤
- 已交付的 01 号做机械别名归一（index←shot_id ×39、technique←fx_type ×8，纯键名映射不编造）；shot_type 39 条缺失如实保留——已交付资产的已知债务，待定向补感知时回填

## 2026-07-27 · 铁头阿彪01 重感知二次验收：ai_fx 边界盲区修补 + SOP 编译器类型防御

**背景**：01 号重感知交付（Pro 98/round 3）后主 Agent 二次验收发现：① ai_fx.scene_timeline 两条整体 +100s 越界（247-256s/297-300s > 总时长 233.8s）——物理边界硬拒只查 6 轨不含 ai_fx，门禁盲区；内容本身有同 JSON 交叉证据（shot@147-155 剪影打斗/VO@198 老紫蜀道山），属时间戳笔误非编造，已定向 Patch 归位；② ip_sop_compiler 对 sop.asset_reusability 假定 dict，遇字符串型（契约允许的显式否定值/纯文本）崩溃。

- `session_guard.check_density_gates` 物理边界检查新增 ai_fx.scene_timeline / ai_fx.micro_motion_moments 两轨；越界注入自测 REJECT ✅
- `ip_sop_compiler.compile_shooting_sop` asset_reusability 兼容 dict/纯文本双型态
- 01 号终态：修补后全门禁复跑 PASS，Layer 4 交付完成（SOP 12KB + 音效库 115 条），质量对比旧版：39 真实镜（vs 142 模板填充）/ 8 段风格化 ai_fx（vs “全实拍”）/ 台词多模态听写无足球污染 / stt_low_coverage 0.36 降级标记生效

## 2026-07-27 · A/B 实验终判：模态并发暂缓转正 + 算法切点锚点反哺主流程

**背景**：两条 A/B 实测完成。第 1 条（03 号，109s）三判据全过（Pro 95±0/镜头密度 2.93→5.31/真实 triad 100%）；第 2 条（02 号，214s 快切片）判据② FAIL——镜头 126→66，ffmpeg 实测 ~185 硬切点（scene>0.35），实验组漏切近 2/3。根因非拆分退化（两条真实 triad 均 100%），而是 mid 档 ASL 3-8s 规则误导模型对快切视频合并镜头；另 wall-clock 两条均未提速，并发主卖点不成立。

### 决策

- 实验模式**暂缓转正**，冻结在实验通道（SKILL.md 章节标注 🔒 评估结论）；merge_subagents.py 保留可用，待平台真并发提速能力后重评

### 算法切点锚点（副产品反哺，单体/实验双受益）

- `preprocessor.py` 新增 `detect_scene_cuts()`（ffmpeg scene>0.35 计数，感知轨上约 10-20s/条），payload 新增 `_scene_cut_estimate`
- `prompt_header.json` 物理边界声明新增第 4 条：镜头数应与算法量级一致，快切视频禁止按档位合并
- `session_guard.check_density_gates` 新增切点锚点软告警：shot 数 <算法切点 50%（漏切）或 >2.5×（填充）告警不拒收
- 验证：02 号基线 126 镜无告警、实验组 66 镜精确触发漏切告警；全库 payload 后台回填中（`_scene_backfill_20260727.log`）

## 2026-07-26 · biaoda.me 同片对比复盘：finalize-l2 三新门禁 + Layer 4《仿写参照》

**背景**：用 biaoda.me 网页拆解工具对铁头阿彪01/04 做同片对比（02 号作方法对照），暴露三个已交付资产带病过审的漏洞：① 01 号 shot_timeline **142/142 条**为严格等长 1.65s（= baseline ASL）+ 同一句复制描述的模板填充，凑密度绕过密度门禁拿 QA 95 分；② 01 号 Whisper 覆盖率 0.53（川渝方言错听“组织→足球”），narrative 直接引用错听文本长出“足球退役人物”虚构故事线；③ 04 号 schema 漂移（7 个契约软必填字段缺失，含商单视频的 monetization）带 QA 98 分过审。Pro 抽查只验“真锦点”未命中填充区段——审计机制被“真锚点+假填充”组合绕过。

### 变更（代码 + 文档）

- `session_guard.py` finalize-l2/mark-flash-extracted 新增三道检查（均在密度门禁之后）：
  - **2.6 契约完整性门禁**（`check_contract_completeness`）：top 硬必填缺失/任意契约字段空块（{}/[]/""）→ 拒收；top_soft 缺失 → 告警
  - **2.7 反模板填充门禁**（`check_shot_authenticity`）：连续 ≥8 镜时长严格等长，或同一归一化描述 ≥5 次且 >30% → 拒收
  - **2.8 STT 低覆盖降级**（`check_stt_coverage_flag`，复用 pro_qa_inspector.cross_validate_whisper_vo）：coverage <0.70 不拒收，但写 `_state.json` 顶层 `stt_low_coverage` + 醒目告警（narrative 禁引 STT 文本结论）
- SKILL.md Layer 4 新增产物 5《仿写参照》`rewrite_reference_<date>.md`（Agent 从已过审 JSON 纯本地聚合：段落级结构视图/值得学习三栏表/复刻版仿写脚本/口播版），含三条写作铁律（禁凭记忆、禁通用模板、stt_low_coverage 时禁引 Whisper 原文）

### 验证（真实资产回归）

- 01 号：反模板 REJECT（连续 141 镜等长 + 142/142 重复描述）+ STT 0.53 降级标记 ✅
- 02 号：三门禁全 PASS（STT 1.0），零误伤 ✅
- 04 号：硬门禁 PASS + 7 条软必填告警（schema 漂移显形）✅
- 结论同步：biaoda 不接管道（无 API/自身无自检/外发依赖），仅作重点视频人工第二意见（story beats 对不齐 = 重感知信号）

## 2026-07-26 · L2 写前预检铁律 + 空返回诚实度铁律（事故：铁头阿彪02 finalize-l2 连拦 3 轮）

**背景**：铁头阿彪 02 号 L2 重感知中断 3 次，复盘定位三个根因：① 写 analysis JSON 前未预读 schema_contract.json，凭 SKILL.md 文字描述构造结构，一次漏 9 个契约必填字段（ai_fx.facial_animation / narrative.script_full_text·all_quotes·macro / sop.complexity_breakdown 等）；② honesty_report 写到顶层而非 `_meta` 内；③ view_file 加载视频返回空内容，却仍在 honesty_report 写 `view_file_called: true`（实际内容靠 Whisper + 九宫格推断，诚实度缺陷）。硬门禁只能事后拦截，每拦一轮多付一轮修补代价。

### 变更（纯文档，无代码改动）

- SKILL.md Layer 2 步骤 2 升级为**写前预检铁律（Pre-flight Read）**：感知/写 JSON 前必须按顺序真实读取 ① schema_contract.json（必填字段对照清单）→ ② prompts.json + prompt_header.json → ③ _grounding_payload.json，禁止凭记忆构造 JSON 结构
- Layer 2 步骤 3a 新增**空返回 = 感知失败**：view_file 响应无实际音视频内容时禁止写 `view_file_called: true`，只能重试或显式走紧急降级模式
- 步骤 3e JSON 示例补入 `_meta.honesty_report` 占位 + **位置铁律**（必须在 `_meta` 内；5 板块 sections 各含 `view_file_watched: true` + evidence）
- 输出前自检新增第 8/9 条（契约字段逐一对照、honesty_report 位置与板块覆盖）；反例黑名单新增 #27（凭记忆构造结构）、#28（空返回仍自报真实观看）

### 补充（同日 22:51 第二轮复盘：新增两类环境级失败模式）

**追加背景**：同一任务的第二轮复盘定位另外两个平台/环境级根因：③ L2 为 45-70 分钟大流式调用，会话上下文被平台截断后断点记忆丢失；④ 宿主工具层 view_file 报 `unsupported mime type video/mp4`，Pro 阶段B 无法在本宿主抽查视频。根因①（写完 JSON 结束回合）系 c97c5b1f 同一行为违规再次复现。

- 规则 1 执行顺序第 3 条追加操作化口径：**写入第 5 个板块的那一回合，finalize-l2 必须在同一回合内**（末板块写盘与 finalize-l2 不允许隔回合），并登记铁头阿彪02 复现记录
- 失败模式表新增 2 行：**会话上下文被平台截断/压缩**（不信记忆、以磁盘为准盘点已完成板块，只补缺失）；**宿主不支持视频 view_file**（L2 禁止在该宿主继续；Pro 阶段B 可派发原生视频 Pro subagent 持审查包抽查，禁止降级为非观看式抽查）
- Layer 3 阶段B 新增「宿主不支持视频 view_file 时的合法回退」说明（subagent 路径 + 规则 5 登记/二次验证）
- 步骤 3e `_meta` 示例补入 `analysis_method`（第二轮复盘确认该必填字段也曾缺失）

### 补充 2：preflight watchdog（机制化堵死行为违规，代码改动）

**背景**：「写完 JSON 未跑 finalize-l2」已两次复现（c97c5b1f、铁头阿彪02），铁律文字挡不住行为违规；且旧 preflight 对此类遗孤（状态停 PREPROCESSED）会推荐重进 L2，白白浪费一次 45-70 分钟完整感知。

- `session_guard.py` 新增 `inspect_orphan_analysis()`：PREPROCESSED 状态下以磁盘为准盘点最新 analysis 的板块完成度
- preflight 分诊升级：齐 5 板块 → **P0_遗孤**（直出 finalize-l2 命令含正确 date，禁止重进 L2）；部分板块 → P3 续跑只补缺失板块（上下文截断恢复）；无 analysis → P3 重进 L2（与旧行为一致）
- summary 新增 `orphan_analysis_unfinalized` 计数，stderr 摘要新增 P0 醒目提示；P0 排序先于 P1
- SKILL.md 同步：四层防御表第 4 层改「前检查 + watchdog」；优先级清单新增 P0_遗孤条目
- 验证：合成 3 场景（遗孤/半成品/未开工）8 项断言全 PASS；真实资产库回归铁头阿彪（15 条）+ kat-and-oliver（15 条）零误伤，且在铁头阿彪 05 号抓到真实半成品（仅 cinematography 落盘）并正确给出「只补 4 个缺失板块」建议

### 补充 3：emit-l2-skeleton 骨架生成器（写前预检机械化，代码改动）

**背景**：写前预检铁律仍依赖 Agent 自觉阅读契约；把结构对齐从「自觉阅读」升级为「机器发牌」，从源头杀死 Schema 类门禁打回。

- `session_guard.py` 新增 `emit-l2-skeleton` 子命令：从 schema_contract.json 生成含全部必填字段的 analysis 骨架（`_meta.honesty_report` 嵌套结构/`analysis_method`/逐板块 top+macro）+ stderr 必填清单；支持 `--out`（硬拒 analysis_*.json 文件名，防污染 watchdog 盘点）
- 安全设计：honesty 预置 false、timeline 预置 []，不真实填写必被 finalize-l2 拒绝，骨架无法被当作伪造产物
- SKILL.md Layer 2 步骤 2 新增「预检机械化」入口；工具集表同步
- 验证：骨架对照契约逐字段断言——全部 top/macro 必填字段在位（含铁头阿彪02 事故漏掉的 9 字段），honesty sections 覆盖 5 板块；analysis_*.json 文件名硬拒生效；watchdog 自测 8 断言回归全 PASS

## 2026-07-26 · 物理锚点三层防线 + 单视频模态并发（实验模式）

**背景**：采纳两项升级建议——① 物理锚点前置注入（封死超时长幻觉，A/B 报告曾实锤裸 prompt 幻觉 39s 时间轴）；② 多智能体并发感知（缓解单体长上下文注意力涣散与速度瓶颈）。② 与「禁止并行」历史铁律冲突，故以实验模式 + 转正门槛落地，不直接替换主流程。

### 物理锚点（即时生效，三层防线）

- `preprocessor.py`：payload 新增 `_system_boundary`（strict_duration_sec/strict_fps/total_frames/time_range_rule）
- `prompt_header.json`：头部新增【物理边界声明·绝对铁律】模板 + 3 个新 field_mappings
- `session_guard.check_density_gates`：新增物理边界硬拒——六类时间轴任一时间戳 > 真实时长+0.5s 即 failure（finalize-l2/mark 两入口同时生效）
- 验证：铁头阿彪 02 真实交付件 0 误伤；注入 999.9s/250.0s 篡改件被硬拒（overruns=2）

### 单视频模态并发（实验模式，未转正）

- 新增 `merge_subagents.py` 主节点缝合器：收 visual/audio/narrative 3 分块 → honesty 铁律验证（任一 Subagent 未真实观看即作废）→ 物理硬截断（start 越界剔/end 越界截）→ SFX×切镜 ±0.2s 自动补 triad_coupling → 密度预检（不达标输出定向补感知指令到具体 Subagent）→ 组装标准 analysis（perception_mode: subagent_concurrent_v1）
- SKILL.md：并行禁令改口径为「禁跨视频并行」，新增实验模式章节（分工表/并发 ≤2 路/audio 可用 _sense_audio.m4a）
- **转正门槛**：ab_compare 连续 2 条 ① Pro ±5 ② 密度不降 ③ 真实 triad_coupling 覆盖率 ≥基线 80%（防跨模态感知退化被缝合器掩盖）
- 端到端测试：02 号交付件拆 3 分块+注入越界条目 → 剔 1 截 1、密度预检过、产物结构完整

## 2026-07-26 · 渐进落盘铁律（事故 2d8ee957：单轮输出上限吞掉感知成果）

**背景**：铁头阿彪 02 号第二次 L2 尝试（任务 2d8ee957）：感知完整完成（48 镜/24+ SFX/132 句 VO 对齐），但在一次性组织 5 板块巨型 JSON 时触发单轮输出上限，analysis 未落盘，成果只存在于会话上下文——比原子绑定间隙更早的新失败点。

### 变更（纯文档，无代码改动）

- SKILL.md Layer 2 步骤 f 新增**渐进落盘铁律**：每完成一个板块的感知立即写入/更新 analysis 文件，禁止攒到最后一次性输出；半成品无风险（状态仍 PREPROCESSED，finalize-l2 校验 5 板块齐全才放行）
- 失败模式表新增「单轮输出上限中断」行：上下文仍在 → 续接后第一动作分批写盘（禁止重新推理），风险由 Pro 阶段B 抽查兜底；上下文已丢 → 重进 L2 + 渐进落盘
- 接力包顶部新增「19:21 第二次中断续接指令」（路径 A 续接写盘 / 路径 B 重看）

## 2026-07-26 · finalize-l2 一键化加固（针对行为违规失败模式）

**背景**：Antigravity transcript c97c5b1f 实锤新失败模式——Agent 写完 analysis_2026-07-26.json 后 Step 52 空响应主动结束回合，未跑 f2/f3 两步，产物成孤儿（状态悬空 PREPROCESSED）；后续服务重启/SSE EOF 仅为补刀。铁律文字约束挡不住行为违规，改用机制堵死。

### 变更

- `session_guard.py` 新增 **`finalize-l2`** 子命令（推荐入口）：完整复用 mark-flash-extracted 的验证+密度门禁+状态写入，门禁通过后**同进程**拉起 `pro_qa_inspector.py --emit-review-packet`——f2/f3 两步合一，原子绑定间隙物理消失。任一环节失败同进程退出、状态不动，天然幂等
- `cmd_mark_flash_extracted` 加 `print_next_hint` 参数（finalize 模式下不打印手动指令），旧两步式保留兼容但不再推荐
- SKILL.md 同步 4 处：规则 1 执行顺序改为一条命令 + 新增「禁止写完 JSON 就结束回合」；Layer 2 f2/f3 合并；状态机铁律白名单；工具集表
- 接力包（铁头阿彪 02 号）执行清单同步改用 finalize-l2

### 验证（2026-07-26）

- 失败路径：02 号真实目录（无 analysis）→ rc=1 干净拒绝，状态未动
- 成功路径：铁头阿彪 01 影子副本（/tmp，重置为 PREPROCESSED）→ 一条命令直达 PRO_AUDITING，history 完整（PREPROCESSED→FLASH_EXTRACTED→PRO_AUDITING），packet 就位；测试目录已清理

## 2026-07-26 · 吞吐提速批次 1（验收后提速建议 1+3 落地）

**背景**：验收发现质量机制健全但吞吐极低（95 条仅交付 1 条）。提速主攻两个零质量风险点：L1 批量预跑 + 感知轨阈值下调。

### 变更

- **新增 `batch_preprocess.py`**：批量 L1 驱动（每账号一次调用，递归扫描源目录，video_id = 文件名 stem 与 scan_helper 一致）。幂等跳过：`_state.json` 状态 ≠ UNPROCESSED 的视频不重跑（保护在途/已交付）。L1 是纯本地 CPU 工作，不受「禁止并行派发」约束（该禁令针对 LLM 批量感知编造）
- **感知转码阈值 20MB → 10MB**（`preprocessor.py` DEFAULT_SENSE_THRESHOLD_MB）：一次 broken pipe 的代价是整段 L2（45-70min）重来，转码已验证不伤感知，更小请求体压低上传失败率与传输耗时
- SKILL.md 同步：阈值口径 4 处 + Layer 1 批量模式用法 + 工具集表注册 batch_preprocess.py
- 环境修复：whisper CLI 缺失（历史产出证明曾可用），以 `uv tool install openai-whisper` 重装（`~/.local/bin/whisper`，model base，与 preprocessor 现有调用接口匹配）
- 补建账：`jiayitsui 碎嘴 naomi`（YouTube）、`羊和狗刻`（抖音）执行 `--init-account`，6 账号建账齐全

### 首次执行（2026-07-26）

- 单条验证：铁头阿彪 03（68.1s/条：Whisper 42 句 + 感知轨 75.8MB→5.9MB + baseline 真实注入）
- 全量批次后台启动（6 账号 ≈ 90 条），日志：`<archive-dir>/_batch_l1_20260726.log`，runner：`scripts/run_batch_l1_20260726.sh`（一次性，可重复执行）

## 2026-07-26 · 过程文件清理升级（隔离区机制）

**背景**：实跑前的例行清理发现 `cleanup-sense` 两个缺口：① 只删不移，不可逆；② 不覆盖 v1.2 前残留的 Whisper 原始 `<片名>.json`（内容已并入 payload，属过期文件）。

### 变更

- `scan_helper.py --cleanup-sense` 新增 `--quarantine-dir`：指定后 `--apply` 改为**移动而非删除**，归档到 `<quarantine-dir>/<日期>/<账号>/<video-id>/`。统一隔离区约定为 `<archive-dir>/_process_archive/`
- 清理目标新增过期 Whisper 原始 JSON（与视频目录同名的 `<片名>.json`）
- SKILL.md「过程文件生命周期与清理」更新：过程文件表加 Whisper 残留行 + 隔离区用法 + 约定说明

### 首次执行（2026-07-26）

- 主人必须屎 TOP01：`_pro_review_packet.json` + 过期 Whisper JSON → 隔离区
- 铁头阿彪 TOP01：同上 2 个 → 隔离区
- 在途资产零接触：铁头阿彪 TOP02（PREPROCESSED，即将实跑）、奶糕「猫和老鼠」（PROBE_REPAIRING）全部完好
- 隔离区：`<archive>/_process_archive/2026-07-26/`（4 文件，0.2MB）

## 2026-07-26 · 密度口径统一 + 门禁自动化（基于 A/B 测试报告）

**依据**：`experiments/ab_test/AB_TEST_FULL_REPORT.md`。A/B 测试证明 skill 零幻觉但密度门禁未生效；同时坐实 v1.2 遗留的「感知密度表（每3s≥1镜）vs 自适应粒度适配器（中长视频 3-8s/镜）」口径冲突——A 路径 ASL 5.61s 按自适应表合理、按密度表违规，门禁标准自相矛盾导致无法自动化拦截。

### 口径统一（结构性修复）

- `schema_contract.json` v1.0.0 → **v1.1.0**，新增 `density_gates` 分段口径（唯一事实源）：
  - 短视频 (0-60s)：镜头 ≥3.3/10s、ASL 0.5-4s、SFX ≥2/10s、VO ≥1/10s
  - 中长视频 (60-300s)：镜头 ≥1.5/10s、ASL 3-8s、SFX ≥1/10s、VO ≥1/10s
  - 超长视频 (>300s)：shot 密度不做平铺门禁（走 Chapter 树状），SFX/VO ≥0.5/10s
  - POV/长镜头例外放宽镜头密度，但 honesty_report 必须声明拍摄风格（关键词检测）
  - `sfx_triad_coupling_min_pct: 50`、`honesty_view_duration_tolerance_sec: 1.0`
- SKILL.md 感知密度表改为分档表格 + 口径说明，消除与自适应粒度适配器的冲突

### 门禁自动化

- `session_guard.py mark-flash-extracted` 新增 `check_density_gates()`：从 `_video_meta.json` 读时长选档 → 计算镜头密度/ASL/SFX/VO → 不达标**拒绝标记 FLASH_EXTRACTED** 并输出回 L2 修复指引。挂在 L2→L3 原子绑定点，不增加会话往返
- `validate_schema.py` 新增硬门禁：`honesty_report.view_duration_sec` vs `_video_meta.json.duration_sec` ±1s 比对，防止诚实度报告本身造假（A/B 测试中直接 prompt 幻觉 33% 的防线）
- `validate_schema.py` 偷懒检测新增：SFX 三元耦合覆盖率 <50% 告警；`ai_fx.generation_evidence` <3 条或 sec 超时长告警

### AI/FX 判定证据化

- 契约 `ai_fx.top_soft` 新增 `generation_evidence`（≥3 条帧级证据，sec+evidence）；prompts.json 同步声明并通过 `--check-contract-sync` 🟢
- 背景：A/B 两路径对"是否有 AI 生成痕迹"给出相反结论，判定必须挂帧级证据

### ab_compare.py 等值误判修复 + 固化

- 旧版 `"A" if a>b else "B"` 等值默认判 B（单次测试 5 项误判），正式版迁移至 `scripts/ab_compare.py`，统一 `_winner()` 三路判定（A/B/tie），新增 `--json-out` 供回归消费
- `experiments/ab_test/ab_compare.py` 改为兼容入口转发，避免双份维护漂移
- 修复版重跑原始数据：A 11 / B 8 / tie 7，与报告人工修正结果一致

### 验证

- 密度门禁对主人必须屎 TOP01（117.84s → mid 档）：镜头 1.78≥1.5 ✓、ASL 5.61∈[3,8] ✓、SFX 0.51<1.0 ✗ 正确拦截（SFX 遗漏是唯一真实密度缺口）
- honesty 门禁合成样本（声称 157s vs 真实 117.84s）：✅ 正确 RED 拦截
- 契约同步校验：🟢 prompts.json ↔ schema_contract.json 完全对齐

### 遗留（下一步）

- A/B 结论样本量 N=1，需补 3 条不同类型视频（口播/Vlog/AI 生成类）再确认普适性
- 本次 A/B 视频的"纯实拍 vs AI 口型驱动"矛盾判定需人工观看裁定

## 2026-07-26 · 会话寿命管理（v1.2 → v1.3）

**根因**（第二次死亡复盘）：同一视频今天死两次，死因都是会话在 L2→L3 间隙耗尽。L2 是 45 分钟的 `view_file` 大流式调用（重活），L3 阶段A 是秒级脚本（轻活）。会话死在"刚干完最重的活、还没来得及跑轻活"的间隙。三个叠加因子：① 大流式调用乘积衰减（10+ SSE 传输/视频，每次都是断流掷骰子）；② 单会话上下文持续膨胀（4 条视频 payload + prompts + JSON 全堆同一会话）；③ Agent 手写 `_state.json`（出现脚本不写的 `attempts:0`、25 秒早产 `FLASH_EXTRACTED`）。

### 新增

- `scripts/session_guard.py`（会话寿命管理器，三命令）：
  - `mark-flash-extracted`：**替代 Agent 手写 `_state.json`**。验证 analysis JSON 存在 + 5 板块齐全后才写 `FLASH_EXTRACTED`，消除早产标记。写完后输出 L3 阶段A 命令，实现 L2→L3 原子绑定。
  - `preflight`：**开工前扫描**。全量视频状态扫描 → 找到卡在 L2→L3 间隙的（`FLASH_EXTRACTED` 但无 `_pro_review_packet.json`）→ 输出优先行动清单（P1_紧急/P2/P3/P4）+ 会话预算追踪（剩 ≥1 才可开始新 L2）+ 篡改检测。
  - `validate-state`：**状态篡改检测**。4 个签名：① `attempts` 字段（脚本从不写）；② 无 `history` 数组；③ `FLASH_EXTRACTED` 距 `PREPROCESSED` < 60s（早产标记）；④ `FLASH_EXTRACTED` 但无 `analysis_*.json`（不一致）。
- SKILL.md 新增「会话寿命管理」专章（4 条规则）：
  - 规则 1 · L2→L3 原子绑定（最高优先级）：`analysis` 写盘 → 立即 `session_guard mark-flash-extracted` → 立即 `pro_qa_inspector --emit-review-packet`，禁止间隙做任何 view_file
  - 规则 2 · 会话预算：每会话最多 3 条 L2，软提醒 2 条，硬限制 3 条
  - 规则 3 · 状态机完整性：只有 4 个脚本可写 `_state.json`，禁止 Agent 手写
  - 规则 4 · 前检查：开工前必跑 `session_guard preflight`，优先推进卡住任务
- Layer 2 工作流更新：步骤 0a 前检查 + 步骤 f2 `session_guard mark-flash-extracted` + 步骤 f3 立即执行 L3 阶段A
- 失败模式表新增 3 行：会话死亡（L2→L3 间隙）、会话预算耗尽、状态机被手写篡改
- 工具表新增 `session_guard.py` 行

### 验证

- `validate-state` 对猫和老鼠视频：✅ 检出 `attempts` 字段 + 25 秒早产标记（severity=critical）
- `preflight` 对猫和老鼠视频：✅ P1_紧急 "卡在 L2→L3 间隙" + 正确推荐 `pro_qa_inspector --emit-review-packet` 命令
- `preflight` 对铁头阿彪账号：✅ 12 条视频状态扫描，1 完成/1 在途/0 卡住，会话预算剩 1 推荐尽快收尾

### 设计判定

| 方案 | 结论 | 理由 |
|---|---|---|
| L2→L3 原子绑定（工作流规则） | ✅ **采用（核心方案）** | L3 阶段A 是秒级纯本地脚本，只要在 L2 落盘后立即执行，死亡半径就是零 |
| 会话预算上限 3 条 | ✅ 采用 | 今天死亡在第 4 个任务前后，限制在 3 条把乘积衰减的掷骰子次数控制在安全区间 |
| 脚本替代手写 `_state.json` | ✅ 采用 | 消除早产标记和格式不一致，状态机成为可信断点 |
| 前检查优先推进 | ✅ 采用 | 状态机续跑而非开新坑，每次死亡后新会话用 preflight 找到断点 |
| 会话心跳/保活探测 | ❌ 不采用 | 不可控（平台侧限制），且增加复杂度；状态机落盘已足够保证零损失 |

## 2026-07-26 · 大文件传输保护（v1.1 → v1.2）

**根因诊断**（基于两次中断的底层日志/堆栈）：54.2MB 视频经 `view_file` 放入请求体时 base64 膨胀 ~1.33×（→ ~72MB body），本地 Sidecar（127.0.0.1:12450）拒收超大 Request Body 主动断管——表现为两种错误签名：① 上传阶段 `write: broken pipe`（EPIPE，`stream_receive_count:0` / `streaming_duration:0s`，Agent 往已关闭的 Socket 写数据）；② 等待响应阶段 `read: connection reset by peer`。流式上下文断裂后 Continue 校验失败无法恢复。根因是单次传输体积过大，非模型能力问题。

### 新增

- `preprocessor.py` 感知专用转码（默认阈值 **20MB**——base64 膨胀后 ~27MB 请求体处于安全区间；`--sense-threshold-mb` 可调 / `--no-sense` 禁用）：
  - 两档递进：① 720p / H.264 CRF30 / superfast / AAC 96k → 仍超阈值 ② 540p / CRF34 / AAC 64k / fps≤30
  - scale 同时约束宽高（`min(iw,1280)`/`min(ih,720)` + AR decrease），竖屏视频（1080×1920）也能正确缩放——优于 `min(1280,iw):-2` 写法
  - 时长完整性校验（产物 vs 原片 ±1s），异常自动重试下一档；全档失败回退原文件并告警
  - 产物：`_sense.mp4` + `_sense_meta.json` + **`_sense_audio.m4a` 独立音轨**（2~3MB，音视解耦降级资产）；`_grounding_payload.json` 新增 `sense` 信息与 `view_file_target` 字段（Layer 2 实际加载路径）
  - 有感知轨时九宫格改从感知轨切帧（Pro 抽查画面与 view_file 严格一致）；Whisper STT 仍对原文件执行
  - `_state.json` 追加 `view_file_target`
- **紧急降级模式**（音视解耦最后兜底，SKILL.md 专章）：`_sense.mp4` 仍传输失败且网络层自查无效时，允许 `_sense_audio.m4a`（音频板块）+ `_contact_sheet.jpg`（场景级画面）组合感知。强制诚实标注：`analysis_method=audio_contact_sheet_degraded`、密度豁免说明、降级视频镜头维度不计入账号 ASL 基线、`_state.json` 记 `degraded: true`
- **网络层自查指引**（SKILL.md）：代理 NO_PROXY 须含 127.0.0.1/localhost；自建 Sidecar 超时（IdleConn/ResponseHeader/KeepAlive）≥300s
- **过程文件清理**：`scan_helper.py --cleanup-sense`（默认 dry-run，`--apply` 执行）——只清 `PASS_DELIVERED` 视频的 `_sense.mp4`/`_sense_audio.m4a`/`_pro_review_packet.json`（可再生），在途分析不动；**固化为流水线「第 8 步」**：报告输出后自动执行 `--apply`（状态门禁保证安全），收尾汇报需附清理结果；Whisper 原始输出 `<片名>.json` 改由 preprocessor 解析后自动删除（内容已并入 payload，此前无消费者滞留）。实测 dry-run 不误删、`--apply` 只清已交付、在途（PRO_AUDITING）完好

### 同日验收修复（主人必须屎 TOP01 验收发现）

- **硬门禁漏洞（P0）**：`pro_qa_inspector.py` 的 `run_hard_gate_checks` 此前只经 `_load_sections()` 读契约*板块列表*做存在性检查，**从不校验板块内 top 必填字段**——导致 `narrative.emotional_timeline`（契约 top 必填）缺失仍一路 PASS_DELIVERED。已新增 `_load_section_top_fields()` + 硬门禁逐字段检查（缺失/空数组/空对象均拦截），复测该 analysis 现在正确 RED 拦截
- **validate_schema 误报（P1）**：`avg_shot_length` 校验旧口径 `sum(duration_sec)/len`，Flash 产出常不含 `duration_sec` 字段导致 sum=0 误报不一致；已加 `end_sec-start_sec` 兜底，复测误报消除且真实缺失仍检出
- 验收暴露的口径冲突（文档层，未改）：SKILL.md「感知密度表」每3s≥1镜 与「自适应粒度适配器」中长视频 3-8s/镜 对 60-300s 视频存在矛盾，本次执行按自适应表（ASL 5.61s）合理——密度表后续应加中长视频口径注记
- 实测验证（20s/1080p/19.7MB 测试片）：一档 19.7→2.0MB（10%）、二档升级 19.7→0.8MB（4%）、阈值内不触发、无音轨源优雅跳过，全路径通过
- `pro_qa_inspector.py` 审查包 `pro_instructions` 修正：Pro 抽查的 view_file 加载路径优先取 `grounding.view_file_target`（原指令引用不存在的 `grounding.video_path` 字段，大文件场景 Pro 会回退原片直传，踩同一个传输坑）

### 设计判定（对四种优化提议的取舍）

| 方案 | 结论 | 理由 |
|---|---|---|
| 视频压缩（感知专用转码） | ✅ **采用（主方案）** | 保完整画面流+音频轨+时间流，不是抽帧降级；Gemini 感知对 720p/96k 完全足够 |
| 降低分辨率 | ✅ 已并入主方案 | 压缩的一部分（720p/540p 两档，宽高双约束兼容竖屏） |
| 音视解耦 | ✅ 采用为**紧急降级模式** | 音轨 2~3MB 传输成功率 ~100%；但不作为常规路径（九宫格无毫秒级时间轴），仅应急并强制诚实标注 |
| 切片 | ✅ 沿用既有能力 | `scan_helper.py --smart-split` 本就是 >5min 长视频方案，与转码可叠加（先转码再切片） |
| 九宫格切帧图替代 view_file | ❌ 拒绝作为常规路径 | 丢失音频轨/时间流/跨模态关联，违反反例黑名单 #9；九宫格保持 Layer 1 辅助定位 + 降级模式视觉输入 |
| Sidecar 网络层配置 | ✅ 采用为辅助自查项 | NO_PROXY / 超时配置消除网络抖动，但不替代转码（环境不可控时的主防线是降请求体体积） |

### 文档（SKILL.md）

- 视频规格要求新增「大文件传输保护」（含 broken pipe vs connection reset 两阶段错误签名、base64 膨胀依据、感知转码 ≠ 抽帧降级）+「网络层自查」
- Layer 1 产出新增 `sense` / `view_file_target` 字段说明与转码规则
- Layer 2 明确 view_file 加载路径取 `view_file_target`，禁止绕过感知轨直传原文件
- 失败模式表拆分「上传阶段 broken pipe」与「等待响应阶段 connection reset」两行，恢复路径一致：不要点 Continue，新会话从 `PREPROCESSED` 状态重进 Layer 2
- 新增「紧急降级模式（音视解耦 · 最后兜底）」专章（触发条件/执行方式/强制诚实标注/状态机规则）
- 新增「过程文件生命周期与清理」专章（设计资产 vs 过程文件分界 + `--cleanup-sense` 用法 + 量级参考）
- 反例黑名单 #9 修订：禁止**主动**降级；感知轨例外 + 紧急降级例外（须诚实标注）
- honesty_report 新增 `view_file_multimodal_sense_track` / `audio_contact_sheet_degraded` 取值约定

## 2026-07-25 · 首跑后升级改造（v1.0 → v1.1）

基于 TOP01 首跑验收（`验收报告_TOP01_2026-07-25.md`）+ Anti-gravity 风险审计（6 大隐患）的联合改造。

### 新增

- `scripts/schema_contract.json`（v1.0.0）：字段级唯一事实源。validate_schema / unified_gate / pro_qa_inspector 的必填表均从它读取。含 top/top_soft/macro/macro_soft 分级与 prompt_must_mention 同步检查键
- `validate_schema.py --check-contract-sync`：prompts.json ↔ 契约对齐校验（风险4：防双重维护漂移）
- `scan_helper.py --init-account`：轻量建账模式，创建 `_account_meta.json` + `_scan_log.json` + upsert 全局 `_index.json`（P1-2）
- `scan_helper.py upsert_index()`：补上 `_index.json` 无脚本写入的断链；正常扫描流程同步回写
- `pro_qa_inspector.py` 多轮留痕（P1-1）：
  - 每轮 `_pro_review_result_r<N>.json` / `_qa_result_r<N>.json` 自动归档（N = PROBE_REPAIRING 次数 + 1，风险2）
  - 组包写入 `analysis_md5`；组包间隔内 analysis 被修改自动记录 `PROBE_REPAIRING`（手动 patch 路径也留痕），上限 3 次熔断
  - ingest 校验 packet md5 一致性，拒收过期审查包
  - `_qa_result.json` 新增 `round` 与 `dimensions`（规则预检两维 + Pro 分）字段
- `_index.json` 交付回写闭环：`ip_sop_compiler.py` 回写 analyzed_count/asl_mean；`synthesis_engine.py` 回写 formula_name/asl_mean

### 修复

- **死锁（风险1）**：Layer 3 入口状态集由单一 `FLASH_EXTRACTED` 扩展为 `[FLASH_EXTRACTED, PROBE_REPAIRING, PRO_AUDITING]`（脚本内置校验 + SKILL.md 同步）
- **九宫格退化（P2-1 + 风险3）**：`preprocessor.py` 弃用 `fps=1/9`（每 9 秒 1 帧的语义错误），改为 `select='eq(n,...)'` 按总帧数等距精确抽 9 帧；duration<1s 兜底跳过；改为始终生成（删除 ASL<1.5s 限制）
- **死代码**：`validate_schema.py detect_laziness` 第 249 行提前 return 导致检查 1-12 永不执行，已恢复
- **切频 N/A（P2-2）**：`ip_sop_compiler.py` 改为内联计算 `total_shots/end_sec`，输出「22.6 次/分（0.38 镜/秒）」双单位
- **prompt_card 空列（P2-3）**：prompts.json sop 板块 JSON 示例补 `prompt_card` 字段（此前自然语言要求但模板未声明，Flash 不可能产出）；编译器加描述兜底
- **停顿数恒 0**：`synthesis_engine.py` 改读契约字段 `ducking_and_silence`（兼容旧键 silence_moments）
- **Hook 类型空**：`synthesis_engine.py` 增加从 `story_beats[beat_type=hook]` 派生兜底；`hook_analysis` 入契约软必填（⚠️）
- **tuple repr 泄漏（P3-1）**：`synthesis_engine.py` 新增 `fmt_counter()`，9 处 Counter 输出改自然语言
- **状态重复追加（P3-3）**：`PASS_DELIVERED`（ip_sop_compiler）与 `PRO_AUDITING`（pro_qa_inspector/unified_gate）追加幂等
- **告警轰炸（风险5）**：`preprocessor.py` baseline unknown 区分「全新账号首条 → ℹ️ Info」与「有分析记录但 _index.json 缺失 → ⚠️ Warning」

### 文档（SKILL.md）

- Layer 3 入口状态集 + 多轮留痕机制说明
- ASL 口径：数据层 2 位小数、展示层 1 位（自检规则与反例 #19 同步）
- Layer 2 执行流程新增第 0 步「账号建账」
- 工具集表加入 schema_contract.json / --init-account / --check-contract-sync，附契约同步铁律

### _trash 临时脚本合并确认（风险6 diff 审查）

| 脚本 | 意图 | 合并点确认 |
|---|---|---|
| add_honesty.py | SKILL.md 插入诚实度报告机制 | ✅ 已在（诚实度报告章节） |
| update_skill_single*.py ×3 | 强制单视频模式 | ✅ 已在（Layer 2 强制单视频模式） |
| fix_3p_issues.py | POV 密度例外 / 次要环境音 / 决策树 | ✅ 三处均已在 SKILL.md |
| tmp_fix_silence.py | validate_schema 移除 silence_moments 必填 | ✅ 契约 audio.top 无此字段，ducking_and_silence 为 top_soft |
| verify_top01.py | TOP01 数据质量一次性检查 | 一次性工具，无需合并 |

### 首跑顺带验证的既有事实

- prompts.json ↔ schema_contract.json 经 `--check-contract-sync` 校验对齐（🟢）
- TOP01 归档产物已用新脚本重编译：formula 停顿数 0→3、SOP 切频 N/A→22.6 次/分、Hook 类型派生补齐、`_index.json` 建账完成
