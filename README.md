# video-analysis-gemini

> Gemini 3.6 Flash 原生多模态视频制作技术分析 Skill

## 概述

专为 Antigravity AI 设计的视频分析工具，通过 Gemini 3.6 Flash 的原生音视频多模态能力，对对标账号视频进行制作技术全维度拆解并沉淀为可追踪资产。

## 核心特性

### 四层流水线架构

```
Layer 1: 预处理（信号显性化）
  ├── ffprobe 提取硬指标元数据
  ├── Whisper 毫秒级台词 STT
  ├── 动态九宫格卡点切帧图
  └── 注入账号 Baseline

Layer 2: 多模态感知（Flash 3.6 初拆）
  ├── view_file 原生音视频长上下文
  ├── 提取 5 板块结构化 JSON
  └── 附带诚实度报告证据链

Layer 3: 质检与对抗探针（Pro 3.1 深度审查）
  ├── 物理级硬门禁（Schema/密度/时间轴）
  ├── Pro 语义级审查（声画脱节/因果矛盾）
  ├── 对抗式定向探针
  └── 3 轮熔断机制

Layer 4: 交付与 IP 资产编译
  ├── 正式落盘 analysis_<date>.json
  ├── 触发 synthesis_engine 公式提炼
  └── 自动编译《IP 专属实拍与音频 SOP》
```

### 五大核心分析板块

| 板块 | 内容 |
|------|------|
| **cinematography** | 画面镜头语言（机位、景深、ASL 节奏、光影色彩） |
| **ai_fx** | AI 生成与合成技术（角色一致性、面部口型、道具融合） |
| **audio** | 声音工程（画外音特征、SFX 三位一体联动、BGM/Ducking） |
| **narrative** | 叙事结构（注意力曲线、信息差视角、金句双关） |
| **sop** | 制作 SOP（复杂度成本、可复用资产、商业植入） |

## 支持的视频规格

| 维度 | 支持范围 | 最佳区间 |
|------|---------|---------|
| 格式 | .mp4 .mov .webm .m4v .mkv .avi | .mp4 (H.264 + AAC) |
| 文件大小 | ≤ 2GB | 10MB ~ 300MB |
| 时长 | 15s ~ 60min | 15s ~ 5min |
| 分辨率 | 360p ~ 4K | 720p ~ 1080p |
| 帧率 | 24/30/60 fps | 30 fps |
| 音频 | 需带音频轨 | AAC 清晰音轨 |

## 快速开始

### 1. 环境配置

```bash
# 克隆仓库
git clone https://github.com/andersyin/video-analysis-gemini.git
cd video-analysis-gemini
```

### 2. 替换路径占位符

详见 [DEPLOY.md](DEPLOY.md)：

| 占位符 | 说明 |
|--------|------|
| `{{KB_BASE}}` | Knowledge Base 根目录 |
| `{{MEDIA_DIR}}` | 媒体资产目录 |
| `{{BASE}}` | 项目基础目录 |

### 3. 依赖安装

```bash
pip install -r requirements.txt  # 如有
```

### 4. 运行预处理

```bash
cd scripts
python3 batch_preprocess.py \
  --videos-dir /path/to/videos \
  --account your_account \
  --archive-dir /path/to/archive
```

### 5. 后台守护进程（macOS launchd）

```bash
# 安装 launchd 任务
cp launchd/com.kb.video-analysis-watchdog.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kb.video-analysis-watchdog.plist
```

详细说明见 [launchd/README_watchdog_install.md](launchd/README_watchdog_install.md)

## 目录结构

