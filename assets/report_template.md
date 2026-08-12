# 逐条视频拆解报告

<!--
  本模板由 Agent 填充。{{...}} 替换为实际内容，{{#each ...}} 遍历列表逐条展开。
  感知数据来源于归档目录中 analysis_<date>.json。
  每条视频一个文件，存入 <archive-dir>/<account>/videos/<video-id>/report_<date>.md
  原则：微观可查到任意秒数的任意元素，宏观可看到整体曲线与公式。
  注意：Gemini 只输出量化感知数据，借鉴建议由 Agent 在第六节综合提炼。
-->

## 视频信息
- 视频ID：{{video_id}}
- 视频文件：{{video_file}}
- 时长：{{duration}}
- 播放量/点赞：{{views}} / {{likes}}
- 分析日期：{{analysis_date}}
- 分析模型：{{model}}

---

## 一、画面与镜头语言（cinematography）

### 宏观综合
- **主机位**：{{cinematography.macro.dominant_camera_height_range}} · {{cinematography.macro.dominant_composition}} · 视线对齐：{{cinematography.macro.eye_line_match}}
- **主光影/色温**：{{cinematography.macro.dominant_lighting}} · {{cinematography.macro.dominant_color_temp}}
- **剪辑统计**：{{cinematography.macro.total_shots}} 镜 · 均长 {{cinematography.macro.avg_shot_length_sec}}s
  {{#if cinematography.macro.quick_cut_segments}}· 快切：{{#each cinematography.macro.quick_cut_segments}}`{{start_sec}}s`×{{shot_count}}镜均{{avg_duration_sec}}s {{/each}}{{/if}}
  {{#if cinematography.macro.hold_frames}}· 定格：{{#each cinematography.macro.hold_frames}}`{{second}}s`{{duration_sec}}s {{/each}}{{/if}}
- **画面情绪曲线**：{{cinematography.macro.visual_emotion_curve}}

### 逐镜时间轴

| # | 起止 | 时长 | 景别 | 机位cm | 角度 | 运镜 | 构图 | 景深 | 主体% | 光影 | 色温 | 画面内容 | 转场 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
{{#each cinematography.shot_timeline}}
| {{index}} | {{start_sec}}-{{end_sec}} | {{duration_sec}} | {{shot_type}} | {{camera_height_cm}} | {{camera_angle}} | {{camera_movement}} | {{framing}} | {{dof}} | {{main_subject_ratio_pct}} | {{lighting}} | {{color_temp}} | {{visual_content}} | {{transition_to_next}} |
{{/each}}

---

## 二、AI 生成与合成技术（ai_fx）

### 宏观综合
- **角色一致性**：锚点 {{ai_fx.character_consistency.ip_anchors}} · 漂移 {{ai_fx.character_consistency.drift_observed}}（{{ai_fx.character_consistency.drift_notes}}）
- **生成管线**：{{ai_fx.generation_pipeline.video_model_guess}} · 混合：{{ai_fx.generation_pipeline.real_vs_ai_blend}}
- **面部微动**：{{ai_fx.facial_animation.tech_used}} · 口型：{{ai_fx.facial_animation.lip_sync_naturalness}} · 微动占比 {{ai_fx.facial_animation.micro_motion_ratio_pct}}%
- **道具阴影**：接触阴影 {{ai_fx.asset_shadow.contact_shadows}}（{{ai_fx.asset_shadow.shadow_realism}}）
- **AI情绪辅助曲线**：{{ai_fx.ai_emotion_curve}}

### 逐场景技术时间轴

| 起止 | 技术手法 | 推测工具 | 混合方式 | 技术细节 |
|---|---|---|---|---|
{{#each ai_fx.scene_timeline}}
| {{start_sec}}-{{end_sec}} | {{technique}} | {{tool_guess}} | {{blend_method}} | {{notes}} |
{{/each}}

### 面部微动时刻

| 秒数 | 持续 | 描述 |
|---|---|---|
{{#each ai_fx.micro_motion_moments}}
| {{second}} | {{duration_sec}} | {{description}} |
{{/each}}

### 道具清单

| 秒数 | 道具 | 类型 |
|---|---|---|
{{#each ai_fx.prop_inventory}}
| {{second}} | {{item}} | {{type}} |
{{/each}}

---

## 三、声音工程（audio）

### 宏观综合
- **声画比例**：画外音 {{audio.macro.voiceover_ratio_pct}}% · 角色台词 {{audio.macro.character_lines_ratio_pct}}%
- **反差**：{{audio.macro.tone_contrast}}
- **BGM**：{{audio.macro.bgm_genre}} · 卡点：{{audio.macro.beat_sync}}
- **声音情绪曲线**：{{audio.macro.audio_emotion_curve}}

### 逐句画外音转录

| # | 起止 | 原文 | 说话者 | 语气 | 语速 |
|---|---|---|---|---|---|
{{#each audio.voiceover_transcript}}
| {{index}} | {{start_sec}}-{{end_sec}} | {{text}} | {{speaker}} | {{tone}} | {{pace}} |
{{/each}}

### 逐个音效时间轴（SFX）

| 秒数 | 分类 | 类型 | 描述 | 对齐画面 |
|---|---|---|---|---|
{{#each audio.sfx_timeline}}
| {{second}} | {{category}} | {{type}} | {{description}} | {{sync_with_visual}} |
{{/each}}

### BGM 变化时间轴

| 秒数 | 变化类型 | 风格 | 描述 |
|---|---|---|---|
{{#each audio.bgm_timeline}}
| {{second}} | {{change_type}} | {{genre}} | {{description}} |
{{/each}}

### 停顿时刻

| 秒数 | 持续 | 效果 |
|---|---|---|
{{#each audio.silence_moments}}
| {{second}} | {{duration_sec}} | {{effect}} |
{{/each}}

---

## 四、叙事结构（narrative）

### 宏观综合
- **注意力曲线**：
  - `{{narrative.macro.attention_curve.hook_sec}}` 钩子：{{narrative.macro.attention_curve.hook_content}}
  - `{{narrative.macro.attention_curve.setup_sec}}` 铺垫：{{narrative.macro.attention_curve.setup_content}}
  - `{{narrative.macro.attention_curve.climax_sec}}` 高潮：{{narrative.macro.attention_curve.climax_content}}
  - `{{narrative.macro.attention_curve.reversal_sec}}` 反转：{{narrative.macro.attention_curve.reversal_content}}
  - `{{narrative.macro.attention_curve.ending_sec}}` 收束：{{narrative.macro.attention_curve.ending_content}}
- **叙事模板**：{{narrative.macro.narrative_template}}
- **信息差**：{{narrative.macro.information_asymmetry.dramatic_irony}}
- **整体结构**：{{narrative.macro.story_structure}}

### 逐拍情绪时间轴

| 起止 | 情绪 | 强度(1-10) | 触发因素 |
|---|---|---|---|
{{#each narrative.emotional_timeline}}
| {{start_sec}}-{{end_sec}} | {{emotion}} | {{intensity_1to10}} | {{trigger}} |
{{/each}}

### 故事节拍

| 起止 | 节拍类型 | 描述 |
|---|---|---|
{{#each narrative.story_beats}}
| {{start_sec}}-{{end_sec}} | {{beat_type}} | {{description}} |
{{/each}}

### 完整文案

> {{narrative.script_full_text}}

### 全部金句

| 秒数 | 金句原文 | 双关 | 传播度 |
|---|---|---|---|
{{#each narrative.all_quotes}}
| {{second}} | {{text}} | {{#if pun}}✓{{/if}} | {{spreadability}} |
{{/each}}

---

## 五、制作 SOP（sop）

### 宏观综合
- **复杂度**：{{sop.production_complexity.complexity_rating}} · 耗时：{{sop.production_complexity.estimated_time}} · 软件链：{{sop.production_complexity.software_chain}}
- **可复用**：{{#each sop.asset_reusability.reusable_modules}}{{name}}({{#if reuse_observed}}✓{{else}}✗{{/if}}) {{/each}}
- **商业植入**：{{sop.monetization.product_placement}} · 软性度：{{sop.monetization.softness}}

### 制作复杂度拆解

| 阶段 | 工具 | 耗时 | 难度 |
|---|---|---|---|
{{#each sop.complexity_breakdown}}
| {{phase}} | {{tool}} | {{effort}} | {{difficulty}} |
{{/each}}

### 固定元素清单

| 元素 | 描述 |
|---|---|
{{#each sop.fixed_elements}}
| {{element}} | {{description}} |
{{/each}}

### 品牌元素

| 秒数 | 元素 | 融入方式 |
|---|---|---|
{{#each sop.brand_elements}}
| {{second}} | {{element}} | {{integration}} |
{{/each}}

---

## 六、综合借鉴点（Agent 提炼 · 非 Gemini 输出）

{{基于五大板块的量化感知数据（shot_timeline / scene_timeline / sfx_timeline / emotional_timeline / complexity_breakdown 等），由 Agent 综合提炼本条视频最值得用户IP借鉴的 1-3 个技术点。每条必须包含：技术名称、量化参数值、执行方法、预期效果、实现难度（易/中/难）}}

---

## 七、跨板块情绪递进综合（Agent 综合）

{{综合 cinematography.macro.visual_emotion_curve + audio.macro.audio_emotion_curve + ai_fx.ai_emotion_curve + narrative.emotional_timeline，画出完整的情绪递进曲线，标注各情绪高点的秒数位置和触发因素}}

---

*原始感知数据：analysis_{{analysis_date}}.json*
