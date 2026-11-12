"""全局筛选器运行态：全系统唯一一份筛选状态，图表、看板、导出都从这里读数。

设计要点
--------
1. 每个筛选器同时保存「系统默认值」和「用户当前选择」，有效当前值 = 用户选择优先，
   用户清空后回落到系统默认值，而不是上一次临时选择。
2. 可选值范围、关联字段标准、联动条件构成默认值规则；不满足规则的默认值不允许保存，
   校验依据通过 validate_default 暴露给接口，展示在筛选器配置旁。
3. 每次选择都带单调递增的版本号；并发切换时旧版本响应无法覆盖新版本，
   只有最后一次选择会生效。
4. 默认值来源切换（地区主数据 -> 自定义清单）后，旧默认值若在新来源中失效，
   系统默认值置空并给出来源变更提示，失效值不会悄悄恢复。
"""
from __future__ import annotations

import re
import threading
from copy import deepcopy
from typing import Any

# 可选值来源的标准字典键，来源名称同时用于前端展示与来源变更判定
SOURCE_MASTER = "地区主数据"
SOURCE_CUSTOM = "自定义清单"

# 默认值规则的三条判定依据，接口原样返回，前端直接渲染在配置旁
RULE_RANGE = "默认值必须落在当前可选值来源提供的可选值范围内"
RULE_FIELD = "关联字段必须符合字段标准（小写字母开头，仅含字母、数字、下划线）"
RULE_LINKAGE = "联动条件必须明确绑定一个联动维度，不允许为空"


def _code_tokens(text: str) -> str:
    """把编号压成「前缀+数字」形式，FILT-002 与 FILT-0002 归一为 filt-2。

    用户检索时常省略编号里的补零，归一后两种写法能命中同一条筛选器。
    """
    match = re.match(r"^([A-Za-z]+)-0*(\d+)$", text.strip())
    if match:
        return f"{match.group(1).lower()}-{int(match.group(2))}"
    return text.strip().lower()


def _match_code(keyword: str, code: str) -> bool:
    key = keyword.strip().lower()
    if key in code.lower():
        return True
    return _code_tokens(keyword) == _code_tokens(code)


def _seed_filters() -> list[dict[str, Any]]:
    """筛选器定义：编号、关联字段、联动维度、可选值与默认值来源都在这里登记。"""
    return [
        {
            "id": 1,
            "筛选器编号": "FILT-0001",
            "筛选器名称": "销售渠道筛选器",
            "关联字段": "channel",
            "筛选类型": "单选",
            "联动维度": "渠道",
            "是否启用": "是",
            "可选值来源": SOURCE_MASTER,
            "可选值": ["线上直营", "线下经销", "代理商"],
            "系统默认值": "线上直营",
        },
        {
            "id": 2,
            "筛选器编号": "FILT-0002",
            "筛选器名称": "地区筛选器",
            "关联字段": "region",
            "筛选类型": "单选",
            "联动维度": "地区",
            "是否启用": "是",
            "可选值来源": SOURCE_MASTER,
            "可选值": ["华东", "华南", "华北", "西南"],
            "系统默认值": "华东",
        },
        {
            "id": 3,
            "筛选器编号": "FILT-0003",
            "筛选器名称": "客户等级筛选器",
            "关联字段": "customer_level",
            "筛选类型": "多选",
            "联动维度": "客户分层",
            "是否启用": "是",
            "可选值来源": SOURCE_MASTER,
            "可选值": ["战略客户", "重点客户", "普通客户"],
            "系统默认值": "重点客户",
        },
    ]


