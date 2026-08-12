> 本文件是 `video-analysis-gemini` 的执行细则（渐进披露拆分，2026-07-30）。核心架构/五大板块/四层门禁/反例黑名单见上级 [SKILL.md](../SKILL.md)；正文与拆分前逐字一致。

## agy CLI Headless 批量编排（2026-07-28 实跑固化）

> 本 skill 原设计假定 GUI Antigravity 交互式 view_file。2026-07-28 实跑验证了 **`agy` CLI（`~/.local/bin/agy`）headless 批量派发**可行（视频 view_file 多模态真实可用），并踩平一串坑。经此通道编排须遵守以下铁律。

**派发命令**：
```bash
agy --print "$(cat <任务提示>)" \
  --model gemini-3.6-flash-high \   # L2 感知；Pro 终审换 gemini-3.1-pro-high
  --add-dir <归档根> --dangerously-skip-permissions \
  --print-timeout 95m --log-file <debug.log>
```

**铁律 1 — 必须出沙箱运行**（否则长会话 100% 暴毙）：Agent/nohup 若继承受限沙箱（仅工作区可写），agy 写 `~/.gemini/` token 与 code-action 写盘均 `operation not permitted`；token 每小时约 :26 到期刷新写盘失败 → 401 UNAUTHENTICATED → 会话终止。驱动须以宿主完整权限启动。

**铁律 2 — agy 只“看+写”，计算/门禁/状态全部下沉本地 Python**：
- L2：agy 只 view_file + 用 **write_file 工具**写 `analysis_<date>.json`（**禁 python/code-action 写盘**——沙箱拦截，且把脚本存成 .json 正是伪造源头）。
- Pro：agy 只 view_file 抽查 + write_file 写 `_pro_review_result.json`。
- finalize-l2 / 评分 / ingest / L4 组包 / 状态跳变由**编排方在 agy 会话外**跑；不要让 agy 在会话末尾跑收尾命令（末尾跑命令易报错终止，虽产物已写好）。

**铁律 3 — token 边界重试**：会话跨整点 token 到期有 401 竞态。对**基础设施性失败**（无 JSON / 解析失败 / 缺板块 / 无产物）自动重试（落在刷新后干净窗口）最多 2-3 次；**内容质量失败**（骨架/占位/等长）不重试。

**agy 能力边界（实测，决定派发范围）**：

| 视频类型 | 结果 | 说明 |
|---|---|---|
| 短/中片 ≤~180s、镜数适中 | ✅ 稳定全流程 | 07(179s/38镜)、11(111s/63镜) 一次过；单视频 L2 20-55min + Pro 5-28min |
| 极密镜（如 93 镜） | ❌ 单板块耗尽输出预算 | 只写出 cinematography，其余 4 板块未产出 |
| 长片 ≥~220s | ❌ 常无产出 | 观看耗时长，写盘前会话已断 |

> **派发前按此预筛**：只喂 agy 短/中片；长片/密镜走 GUI 手工或分段观看，不浪费配额。

**编排纪律**：**串行 + 每条验收**（沿用反并行铁律，防伪造放大）；**快速失败**（同一失败签名连续 2 次即跳过该视频，勿死磕 3 次浪费配额+时长）；**熔断**（连续 2 个硬失败停批，保护 Gemini 配额）。可复用驱动样板见 `.kb/runs/overnight-video-20260727/`（overnight_driver.sh + gate_check.py + L2/Pro 提示模板）。

> **验收铁律：机器门禁 ≠ 防伪。** 纯密度/schema 门禁曾放行 110 镜“第N镜…画面细节描述”骨架（密度因镜多而通过）。必须叠加**内容抽样**（读真实画面比对）+ `check_placeholder_forgery` 的模板套话/去数字唯一度检测（2026-07-28 已固化进门禁）。

