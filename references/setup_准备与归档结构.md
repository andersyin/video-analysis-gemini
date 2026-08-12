> 本文件是 `video-analysis-gemini` 的执行细则（渐进披露拆分，2026-07-30）。核心架构/五大板块/四层门禁/反例黑名单见上级 [SKILL.md](../SKILL.md)；正文与拆分前逐字一致。

## 前置准备

1. 确定归档根目录路径（如 `{{BASE}}.../对标视频分析资产/`）
2. 确认视频文件符合上方规格要求（格式/大小/时长/音频轨）

## 归档目录结构

所有分析产出自动归档为可复用资产，按以下结构组织：

```
<archive-dir>/
├── <账号名>/
│   ├── _account_meta.json                 # 账号元数据快照（每次扫描追加一条）
│   ├── _scan_log.json                     # 扫描日志（日期→视频列表→成功/失败）
│   ├── _failed_<date>.json                # 失败列表（如有）
│   ├── videos/
│   │   ├── <video-id>/
│   │   │   ├── _video_meta.json          # ffprobe 提取的硬指标元数据
│   │   │   ├── analysis_2026-07-24.json   # 每次分析日期戳，不覆盖旧文件
│   │   │   └── analysis_2026-09-15.json   # 再次扫描时新建，实现时序追踪
│   │   └── ...
│   ├── account_formula_2026-07-24.md      # 账号级公式提炼报告（日期戳）
│   └── temporal_comparison.md             # 跨时间对比报告
└── _index.json                            # 全局账号索引（你维护）
```

**关键原则**：
- **日期戳命名，不覆盖**：每次分析生成 `analysis_<date>.json`，旧数据永久保留
- **增量可复用**：已分析过的视频可跳过，新视频补分析
- **跨时间可比**：同一视频不同日期的分析文件可 diff 对比技术演进

### 过程文件生命周期与清理

执行过程会产生两类文件，**只有设计资产需要长期保留**：

| 类别 | 文件 | 体积 | 生命周期 |
|---|---|---|---|
| 设计资产（保留） | `analysis_<date>.json`、`_grounding_payload.json`、`_video_meta.json`、`_state.json`、`_contact_sheet.jpg`、`_qa_result*.json`、`_pro_review_result*.json`、`_segments.json` | KB 级 | 永久（时序追踪 + 审计留痕） |
| 过程文件（可清） | `_sense.mp4`、`_sense_audio.m4a`、`_pro_review_packet.json`、过期 Whisper 原始 `<片名>.json`（v1.2 前的残留，内容已并入 payload） | 2~15MB/条 | `PASS_DELIVERED` 后使命完成，可随时由 preprocessor 重新生成 |

**清理命令**（只清已交付视频，在途分析不受影响；默认 dry-run）：

```bash
# 预览可释放空间
python3 scripts/scan_helper.py --cleanup-sense \
  --archive-dir /path/to/archive --account "AccountD"

# 确认后移至隔离区（推荐，可逆）
python3 scripts/scan_helper.py --cleanup-sense --apply \
  --quarantine-dir <archive-dir>/_process_archive \
  --archive-dir /path/to/archive --account "AccountD"

# 或直接删除（不可逆，确认无用后再用）
python3 scripts/scan_helper.py --cleanup-sense --apply \
  --archive-dir /path/to/archive --account "AccountD"
```

> **隔离区约定（2026-07-26 新增）**：指定 `--quarantine-dir` 后 `--apply` 改为**移动而非删除**，文件归档到 `<quarantine-dir>/<清理日期>/<账号>/<video-id>/`。统一隔离区为 `<archive-dir>/_process_archive/`——过期文件不出归档根目录，需要回溯时按日期+账号+视频三级路径找回；确认无用后可整体删除某个日期目录。
> Whisper 原始输出 `<片名>.json` 自 v1.2 起由 preprocessor 解析后**自动删除**（内容已并入 payload）；v1.2 前的残留由清理命令一并收进隔离区。脚本目录 `__pycache__/` 可随手删，无影响。
> **量級参考**：100 条大视频的感知轨约 0.5~1.5GB。**批次收尾时由「第 8 步」自动执行清理，无需手动**；此处命令仅供手动补清旧归档使用。


