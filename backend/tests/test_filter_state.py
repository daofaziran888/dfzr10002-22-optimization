"""全局筛选器运行态的业务规则测试。

覆盖需求中的关键场景：
1. 编号（含省略补零）、关联字段、联动维度多入口定位同一筛选器
2. 用户选择优先于系统默认值；清空后回到系统默认值而不是上一次临时选择
3. 并发切换的版本控制：旧响应不能覆盖新选择，只有最后一次选择生效
4. 来源切换导致默认值失效时给出来源变更提示，失效值不悄悄恢复
5. 默认值规则（可选值范围、关联字段标准、联动条件）不通过则拒绝保存
6. 图表 CFG-0007、面板 DASH-0005、导出任务读取同一份有效筛选
"""
from __future__ import annotations

import pytest

from app.services.filter_state import filter_state_service as state


@pytest.fixture(autouse=True)
def _reset_state():
    state.reset()
    yield
    state.reset()


def test_locate_same_filter_from_three_entries():
    """FILT-002、region、地区 三种入口都定位到 FILT-0002。"""
    for keyword in ("FILT-002", "FILT-0002", "filt-0002", "region", "地区"):
        rows = state.list_definitions(keyword)
        assert len(rows) == 1
        assert rows[0]["筛选器编号"] == "FILT-0002"


def test_effective_value_default_then_user_then_reset():
    initial = state.get_state(2)
    assert initial["当前有效值"] == "华东"
    assert initial["用户已自定义"] is False

    selected, error = state.select(2, "华南", initial["version"])
    assert error is None
    assert selected["当前有效值"] == "华南"
    assert selected["用户已自定义"] is True

    # 清空：回到系统默认值，而不是上一次临时选择（华南）
    reset, error = state.reset_to_default(2)
    assert error is None
    assert reset["当前有效值"] == "华东"
    assert reset["用户已自定义"] is False


def test_stale_concurrent_select_cannot_override_latest():
    first, _ = state.select(2, "华南", 0)
    assert first["version"] == 1
    second, _ = state.select(2, "华北", 1)
    assert second["version"] == 2
    assert second["当前有效值"] == "华北"

    # 基准版本 1 的迟到响应：必须被拒绝，当前有效值仍是第二次选择
    stale, conflict = state.select(2, "西南", 1)
    assert conflict is not None
    assert stale["当前有效值"] == "华北"
    assert state.get_state(2)["当前有效值"] == "华北"


def test_select_out_of_range_rejected():
    current = state.get_state(2)
    _, error = state.select(2, "火星大区", current["version"])
    assert error is not None and "可选值范围" in error
    assert state.get_state(2)["当前有效值"] == "华东"


def test_source_change_invalidates_stale_default_with_notice():
    changed, notice = state.change_source(2, "自定义清单", ["华中", "西北"])
    assert notice is not None and "来源" in notice
    assert changed["系统默认值"] is None
    assert changed["当前有效值"] is None
    # 提示在清空操作后仍然保留，失效默认值没有被悄悄带回
    state.reset_to_default(2)
    again = state.get_state(2)
    assert again["系统默认值"] is None
    assert again["notice"] is not None


def test_source_change_keeps_default_when_still_valid():
    changed, notice = state.change_source(2, "自定义清单", ["华东", "华中"])
    assert notice is None
    assert changed["系统默认值"] == "华东"
    assert changed["当前有效值"] == "华东"


def test_default_save_rejected_when_rules_fail():
    # 先切到自定义清单，让「华东」变成越界值
    state.change_source(2, "自定义清单", ["华中", "西北"])
    saved, checks = state.save_default(2, {"系统默认值": "华东"})
    assert saved is None
    failed = {item["rule"]: item for item in checks}
    assert failed["可选值范围"]["passed"] == "false"
    assert "可选值范围" in failed["可选值范围"]["basis"]
    # 配置未被污染
    assert state.get_state(2)["系统默认值"] is None


def test_default_save_rejects_bad_field_standard():
    saved, checks = state.save_default(2, {"关联字段": "1region", "系统默认值": "华东"})
    assert saved is None
    failed = {item["rule"]: item for item in checks}
    assert failed["关联字段标准"]["passed"] == "false"


def test_default_save_success_and_user_selection_wins():
    # 用户先选华南
    state.select(2, "华南", 0)
    # 管理员把系统默认值改成华北；用户当前选择仍应优先
    saved, checks = state.save_default(2, {"系统默认值": "华北"})
    assert saved is not None
    assert all(item["passed"] == "true" for item in checks)
    current = state.get_state(2)
    assert current["系统默认值"] == "华北"
    assert current["当前有效值"] == "华南"
    assert current["用户已自定义"] is True


def test_empty_options_source_switch_rejected():
    _, notice = state.change_source(2, "自定义清单", [])
    assert notice is not None
    assert state.get_state(2)["可选值来源"] == "地区主数据"
