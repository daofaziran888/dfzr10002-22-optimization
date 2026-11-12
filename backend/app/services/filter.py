"""全局筛选器业务规则：状态流转、字段校验、多字段检索与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.services.filter_state import _match_code, filter_state_service
from app.store import store

MODULE = "filter"
REQUIRED_FIELDS = ["筛选器编号", "筛选器名称", "关联字段"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用配置": "已启用", "停用配置": "已停用"}
NEGATIVE_ACTIONS = ["停用配置"]

# 检索字段白名单：编号、关联字段、联动维度都能作为定位入口
SEARCHABLE_FIELDS = {
    "筛选器编号": "筛选器编号",
    "关联字段": "关联字段",
    "联动维度": "联动维度",
    "筛选器名称": "筛选器名称",
}


class FilterService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        field: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            key = keyword.strip().lower()
            if key:
                if field and field in SEARCHABLE_FIELDS:
                    # 指定字段检索：例如只按关联字段 region 定位
                    target = SEARCHABLE_FIELDS[field]
                    if target == "筛选器编号":
                        rows = [row for row in rows if _match_code(keyword, str(row.get(target, "")))]
                    else:
                        rows = [row for row in rows if key in str(row.get(target, "")).lower()]
                else:
                    # 不指定字段时，编号（支持省略补零）、关联字段、联动维度、名称一起匹配，
                    # FILT-002、region、地区都能回到同一条筛选器
                    rows = [
                        row
                        for row in rows
                        if _match_code(keyword, str(row.get("筛选器编号", "")))
                        or key in str(row.get("关联字段", "")).lower()
                        or key in str(row.get("联动维度", "")).lower()
                        or key in str(row.get("筛选器名称", "")).lower()
                    ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"筛选器 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于全局筛选器可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"筛选器已{action}"

    def effective_snapshot(self) -> dict[str, Any]:
        """对外暴露统一有效筛选状态，供其他服务复用同一份口径。"""
        return filter_state_service.snapshot()
