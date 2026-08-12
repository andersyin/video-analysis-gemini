# 部署说明

## 环境配置

本项目使用占位符代替个人绝对路径，部署时需替换为实际路径。

### 占位符说明

| 占位符 | 说明 | 示例 |
|--------|------|------|
| `{{KB_BASE}}` | Knowledge Base 根目录 | `/Users/yourname/Documents/KnowledgeBase` |
| `{{MEDIA_DIR}}` | 媒体资产目录 | `/Users/yourname/Media/Research` |
| `{{BASE}}` | 项目基础目录 | `/Users/yourname/Documents` |

### 替换方法

```bash
# 在项目根目录执行
find . -type f \( -name "*.py" -o -name "*.sh" -o -name "*.plist" -o -name "*.md" \) -exec sed -i '' \
  -e "s|{{KB_BASE}}|$KB_BASE|g" \
  -e "s|{{MEDIA_DIR}}|$MEDIA_DIR|g" \
  -e "s|{{BASE}}|$BASE|g" \
  {} \;
```

或手动修改以下文件中的占位符：
- `scripts/standalone_watchdog.py`
- `scripts/cross_validate.py`
- `scripts/vc_cross_acct.py`
- `scripts/vo_quality_check.py`
- `scripts/run_batch_l1_20260726.sh`
- `launchd/watchdog-wrapper.sh`
- `launchd/com.kb.video-analysis-watchdog.plist`
- `launchd/README_watchdog_install.md`
- `references/setup_准备与归档结构.md`

## 依赖安装

```bash
pip install -r requirements.txt  # 如有
```

## 快速开始

详见 [SKILL.md](SKILL.md) 核心使用指南。

## Launchd 配置

launchd 相关配置在 `launchd/` 目录，安装前需先替换路径占位符。

```bash
# 复制 plist 到 launchd
cp launchd/com.kb.video-analysis-watchdog.plist ~/Library/LaunchAgents/

# 加载
launchctl load ~/Library/LaunchAgents/com.kb.video-analysis-watchdog.plist
```

## 项目结构

```
video-analysis-gemini/
├── SKILL.md                    # 核心技能说明
├── assets/                     # 模板文件
├── experiments/                # 实验记录
├── launchd/                    # 后台守护进程配置
├── references/                 # 参考文档
├── scripts/                    # 核心脚本
└── DEPLOY.md                   # 本文件
```