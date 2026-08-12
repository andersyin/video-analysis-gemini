#!/usr/bin/env python3
"""standalone_watchdog.py — 会话外独立看门狗（P0-4，SentientOS deadman 借鉴，2026-07-28）

设计原则（来源：SentientOS Overnight Scheduler deadman timer 教训）：
  「App 内的 timer 会跟 App 一起死」——session_guard.py 的 preflight/watchdog 逻辑
  只在 AI 会话内被调用，会话死了守护也死。本脚本把守护逻辑挂到会话之外：
  由 launchd 定时拉起（默认 30 分钟一轮），零 LLM、纯确定性判断。

判活模型（心跳 = 文件 mtime，被守护方无需改造）：
  - 会话在途中间态（FLASH_EXTRACTED/PRO_AUDITING/PROBE_REPAIRING）的视频目录，
    取目录内全部文件的最新 mtime 作为心跳（PREPROCESSED 是排队态，不参与判活）；
  - 心跳超过 --stale-min（默认 90 分钟，覆盖 L2 最长 45 分钟 view_file 的 2 倍）
    → 判定 STALLED（会话死亡签名），告警；
  - 遗孤（analysis 齐 5 板块但未 finalize-l2，复用 session_guard preflight 的 P0_遗孤判定）
    → 默认告警；--auto-finalize 时直接补跑 finalize-l2（skill 纪律：禁止重进 L2；
    finalize-l2 自带门禁校验，不达标会拒收，故自动补跑安全）。

watchdog 自身心跳（Liveness is the ONLY honest status）：
  每轮把状态 JSON 写入 --status-file（含 last_run_at）。健康检查看该文件 mtime，
  不看 plist 是否存在——文件检查全绿而 daemon 已死是 SentientOS field-found 教训。

用法：
  python3 standalone_watchdog.py \
    --archive-dir "{{MEDIA_DIR}}/analysis_archive" \
    [--stale-min 90] [--auto-finalize] [--status-file <path>] [--log-file <path>]

  launchd 安装/验证：见同目录 launchd/README_watchdog_install.md

退出码：0=全部健康；1=发现 STALLED/遗孤/篡改（详情见状态文件）；2=脚本自身错误
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SESSION_GUARD = SCRIPT_DIR / "session_guard.py"

# 心跳判活只盯"会话理应正在干活"的中间态。
# PREPROCESSED 是排队态（预处理完等未来 L2 会话），不算在途——
# 真实负载压测（2026-07-28，6 账号 95+ 视频）显示把它算在途会误报 70+ 条积压为 STALLED。
# PREPROCESSED 的异常由遗孤检测覆盖（5 板块齐但未 finalize-l2）。
STALL_WATCH_STATES = {"FLASH_EXTRACTED", "PRO_AUDITING", "PROBE_REPAIRING"}

# KB 持久心跳目录（对齐 raw/系统/备份心跳/ 双写模式）
DEFAULT_STATUS_DIR = Path("{{KB_BASE}}/raw/系统/watchdog心跳")
LOG_KEEP_LINES = 500  # 日志轮转：只保留最近 N 行，防熵


def newest_mtime(video_dir: Path):
    """视频目录内全部文件的最新 mtime（递归一层足够：产物都在顶层或 logs/）。"""
    latest = 0.0
    for p in video_dir.rglob("*"):
        try:
            if p.is_file():
                latest = max(latest, p.stat().st_mtime)
        except OSError:
            continue
    return latest


def run_preflight(archive_dir: str, account: str):
    """复用 session_guard preflight 的判定（P0_遗孤/篡改/卡住），解析其 stdout JSON。"""
    try:
        proc = subprocess.run(
            [sys.executable, str(SESSION_GUARD), "preflight",
             "--archive-dir", archive_dir, "--account", account],
            capture_output=True, text=True, timeout=120,
        )
        return json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
        return {"error": f"{type(e).__name__}: {e}"}


def auto_finalize(archive_dir: str, account: str, video_id: str, date: str):
    """遗孤补跑 finalize-l2（幂等：门禁不过会拒收，退出码非 0）。"""
    proc = subprocess.run(
        [sys.executable, str(SESSION_GUARD), "finalize-l2",
         "--archive-dir", archive_dir, "--account", account,
         "--video-id", video_id, "--date", date],
        capture_output=True, text=True, timeout=300,
    )
    return proc.returncode, (proc.stdout + proc.stderr)[-500:]


def discover_accounts(root: Path):
    """账号目录 = 含 videos/ 子目录的一级目录（排除 _ 前缀过程目录）。"""
    return sorted(
        d.name for d in root.iterdir()
        if d.is_dir() and not d.name.startswith("_") and (d / "videos").is_dir()
    )


def rotate_log(log_path: Path):
    if not log_path.exists():
        return
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) > LOG_KEEP_LINES:
        log_path.write_text("\n".join(lines[-LOG_KEEP_LINES:]) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="video-analysis 独立看门狗（launchd 拉起，零 LLM）")
    ap.add_argument("--archive-dir", required=True)
    ap.add_argument("--stale-min", type=int, default=90)
    ap.add_argument("--auto-finalize", action="store_true",
                    help="P0 遗孤直接补跑 finalize-l2（门禁自校验，安全）")
    ap.add_argument("--status-file", default=str(DEFAULT_STATUS_DIR / "video-analysis-watchdog.json"))
    ap.add_argument("--log-file", default=str(DEFAULT_STATUS_DIR / "video-analysis-watchdog.log"))
    args = ap.parse_args()

    now = datetime.now()
    root = Path(args.archive_dir)
    status = {
        "watchdog": "video-analysis-standalone",
        "last_run_at": now.isoformat(),
        "archive_dir": str(root),
        "stale_threshold_min": args.stale_min,
        "auto_finalize": args.auto_finalize,
        "accounts": {},
        "alerts": [],
        "actions_taken": [],
    }
    exit_code = 0

    if not root.is_dir():
        status["error"] = f"归档根目录不可达: {root}（外置卷未挂载？）"
        exit_code = 2
    else:
        for account in discover_accounts(root):
            pf = run_preflight(str(root), account)
            if "error" in pf:
                status["accounts"][account] = {"preflight_error": pf["error"]}
                exit_code = max(exit_code, 2)
                continue
            summary = pf.get("summary", {})
            acct_report = {"summary": summary, "stalled": [], "orphans": []}

            for v in pf.get("videos", []):
                vid, state = v["video_id"], v["current_state"]
                vdir = root / account / "videos" / vid

                # 心跳判活：会话在途中间态 + 文件 mtime 超阈值 = 会话死亡签名
                if state in STALL_WATCH_STATES and vdir.is_dir():
                    hb = newest_mtime(vdir)
                    idle_min = (now.timestamp() - hb) / 60 if hb else None
                    if idle_min is not None and idle_min > args.stale_min:
                        acct_report["stalled"].append(
                            {"video_id": vid, "state": state, "idle_min": round(idle_min)})
                        status["alerts"].append(
                            f"STALLED {account}/{vid}: 状态 {state}，心跳静默 {round(idle_min)} 分钟"
                            f"（阈值 {args.stale_min}）→ 会话疑似死亡，按 preflight 建议恢复")
                        exit_code = max(exit_code, 1)

                # 遗孤：preflight 判定 P0_遗孤（5 板块齐但未 finalize-l2）
                acts = v.get("next_actions", [])
                if acts and acts[0]["priority"] == "P0_遗孤":
                    acct_report["orphans"].append(vid)
                    exit_code = max(exit_code, 1)
                    if args.auto_finalize:
                        # 从 analysis 文件名取 date（analysis_YYYY-MM-DD.json）
                        try:
                            afile = next((root / account / "videos" / vid).glob("analysis_*.json"))
                            date = afile.stem.replace("analysis_", "")
                            rc, tail = auto_finalize(str(root), account, vid, date)
                            status["actions_taken"].append(
                                {"video_id": f"{account}/{vid}", "action": "finalize-l2",
                                 "rc": rc, "tail": tail})
                        except StopIteration:
                            status["alerts"].append(f"ORPHAN {account}/{vid}: 未找到 analysis_*.json，跳过自动补跑")
                    else:
                        status["alerts"].append(
                            f"ORPHAN {account}/{vid}: 5 板块齐但未 finalize-l2 → 补跑 finalize-l2（禁止重进 L2）")

                if v.get("tamper_severity") in ("high", "critical"):
                    status["alerts"].append(f"TAMPER {account}/{vid}: {v['tamper_issues']}")
                    exit_code = max(exit_code, 1)

            status["accounts"][account] = acct_report

    status["exit_code"] = exit_code
    # watchdog 自身心跳落盘（liveness 探针读这里的 mtime，不读 plist）
    sf = Path(args.status_file)
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    lf = Path(args.log_file)
    lf.parent.mkdir(parents=True, exist_ok=True)
    with lf.open("a", encoding="utf-8") as f:
        f.write(f"{now.isoformat()} exit={exit_code} alerts={len(status['alerts'])} "
                f"actions={len(status['actions_taken'])}\n")
    rotate_log(lf)

    print(json.dumps({"exit_code": exit_code, "alerts": status["alerts"],
                      "actions_taken": status["actions_taken"]}, ensure_ascii=False))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