> **驱动样板 gate 检查器禁把视频目录全路径交给 `glob.glob`（2026-08-05 jiayitsui 事故）**：视频目录名含 `[1hKnX4ehkGQ]` 方括号（YouTube ID），`glob.glob(os.path.join(vdir,"analysis_*.json"))` 会把目录段当字符类通配符 → 永远匹配失败 → 有效产物被误判"无 analysis_*.json"拒收（今早 5 条全部中招，其中 2 条产物实为有效）。skill 正式脚本（session_guard/pro_qa_inspector 等）用 `Path.glob("analysis_*.json")` 只匹配文件名段，**不受影响**；只有 run 目录驱动样板里的 `gate_check.py` 用 `glob.glob` 踩坑。修复：`latest_analysis()` 改用 `os.listdir` 过滤文件名段。样板 `.kb/runs/overnight-video-20260727/gate_check.py` 与 `video-jiayitsui-20260801/gate_check.py` 均已修（2026-08-05）。复制驱动样板时务必检查此点。

> **view_file 目标禁写死 `_sense.mp4`，须按 grounding 的 view_file_target 动态解析（2026-08-05 小狗补写伪造事故）**：<10MB 的小视频（`sense: null`）不生成感知轨，`_sense.mp4` 不存在，正确观看目标是**原始视频**（grounding `view_file_target`）。若 prompt 写死 `_sense.mp4`：view_file 失败 → 会话若继续编造板块写盘 = 伪造事故。修复：prompt 里写「用 view_file 打开 grounding view_file_target 指定的视频（_sense.mp4 存在则用它，否则用原始视频）」；编排方在派发前读 `_grounding_payload.json` 的 `view_file_target` 确认目标存在。

> **ViewFile 物理门禁判定升级（2026-08-05 v5）**：`Step_ViewFile approved=true` 只代表工具被批准执行，不代表执行成功——失败调用也留 approved 行（小狗伪造会话 approved=1 但 view_file 实际 failed to read file）。正确判定：**成功 = max(日志 approved 数, 轨迹库 ViewFile 签名数) − 媒体失败调用数**；且目标媒体文件必须存在于磁盘（文件不存在 = 必失败）。媒体失败 = 轨迹库 "failed to read file" 总数 − 非媒体失败（schema_contract 等 /scripts/ 路径错误，乌龟 L2 实测 8 次失败全是契约文件路径错，与看片无关）。仅数轨迹库 "ViewFile" 字样不可靠：成功签名不出现在轨迹库，失败堆栈（ViewFileToolConverter）反而含 ViewFile。重构版：`check_viewfile_gate_v2.sh`（jiayitsui run 目录，2026-08-05）。

### 修复循环策略（agy 定向小会话，2026-07-28 铁头阿彪 12/12 清账实战验证）

对"内容真实但局部缺陷"的产物，**禁止全量重跑**（烧配额+丢真实内容），按缺陷类型派定向小会话：

| 缺陷签名 | 策略 | 实战 |
|---|---|---|
| 时长量化（连续≥8镜等长） | **时间轴定向修复**：只改 shot start/end，内容一字不动；大片被中断后只修残留区段（提示里给区段 index+时间范围+首尾边界锚点，只重看对应片段） | 08 一轮过；12 三轮收口（r2超时修完前63镜→r3定点续修两区段） |
| 单板块耗尽预算（缺板块） | **补写会话**：已有板块严禁改动，只补缺失板块（读契约+与已有时间轴对齐） | 10 补4板块；09 B段+仅补sop收尾 |
| 长片（≥~200s）/密镜 | **拆写**：A段 `_meta+cinematography+ai_fx` → B段 `audio+narrative+sop`，各段渐进落盘（B段死于token边界时已写板块不丢，续跑只补剩余） | 12(144镜)、09(173镜/178切点) 均全流程达成 |
| 机械元数据缺陷（字段别名 sound/timestamp_sec、顶层布尔漏写、total_shots 不同步） | **编排方本地机械修正**：纯键名映射/计数同步，零编造（先例：01号别名归一） | 10 sound→description×23；09 元数据补全 |

- 每次修复会话**先备份 JSON**；修后 diff 验收三件套：未授权板块 0 改动 + 内容保留率（visual_content 逐条比对）+ 门禁复跑。
- 长片单会话（Pro终审/修复）约 20-40min 可在一个 token 窗口内完成；只有"全片观看+全量生成"才必须拆写。