```
video-analysis-gemini/
├── SKILL.md                    # 核心技能说明（必读）
├── README.md                   # 本文件
├── DEPLOY.md                   # 部署说明
├── CHANGELOG.md                # 更新日志
├── assets/                     # 模板文件
│   ├── account_synthesis_template.md
│   ├── report_template.md
│   └── temporal_comparison_template.md
├── experiments/                # 实验记录
│   └── ab_test/
├── launchd/                    # macOS launchd 配置
│   ├── com.kb.video-analysis-watchdog.plist
│   ├── watchdog-wrapper.sh
│   └── README_watchdog_install.md
├── references/                 # 参考文档
│   ├── analysis_framework.md
│   ├── setup_准备与归档结构.md
│   ├── 分析工作流.md
│   ├── 失败模式与工具集.md
│   ├── 状态机与会话寿命管理.md
│   ├── 诚实度报告机制.md
│   └── agy_headless批量编排.md
├── scripts/                    # 核心脚本
│   ├── preprocessor.py         # L1 预处理
│   ├── session_guard.py        # 状态管理与守卫
│   ├── standalone_watchdog.py  # 独立看门狗
│   ├── unified_gate.py         # 物理级硬门禁
│   ├── pro_qa_inspector.py     # Pro 质检
│   ├── synthesis_engine.py     # 公式提炼
│   ├── cross_validate.py       # 交叉验证
│   └── ...
└── test-prompts.json           # 测试提示词
```

## 核心脚本说明

| 脚本 | 功能 | 层级 |
|------|------|------|
| `preprocessor.py` | Whisper STT + ffprobe + 九宫格切帧 | L1 |
| `session_guard.py` | 状态管理 + 预检 + 遗孤检测 | 全局 |
| `standalone_watchdog.py` | launchd 拉起的独立看门狗 | 监控 |
| `unified_gate.py` | Schema/密度/时间轴硬门禁 | L3 |
| `pro_qa_inspector.py` | Pro 语义审查 + 对抗探针 | L3 |
| `synthesis_engine.py` | 跨视频公式提炼 | L4 |
| `cross_validate.py` | 多维度自洽性检查 | 验证 |

## 模型路由

| 推理步骤 | 指定模型 | 理由 |
|---------|---------|------|
| 视频感知（`view_file`） | **Gemini 3.6 Flash** | 原生多模态、高通量、成本低 |
| 诚实度终审 + 语义质检 | **Gemini 3.1 Pro** | 反幻觉、因果推理 |
| 公式提炼（跨视频归纳） | **Pro 3.1（Agent 模式）** | 需要跨条目归纳、因果链推理 |
| 战略借鉴决策 | **Pro 3.1（Agent 模式）** | 需要理解用户 IP 特征 |

## Anti-Skip 铁律

禁止跳层执行！每层入口必须验证上一步产出文件存在：

| 入口 | 前置条件 |
|------|---------|
| L1 | `current_state = UNPROCESSED` |
| L2 | `_grounding_payload.json` 存在 + `current_state = PREPROCESSED` |
| L3 | `analysis_<date>.json` 含 5 板块 + 状态 ∈ `[FLASH_EXTRACTED, PROBE_REPAIRING, PRO_AUDITING]` |
| L4 | `_qa_result.json` 存在且 `qa_passed = true` + `current_state = PRO_AUDITING` |

## 反例黑名单（不要做什么）

详见 [SKILL.md](SKILL.md) 第 166 行起，关键几条：

- ❌ 让 Gemini 做"为什么火""总结规律"等推理 → Agent 完成所有推理
- ❌ 覆盖旧 `analysis_*.json` 文件 → 每次新建，旧文件永久保留
- ❌ 跳过第 2 步质控直接提炼公式 → 先确认 100% 覆盖
- ❌ 主动降级为抽帧/切片分析 → `view_file` 无法加载则记录失败
- ❌ VO 转录只分 3 块 → 每一句独立说话/换气为一条
- ❌ SFX 只标 3 个 → 每 10 秒 ≥2 个 SFX

## License

MIT

## 贡献

欢迎 Issue 和 PR！

## 致谢

- 本 Skill 专为 [Antigravity AI](https://github.com/andersyin) 生态系统设计
- 基于知识库 `.kb/` 规约体系构建

## 相关文档

- [SKILL.md](SKILL.md) - 完整技能说明（必读）
- [DEPLOY.md](DEPLOY.md) - 部署指南
- [CHANGELOG.md](CHANGELOG.md) - 版本历史
- [references/](references/) - 技术参考文档