"""HTTP 接口层测试：验证筛选器接口与图表、看板、导出下游的同步口径。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.filter_state import filter_state_service as state


@pytest.fixture(autouse=True)
def _reset_state():
    state.reset()
    yield
    state.reset()


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_three_search_entries_return_same_filter(client):
    for keyword in ("FILT-002", "region", "地区"):
        resp = client.get("/api/filter", params={"keyword": keyword})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert [row["筛选器编号"] for row in items] == ["FILT-0002"]


def test_field_scoped_search(client):
    resp = client.get("/api/filter", params={"keyword": "地区", "field": "联动维度"})
    assert resp.json()["total"] == 1
    resp = client.get("/api/filter", params={"keyword": "region", "field": "关联字段"})
    assert resp.json()["items"][0]["筛选器编号"] == "FILT-0002"


def test_select_then_concurrent_stale_request_rejected(client):
    first = client.post("/api/filter/state/2/select", json={"values": {"value": "华南", "version": 0}})
    assert first.json()["ok"] is True
    second = client.post("/api/filter/state/2/select", json={"values": {"value": "华北", "version": 1}})
    assert second.json()["entry"]["当前有效值"] == "华北"

    stale = client.post("/api/filter/state/2/select", json={"values": {"value": "西南", "version": 1}})
    body = stale.json()
    assert body["ok"] is False
    assert body["entry"]["当前有效值"] == "华北"


def test_reset_returns_to_system_default(client):
    client.post("/api/filter/state/2/select", json={"values": {"value": "华北", "version": 0}})
    resp = client.post("/api/filter/state/2/reset")
    body = resp.json()
    assert body["ok"] is True
    assert body["entry"]["当前有效值"] == "华东"
    assert body["entry"]["用户已自定义"] is False


def test_source_change_notice_and_downstream_only_reads_new_value(client):
    # 切来源导致旧默认值失效
    resp = client.post(
        "/api/filter/state/2/source",
        json={"values": {"source": "自定义清单", "options": ["华中", "西北"]}},
    )
    body = resp.json()
    assert body["ok"] is False  # 失效场景按提示返回 ok=False，但状态已更新
    assert "来源" in body["message"]
    assert body["entry"]["系统默认值"] is None

    # 重新选择有效值
    client.post("/api/filter/state/2/select", json={"values": {"value": "华中"}})

    chart = client.get("/api/chart").json()["items"]
    cfg = next(row for row in chart if row["图表编号"] == "CFG-0007")
    assert "region=华中" in cfg["生效筛选"]

    dash = client.get("/api/dashboard").json()["items"]
    panel = next(row for row in dash if row["面板编号"] == "DASH-0005")
    assert panel["生效筛选"] == cfg["生效筛选"]


def test_invalid_default_rejected_with_basis(client):
    client.post(
        "/api/filter/state/2/source",
        json={"values": {"source": "自定义清单", "options": ["华中", "西北"]}},
    )
    resp = client.post("/api/filter/2/default", json={"values": {"系统默认值": "华东"}})
    body = resp.json()
    assert body["ok"] is False
    rules = {item["rule"]: item for item in body["entry"]["规则校验"]}
    assert rules["可选值范围"]["passed"] == "false"
    assert rules["关联字段标准"]["passed"] == "true"


def test_export_tasks_follow_effective_filter(client):
    client.post("/api/filter/state/2/select", json={"values": {"value": "西南"}})
    exported = client.get("/api/export/export").json()
    region = next(f for f in exported["filterContext"]["filters"] if f["筛选器编号"] == "FILT-0002")
    assert region["当前有效值"] == "西南"
    assert all("region=西南" in row["生效筛选"] for row in exported["items"])

    # 清空后导出立即回到系统默认值
    client.post("/api/filter/state/2/reset")
    exported = client.get("/api/export/export").json()
    region = next(f for f in exported["filterContext"]["filters"] if f["筛选器编号"] == "FILT-0002")
    assert region["当前有效值"] == "华东"


def test_state_snapshot_shape(client):
    resp = client.get("/api/filter/state")
    data = resp.json()
    assert {"items", "version", "notice"} <= set(data)
    item = data["items"][0]
    assert {"系统默认值", "用户选择", "当前有效值", "version", "规则校验"} <= set(item)
