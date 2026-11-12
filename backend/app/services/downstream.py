"""下游模块（图表配置、数据看板、导出任务）读取全局筛选状态的统一口径。

所有下游模块只允许通过这里访问 filter_state_service，保证它们看到的
「当前有效值」完全一致；失效默认值在状态服务里已被置空，这里不会再恢复。
"""
from __future__ import annotations

from typing import Any

from app.services.filter_state import filter_state_service


def effective_filter_context() -> dict[str, Any]:
    """压缩后的有效筛选上下文，直接塞进列表/导出响应，前端无需二次拼装。"""
    snapshot = filter_state_service.snapshot()
    resolved = [
        {
            "筛选器编号": item["筛选器编号"],
            "关联字段": item["关联字段"],
            "联动维度": item["联动维度"],
            "当前有效值": item["当前有效值"],
            "系统默认值": item["系统默认值"],
            "用户已自定义": item["用户已自定义"],
            "可选值来源": item["可选值来源"],
            "notice": item["notice"],
        }
        for item in snapshot["items"]
    ]
    return {
        "filters": resolved,
        "version": snapshot["version"],
        "notice": snapshot["notice"],
    }


def annotate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """给下游清单逐行写入当前生效筛选，清单随有效筛选同步刷新。"""
    context = effective_filter_context()
    annotated: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["生效筛选"] = [
            f"{entry['关联字段']}={entry['当前有效值']}"
            for entry in context["filters"]
            if entry["当前有效值"] is not None
        ]
        item["筛选状态版本"] = context["version"]
        annotated.append(item)
    return annotated
