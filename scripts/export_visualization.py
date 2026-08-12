#!/usr/bin/env python3
"""可视化导出脚本 —— 将分析资产编译为 Obsidian Canvas 图谱 + CSV 标签表。

负责：
1. 读取归档目录下所有账号的 analysis_*.json
2. 提取每条视频的关键技术参数（总镜数、ASL、机位高度、声画比、叙事模板等）
3. 生成 Obsidian .canvas 图谱（账号节点 → 视频节点 → 参数标签）
4. 生成 CSV 标签表，可回填至 quality_tags_with_source_id.csv

用法:
  python export_visualization.py --archive-dir /path/to/archive \
    --output-dir /path/to/output
"""
import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path


def load_all_analyses(archive_dir):
    """加载归档目录下所有账号的所有分析 JSON。"""
    archive = Path(archive_dir)
    accounts = {}
    for account_dir in sorted(archive.iterdir()):
        if not account_dir.is_dir() or account_dir.name.startswith("_"):
            continue
        videos_dir = account_dir / "videos"
        if not videos_dir.is_dir():
            continue

        account_data = {
            "account": account_dir.name,
            "videos": [],
        }

        # 读取账号公式（如有）
        formula_files = sorted(account_dir.glob("account_formula_*.md"))
        if formula_files:
            account_data["formula_file"] = str(formula_files[-1])

        for video_dir in sorted(videos_dir.iterdir()):
            if not video_dir.is_dir():
                continue
            analysis_files = sorted(video_dir.glob("analysis_*.json"))
            if not analysis_files:
                continue

            # 读最新分析
            with open(analysis_files[-1], encoding="utf-8") as f:
                analysis = json.loads(f.read())

            video_id = video_dir.name
            meta = analysis.get("_meta", {})

            # 提取关键参数
            cine = analysis.get("cinematography", {})
            cine_macro = cine.get("macro", {}) if isinstance(cine, dict) else {}
            audio = analysis.get("audio", {})
            audio_macro = audio.get("macro", {}) if isinstance(audio, dict) else {}
            narr = analysis.get("narrative", {})
            narr_macro = narr.get("macro", {}) if isinstance(narr, dict) else {}
            sop = analysis.get("sop", {})
            sop_pc = sop.get("production_complexity", {}) if isinstance(sop, dict) else {}

            account_data["videos"].append({
                "video_id": video_id,
                "video_file": meta.get("video_file", ""),
                "analysis_date": meta.get("analysis_date", ""),
                "total_shots": cine_macro.get("total_shots"),
                "avg_shot_length_sec": cine_macro.get("avg_shot_length_sec"),
                "dominant_camera_height_range": cine_macro.get("dominant_camera_height_range", ""),
                "dominant_composition": cine_macro.get("dominant_composition", ""),
                "dominant_lighting": cine_macro.get("dominant_lighting", ""),
                "voiceover_ratio_pct": audio_macro.get("voiceover_ratio_pct"),
                "bgm_genre": audio_macro.get("bgm_genre", ""),
                "narrative_template": narr_macro.get("narrative_template", ""),
                "complexity_rating": sop_pc.get("complexity_rating", ""),
            })

        if account_data["videos"]:
            accounts[account_dir.name] = account_data

    return accounts


def generate_canvas(accounts, output_path):
    """生成 Obsidian .canvas 文件。"""
    nodes = []
    edges = []
    node_id = 0

    # 布局参数
    col_width = 320
    row_height = 200
    gap_x = 60
    gap_y = 40
    start_x = 0
    start_y = 0

    for col_idx, (account_name, account_data) in enumerate(accounts.items()):
        x = start_x + col_idx * (col_width + gap_x)

        # 账号节点
        account_node_id = f"node_{node_id}"
        node_id += 1
        video_count = len(account_data["videos"])
        nodes.append({
            "id": account_node_id,
            "type": "text",
            "x": x,
            "y": start_y,
            "width": col_width,
            "height": 80,
            "color": "1",
            "text": f"## 📊 {account_name}\n{video_count} 条视频",
        })

        # 视频节点
        for row_idx, video in enumerate(account_data["videos"]):
            y = start_y + 120 + row_idx * (row_height + gap_y)

            video_node_id = f"node_{node_id}"
            node_id += 1

            # 构建参数摘要
            shots = video.get("total_shots") or "?"
            asl = video.get("avg_shot_length_sec") or "?"
            cam_h = video.get("dominant_camera_height_range") or "?"
            vo = video.get("voiceover_ratio_pct") or "?"
            narr_t = video.get("narrative_template") or "?"
            complexity = video.get("complexity_rating") or "?"

            text = (
                f"**{video['video_id']}**\n\n"
                f"- 镜数: {shots} | ASL: {asl}s\n"
                f"- 机位: {cam_h}\n"
                f"- 画外音: {vo}%\n"
                f"- 叙事: {narr_t}\n"
                f"- 复杂度: {complexity}"
            )

            nodes.append({
                "id": video_node_id,
                "type": "text",
                "x": x,
                "y": y,
                "width": col_width,
                "height": row_height,
                "color": "4" if complexity == "高" else "5",
                "text": text,
            })

            # 账号 → 视频 连线
            edges.append({
                "id": f"edge_{len(edges)}",
                "fromNode": account_node_id,
                "toNode": video_node_id,
            })

    canvas = {"nodes": nodes, "edges": edges}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(canvas, f, ensure_ascii=False, indent=2)
    return output_path


def generate_csv(accounts, output_path):
    """生成 CSV 标签表，可回填至 quality_tags_with_source_id.csv。"""
    rows = []
    for account_name, account_data in accounts.items():
        for video in account_data["videos"]:
            rows.append({
                "account": account_name,
                "video_id": video["video_id"],
                "video_file": video.get("video_file", ""),
                "analysis_date": video.get("analysis_date", ""),
                "total_shots": video.get("total_shots") or "",
                "avg_shot_length_sec": video.get("avg_shot_length_sec") or "",
                "dominant_camera_height_range": video.get("dominant_camera_height_range") or "",
                "dominant_composition": video.get("dominant_composition") or "",
                "dominant_lighting": video.get("dominant_lighting") or "",
                "voiceover_ratio_pct": video.get("voiceover_ratio_pct") or "",
                "bgm_genre": video.get("bgm_genre") or "",
                "narrative_template": video.get("narrative_template") or "",
                "complexity_rating": video.get("complexity_rating") or "",
            })

    if not rows:
        return None

    fieldnames = list(rows[0].keys())
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="可视化导出（Obsidian Canvas + CSV 标签表）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--archive-dir", required=True, help="归档根目录")
    parser.add_argument("--output-dir", required=True, help="输出目录")
    args = parser.parse_args()

    accounts = load_all_analyses(args.archive_dir)
    if not accounts:
        sys.exit("错误：归档目录中未找到分析数据")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")

    # 生成 Canvas
    canvas_path = output_dir / f"video_analysis_canvas_{date_str}.canvas"
    generate_canvas(accounts, canvas_path)
    sys.stderr.write(f"✅ Canvas 已生成: {canvas_path}\n")

    # 生成 CSV
    csv_path = output_dir / f"video_analysis_tags_{date_str}.csv"
    generate_csv(accounts, csv_path)
    sys.stderr.write(f"✅ CSV 标签表已生成: {csv_path}\n")

    # 输出 JSON 摘要
    summary = {
        "date": date_str,
        "accounts": len(accounts),
        "total_videos": sum(len(a["videos"]) for a in accounts.values()),
        "canvas_file": str(canvas_path),
        "csv_file": str(csv_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
