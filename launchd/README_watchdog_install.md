# standalone_watchdog 安装与验收（P0-4，2026-07-28）

> 设计原则：deadman 守护逻辑活在被守护会话之外（SentientOS Overnight Scheduler 教训）。

## 安装（launchd 常驻，30 分钟一轮）

Set `MEDIA_DIR` in `local.env` (copy from `local.env.example`). Do not sed-replace this repo.

```sh
bash launchd/install.sh
launchctl kickstart "gui/$(id -u)/com.video-analysis.watchdog"
```

`install.sh` writes `~/Library/LaunchAgents/com.video-analysis.watchdog.plist` with real paths and `MEDIA_DIR`. The committed plist is a template only.

## 验收标准（P0-2 心跳实测协议，禁止只查文件）

**Liveness is the ONLY honest status**——plist 存在 + `launchctl list` 有条目 ≠ 活着。
唯一验收依据是**状态文件 mtime 前进**：

```sh
# Default heartbeat (KB_BASE unset)
stat -f "%Sm" /tmp/video-analysis-watchdog.json
# If KB_BASE is set:
# stat -f "%Sm" "$KB_BASE/raw/系统/watchdog心跳/video-analysis-watchdog.json"

launchctl kickstart "gui/$(id -u)/com.video-analysis.watchdog" && sleep 30
python3 -c "import json; d=json.load(open('/tmp/video-analysis-watchdog.json')); print(d['last_run_at'], d['alerts'])"
```

故障分类（文件检查只用于分类，不用于判活）：
- **ready**：状态文件 mtime 在 StartInterval×2 内 → 健康
- **disabled**：mtime 停走 + plist 在 + `launchctl print gui/$(id -u)/com.video-analysis.watchdog` 报 not found → 后台活动开关被关 / 被 bootout，需重新 bootstrap
- **notSetUp**：plist 不在 `~/Library/LaunchAgents/` → 重走 `bash launchd/install.sh`
- **tcc-denied**（field-found 2026-07-28）：`/tmp/video-analysis-watchdog.err.log` 出现 `can't open file … Operation not permitted` → launchd 上下文的解释器无外置卷访问权（TCC 不继承终端权限，后台任务不弹授权框、静默失败）。**本机实测有效解**：不要试图给 python3 授 FDA（实测授了仍被拦）——用 `/bin/bash` + `watchdog-wrapper.sh` 包装模式（本 plist 现行方案，与 daily-work-mirror 等既有外置卷任务同款）；若 wrapper 模式也被拦，对照本机其他能访问同卷的 launchd 任务找已持权执行器
- **volume-gone**：err.log 有 python 报错 + 外置卷未挂载 → 挂卷后自愈，无需动 launchd

## 行为契约

| 检测 | 判定 | 动作 |
|---|---|---|
| STALLED | FLASH_EXTRACTED/PRO_AUDITING/PROBE_REPAIRING 态 + 目录心跳静默 > 90 min | 告警（写状态文件 alerts） |
| ORPHAN | preflight P0_遗孤（5 板块齐未 finalize-l2） | `--auto-finalize` 时补跑 finalize-l2；门禁拒收则如实记账（fail-closed 不绕过） |
| TAMPER | _state.json 高危篡改签名 | 告警 |

- 退出码：0 健康 / 1 有发现 / 2 脚本或卷故障。
- 状态与日志：`/tmp/video-analysis-watchdog.{json,log}`（或 `$KB_BASE/raw/系统/watchdog心跳/`）；日志自动轮转 500 行。
- PREPROCESSED 为排队态不参与 STALL 判活（2026-07-28 真实负载压测教训：否则 70+ 积压误报）。

## 卸载

```sh
bash launchd/uninstall.sh
```

Archives and `/tmp/video-analysis-watchdog.*` logs are kept.

## 验收记录

| 日期 | 验收项 | 结果 |
|---|---|---|
| 2026-07-28 | 真实负载压测（6 账号 95+ 视频） | ✅ 首轮暴露 PREPROCESSED 误报（70+），修正后误报 0；抓到真实遗孤 1 条（AccountC/01 猫和老鼠真猫版） |
| 2026-07-28 | auto-finalize 恢复动作 | ✅ 补跑被密度门禁拒收（SFX 0.38<0.5、14 镜 vs 134 硬切点）——fail-closed 未被绕过，遗孤为真质量缺陷需回 L2 补标，watchdog 如实记账 |
| 2026-07-28 | launchd 心跳实测 | 🔴 **心跳实测抓到真实故障**：bootstrap RC=0、`launchctl print` 有条目（文件检查全绿），但状态文件 mtime 未前进——launchd 拉起的 python3 被 TCC 拦在外置卷外（tcc-denied，见故障分类）。旧验收法（只查 plist+launchctl list）会把此状态误判为"已完成"——P0-2 升级的价值实证 |
| 2026-07-28 | tcc-denied 修复与终验 | ✅ **全闭环（19:02）**：用户授 python3 FDA 后直连**仍被拦**（field-found：FDA 给解释器二进制对 launchd 上下文不一定生效）；改用本机已验证模式——`/bin/bash` + `watchdog-wrapper.sh`（与 daily-work-mirror/patrol-weekly 等既有外置卷任务同款）→ 心跳 mtime 前进（18:15:34→19:02:07）、err.log 零新增、遗孤恢复动作正常（finalize-l2 补跑被密度门禁如实拒收）。plist 已改为 wrapper 模式并重装 |
