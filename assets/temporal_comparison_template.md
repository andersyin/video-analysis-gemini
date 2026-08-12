# {{account}} 时序追踪对比报告

<!--
  本模板由 Agent 填充，当同一账号经过多次扫描（≥2次）后产出。
  存入 <archive-dir>/<account>/temporal_comparison.md
  数据来源：同一 video-id 的多个 analysis_<date>.json + _account_meta.json snapshots
-->

> 对比周期：{{date_1}} → {{date_2}}
> 间隔天数：{{days_between}}
> 数据来源：{{video_count}} 条视频的 {{scan_count}} 次扫描

---

## 一、账号整体变化

| 指标 | {{date_1}} | {{date_2}} | 变化 |
|---|---|---|---|
| 视频总数 | {{old_count}} | {{new_count}} | {{delta}} |
| 粉丝量 | {{old_followers}} | {{new_followers}} | {{delta}} |
| 扫描视频数 | {{old_scanned}} | {{new_scanned}} | {{delta}} |
| 新增视频 | — | {{new_videos}} | |

---

## 二、单视频技术参数变化（同 video-id 跨日期 diff）

对在两次扫描中都出现的视频，对比关键参数变化：

| 视频ID | 参数 | {{date_1}} | {{date_2}} | 变化 | 备注 |
|---|---|---|---|---|---|
| {{video_id}} | 机位高度 | {{old}} | {{new}} | — | |
| | 平均镜长 | {{old}} | {{new}} | — | |
| | 画外音占比 | {{old}} | {{new}} | — | |
| | AI技术使用 | {{old}} | {{new}} | — | |

> 注：同一视频不会改变技术参数（已发布视频不变），此表主要用于验证分析一致性。

---

## 三、新增视频技术分析

{{date_1}} 之后新增的视频使用了哪些技术：

| 新增视频ID | 发布时间 | 机位 | 镜均 | 切频 | 新技术特征 | 与既有公式的偏差 |
|---|---|---|---|---|---|---|
| | | | | | | |

### 新技术趋势

{{新增视频是否引入了新的技术手法？如新的 AI 工具、新的机位高度、新的剪辑节奏？}}

---

## 四、公式漂移检测

| 维度 | {{date_1}} 公式 | {{date_2}} 公式 | 是否漂移 |
|---|---|---|---|
| 公式名称 | {{old_name}} | {{new_name}} | ✓/✗ |
| 机位区间 | {{old_range}} | {{new_range}} | |
| 切频区间 | {{old_range}} | {{new_range}} | |
| 声画比例 | {{old_range}} | {{new_range}} | |
| 叙事模板 | {{old}} | {{new}} | |

### 漂移分析

{{账号内容公式是否在变化？变化方向是技术升级（如镜长缩短）还是内容方向漂移（如从实拍转向AI生成）？}}

---

## 五、粉丝增长与技术变化关联

| 时间段 | 粉丝增量 | 关键技术变化 | 关联推断 |
|---|---|---|---|
| {{period}} | {{delta}} | {{tech_change}} | {{causal_inference}} |

### 关联结论

{{技术变化是否对应了粉丝增长？哪些技术改进带来的增长效果最显著？}}

---

## 六、下次追踪建议

- 建议追踪间隔：{{suggested_interval}}
- 重点关注的视频：{{videos_to_watch}}
- 重点关注的指标：{{metrics_to_watch}}
- 预期可能变化的方向：{{expected_direction}}

---

*数据来源：_account_meta.json · _scan_log.json · videos/*/analysis_*.json*