class FilterStateService:
    """内存态筛选状态仓库。线程锁保证并发切换时版本号与落库结果一致。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._definitions: dict[int, dict[str, Any]] = {
            item["id"]: deepcopy(item) for item in _seed_filters()
        }
        # 用户当前选择：None 表示用户已清空，有效当前值回落到系统默认值
        self._user_selections: dict[int, str | None] = {}
        # 每个筛选器的单调版本号，任何一次有效写入都会 +1
        self._versions: dict[int, int] = {fid: 0 for fid in self._definitions}
        # 来源变更等提示，随有效状态一起返回，直到下一次写入
        self._notices: dict[int, str] = {}

    def reset(self) -> None:
        """恢复初始种子状态，主要供测试用例之间隔离使用。"""
        with self._lock:
            seed = _seed_filters()
            self._definitions = {item["id"]: deepcopy(item) for item in seed}
            self._user_selections = {}
            self._versions = {fid: 0 for fid in self._definitions}
            self._notices = {}

    # ------------------------------------------------------------------ #
    # 读取
    # ------------------------------------------------------------------ #
    def list_definitions(self, keyword: str | None = None) -> list[dict[str, Any]]:
        """返回全部筛选器定义；keyword 同时匹配编号、关联字段、联动维度与名称。

        例：FILT-002、region、地区 三个关键字都能定位到 FILT-0002 这同一条筛选器。
        """
        with self._lock:
            rows = [deepcopy(item) for item in self._definitions.values()]
        if keyword:
            key = keyword.strip().lower()
            if key:
                rows = [
                    row
                    for row in rows
                    if _match_code(keyword, str(row.get("筛选器编号", "")))
                    or key in str(row.get("关联字段", "")).lower()
                    or key in str(row.get("联动维度", "")).lower()
                    or key in str(row.get("筛选器名称", "")).lower()
                ]
        return rows

    def get_definition(self, filter_id: int) -> dict[str, Any] | None:
        with self._lock:
            return deepcopy(self._definitions.get(filter_id))

    def find_by_code(self, code: str) -> dict[str, Any] | None:
        """按筛选器编号定位，例如 FILT-0002。"""
        with self._lock:
            for item in self._definitions.values():
                if item.get("筛选器编号") == code:
                    return deepcopy(item)
        return None

    def effective_value(self, definition: dict[str, Any]) -> str | None:
        """有效当前值：用户当前选择优先；用户清空（None）时回落到系统默认值。"""
        fid = int(definition["id"])
        if fid in self._user_selections:
            return self._user_selections[fid]
        return definition.get("系统默认值")

    def snapshot(self) -> dict[str, Any]:
        """全量有效状态快照，供图表配置、看板、导出等下游模块统一读取。"""
        with self._lock:
            items: list[dict[str, Any]] = []
            for definition in self._definitions.values():
                fid = int(definition["id"])
                items.append(self._serialize(definition))
            return {
                "items": items,
                "version": max(self._versions.values(), default=0),
                "notice": self._latest_notice(),
            }

    def get_state(self, filter_id: int) -> dict[str, Any] | None:
        with self._lock:
            definition = self._definitions.get(filter_id)
            if definition is None:
                return None
            return self._serialize(definition)

    # ------------------------------------------------------------------ #
    # 写入：选择 / 清空 / 来源切换 / 默认值保存
    # ------------------------------------------------------------------ #
    def select(
        self, filter_id: int, value: str | None, client_version: int | None = None
    ) -> tuple[dict[str, Any] | None, str | None]:
        """记录一次用户选择。

        并发切换保护：调用方带上它看到的 client_version（期望基准版本）。
        若期间已有更新的选择落库（当前版本 > client_version），本次写入被拒绝，
        旧响应不能覆盖新选择；返回当前最新状态与冲突说明。
        value=None 表示用户清空，有效当前值回落到系统默认值。
        """
        with self._lock:
            definition = self._definitions.get(filter_id)
            if definition is None:
                return None, f"筛选器 {filter_id} 不存在或已归档"

            current_version = self._versions[filter_id]
            if client_version is not None and client_version < current_version:
                return self._serialize(definition), (
                    f"选择已被更新的操作覆盖（当前版本 {current_version}），本次切换未生效"
                )

            if value is not None and value not in definition["可选值"]:
                return self._serialize(definition), (
                    f"值「{value}」不在筛选器 {definition['筛选器编号']} 的可选值范围内，"
                    "请重新选择后再提交"
                )

            self._user_selections[filter_id] = value
            self._versions[filter_id] = current_version + 1
            self._notices.pop(filter_id, None)
            return self._serialize(definition), None

    def reset_to_default(self, filter_id: int) -> tuple[dict[str, Any] | None, str | None]:
        """清空用户选择：显式回到系统默认值，而不是上一次临时选择。"""
        with self._lock:
            definition = self._definitions.get(filter_id)
            if definition is None:
                return None, f"筛选器 {filter_id} 不存在或已归档"
            self._user_selections.pop(filter_id, None)
            self._versions[filter_id] += 1
            # 注意：不清空 _notices。若默认值因来源变更失效，提示要保留到用户重新选择，
            # 不能因为一次清空操作就把失效原因藏起来。
            return self._serialize(definition), None

    def change_source(
        self, filter_id: int, source: str, options: list[str]
    ) -> tuple[dict[str, Any] | None, str | None]:
        """切换可选值来源（地区主数据 -> 自定义清单）。

        旧系统默认值若不在新来源的可选值范围内，则判定失效：系统默认值置空、
        用户临时选择一并作废，并登记来源变更提示。失效默认值不会被悄悄带回。
        """
        with self._lock:
            definition = self._definitions.get(filter_id)
            if definition is None:
                return None, f"筛选器 {filter_id} 不存在或已归档"
            if not options:
                return self._serialize(definition), "新来源至少要提供一个可选值，来源未切换"

            old_source = definition["可选值来源"]
            old_default = definition.get("系统默认值")
            definition["可选值来源"] = source
            definition["可选值"] = list(options)

            notice: str | None = None
            if old_default is not None and old_default not in options:
                definition["系统默认值"] = None
                # 用户选择基于旧来源，同样作废，避免失效值通过用户选择通道复活
                self._user_selections.pop(filter_id, None)
                notice = (
                    f"默认值来源已由「{old_source}」切换为「{source}」，"
                    f"原默认值「{old_default}」不在新来源可选值范围内，已失效并清空，"
                    "请重新选择当前有效值"
                )
                self._notices[filter_id] = notice

            self._versions[filter_id] += 1
            return self._serialize(definition), notice

    def validate_default(self, definition: dict[str, Any]) -> list[dict[str, str]]:
        """默认值规则校验，返回每条规则的通过情况与判定依据。"""
        results: list[dict[str, str]] = []
        default = definition.get("系统默认值")
        options = definition.get("可选值") or []

        in_range = default is not None and default in options
        results.append({
            "rule": "可选值范围",
            "passed": "true" if in_range else "false",
            "basis": f"{RULE_RANGE}；当前可选值：{('、'.join(options)) or '（空）'}",
        })

        field = str(definition.get("关联字段") or "")
        field_ok = bool(field) and field[0].isalpha() and field.replace("_", "").isalnum()
        results.append({
            "rule": "关联字段标准",
            "passed": "true" if field_ok else "false",
            "basis": f"{RULE_FIELD}；当前关联字段：{field or '（空）'}",
        })

        linkage = str(definition.get("联动维度") or "").strip()
        results.append({
            "rule": "联动条件",
            "passed": "true" if linkage else "false",
            "basis": f"{RULE_LINKAGE}；当前联动维度：{linkage or '（空）'}",
        })
        return results

    def save_default(
        self, filter_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
        """保存筛选器配置与默认值。任一规则不通过则整体拒绝，判定依据原样返回。"""
        with self._lock:
            definition = self._definitions.get(filter_id)
            if definition is None:
                return [], []  # 调用方按空结果转 404

            candidate = deepcopy(definition)
            for field in ("筛选器名称", "关联字段", "筛选类型", "联动维度", "是否启用"):
                if field in values and values[field] is not None:
                    candidate[field] = str(values[field]).strip()
            if "系统默认值" in values:
                raw_default = values["系统默认值"]
                candidate["系统默认值"] = None if raw_default in (None, "") else str(raw_default)
            if "可选值" in values and isinstance(values["可选值"], list):
                candidate["可选值"] = [str(item) for item in values["可选值"]]

            checks = self.validate_default(candidate)
            if any(item["passed"] != "true" for item in checks):
                return None, checks

            # 规则全部通过才落库；新默认值若与用户选择不同，以用户当前选择为准，
            # 只更新系统默认值本身，不覆盖用户选择。
            definition.update(candidate)
            self._versions[filter_id] += 1
            return self._serialize(definition), checks

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #
    def _serialize(self, definition: dict[str, Any]) -> dict[str, Any]:
        fid = int(definition["id"])
        user_value = self._user_selections.get(fid, "__unset__")
        is_customized = user_value != "__unset__"
        current_value = (
            self._user_selections[fid] if is_customized else definition.get("系统默认值")
        )
        return {
            "id": fid,
            "筛选器编号": definition["筛选器编号"],
            "筛选器名称": definition["筛选器名称"],
            "关联字段": definition["关联字段"],
            "筛选类型": definition["筛选类型"],
            "联动维度": definition["联动维度"],
            "是否启用": definition["是否启用"],
            "可选值来源": definition["可选值来源"],
            "可选值": deepcopy(definition["可选值"]),
            "系统默认值": definition.get("系统默认值"),
            "用户选择": self._user_selections.get(fid),
            "用户已自定义": is_customized,
            "当前有效值": current_value,
            "version": self._versions[fid],
            "notice": self._notices.get(fid),
            "规则校验": self.validate_default(definition),
        }

    def _latest_notice(self) -> str | None:
        notices = [text for text in self._notices.values() if text]
        return notices[-1] if notices else None


# 进程内单例：下游模块全部通过这一个实例读取有效筛选状态
filter_state_service = FilterStateService()
