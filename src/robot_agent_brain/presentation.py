def format_report(report):
    lines = [f"Provider: {report.provider}（仅规划，不执行）", f"分类：{report.turn_kind or '未解析'} / {report.run_status}", report.reply]
    for key, path in report.artifacts.items():
        lines.append(f"{key}: {path}")
    if report.error:
        lines.append(f"错误：{report.error.code}")
    return "\n".join(lines)


def exit_code(report):
    if report.turn_status == "unsupported_task":
        return 3
    return {"success":0, "blocked":2, "failed":4}[report.run_status]
