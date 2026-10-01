"""季度养护方案：批量送审、批量审批与审批汇总的回归测试。

全局 store 是单例，各用例用不同季度隔离数据，互不干扰。
运行：python3 -m pytest tests -q（在 backend 目录下）
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _create(no: str, quarter: str, plot: str, contents: list[str] | None = None, budget: float = 0.0) -> dict:
    resp = client.post("/api/seasonplan", json={"values": {
        "方案编号": no,
        "方案季度": quarter,
        "覆盖绿地": plot,
        "方案内容": contents or [],
        "预算金额": budget,
        "编制人": "测试员",
    }})
    payload = resp.json()
    assert payload["ok"], payload["message"]
    return payload["entry"]


def _action(entry_id: int, action: str, **extra) -> dict:
    resp = client.post(f"/api/seasonplan/{entry_id}/actions", json={"values": {"action": action, **extra}})
    return resp.json()


def _submit(quarter: str, plan_ids: list[int], **extra) -> dict:
    resp = client.post("/api/seasonplan/batches", json={"values": {
        "方案季度": quarter, "方案ids": plan_ids, **extra,
    }})
    return resp.json()


def _approve(batch_no: str, **extra) -> dict:
    resp = client.post(f"/api/seasonplan/batches/{batch_no}/approve", json={"values": {"审批人": "赵主任", **extra}})
    return resp.json()


def test_compile_requires_content_lines() -> None:
    """养护内容逐条填：没填内容不能标已编制，补录后才能编制。"""
    plan = _create("SEAS-T101", "2099-Q1", "测试绿地甲")
    result = _action(plan["id"], "编制方案")
    assert not result["ok"]
    assert "养护内容" in result["message"]
    resp = client.post(
        f"/api/seasonplan/{plan['id']}/contents",
        json={"values": {"方案内容": ["乔木修剪 10 株", "草坪追肥 100㎡"]}},
    )
    payload = resp.json()
    assert payload["ok"], payload["message"]
    assert payload["entry"]["方案内容"] == ["乔木修剪 10 株", "草坪追肥 100㎡"]
    result = _action(plan["id"], "编制方案")
    assert result["ok"], result["message"]
    assert result["entry"]["status"] == "已编制"
    assert result["entry"]["方案状态"] == "已编制"


def test_batch_submit_is_idempotent() -> None:
    """同一批方案重复提交只认第一次：批次号不变、批次记录不增。"""
    p1 = _create("SEAS-T201", "2099-Q2", "测试绿地乙", ["内容 1"], 10.0)
    p2 = _create("SEAS-T202", "2099-Q2", "测试绿地丙", ["内容 1"], 20.0)
    _action(p1["id"], "编制方案")
    _action(p2["id"], "编制方案")
    first = _submit("2099-Q2", [p1["id"], p2["id"]])
    assert first["ok"], first["message"]
    batch_no = first["entry"]["批次号"]
    second = _submit("2099-Q2", [p1["id"], p2["id"]])
    assert second["ok"]
    assert second["entry"]["批次号"] == batch_no
    assert "只认第一次" in second["message"]
    batches = client.get("/api/seasonplan/batches", params={"方案季度": "2099-Q2"}).json()
    assert batches["total"] == 1


def test_batch_submit_rejects_mixed_quarters() -> None:
    """方案季度统一带出：混进别的季度的方案，整批拦下。"""
    p1 = _create("SEAS-T301", "2099-Q3", "测试绿地丁", ["内容"], 5.0)
    p2 = _create("SEAS-T302", "2099-Q4", "测试绿地戊", ["内容"], 5.0)
    result = _submit("2099-Q3", [p1["id"], p2["id"]])
    assert not result["ok"]
    assert "不属于" in result["message"]


def test_batch_approve_picks_unfinished_and_is_final() -> None:
    """审批前挑出未编完的，只审已编完的；批次审过就封板。"""
    done = _create("SEAS-T401", "2099-Q5", "测试绿地己", ["内容"], 12.0)
    _action(done["id"], "编制方案")
    todo = _create("SEAS-T402", "2099-Q5", "测试绿地庚")  # 待编制，没编完
    batch = _submit("2099-Q5", [done["id"], todo["id"]])["entry"]
    result = _approve(batch["批次号"])
    assert result["ok"], result["message"]
    entry = result["entry"]
    assert [p["id"] for p in entry["审批结果"]["已审"]] == [done["id"]]
    assert [p["id"] for p in entry["审批结果"]["未编完挑出"]] == [todo["id"]]
    assert entry["预算合计"] == 12.0  # 预算按整体审批结果落
    assert client.get(f"/api/seasonplan/{done['id']}").json()["status"] == "已审批"
    assert client.get(f"/api/seasonplan/{todo['id']}").json()["status"] == "待编制"
    again = _approve(batch["批次号"])
    assert "第一次" in again["message"]
    assert again["entry"]["预算合计"] == 12.0


def test_reject_keeps_plan_in_place_for_resubmit() -> None:
    """有一片被退回时：已审的不动，退回的留在已编制等重提。"""
    p1 = _create("SEAS-T501", "2099-Q6", "测试绿地辛", ["内容"], 8.0)
    p2 = _create("SEAS-T502", "2099-Q6", "测试绿地壬", ["内容"], 9.0)
    _action(p1["id"], "编制方案")
    _action(p2["id"], "编制方案")
    batch = _submit("2099-Q6", [p1["id"], p2["id"]])["entry"]
    result = _approve(batch["批次号"], 退回ids=[p2["id"]], 退回原因="内容需补充")
    entry = result["entry"]
    assert entry["状态"] == "部分退回"
    assert [p["id"] for p in entry["审批结果"]["退回"]] == [p2["id"]]
    assert entry["预算合计"] == 8.0  # 只落审过那条的预算
    assert client.get(f"/api/seasonplan/{p1['id']}").json()["status"] == "已审批"
    assert client.get(f"/api/seasonplan/{p2['id']}").json()["status"] == "已编制"
    # 退回的那条重新送审：新批次，审过后状态才往前走
    batch2 = _submit("2099-Q6", [p2["id"]])["entry"]
    assert batch2["批次号"] != batch["批次号"]
    result2 = _approve(batch2["批次号"])
    assert result2["ok"]
    assert client.get(f"/api/seasonplan/{p2['id']}").json()["status"] == "已审批"


def test_summary_quarter_overrides_budget_and_reconciles() -> None:
    """审批汇总与方案台账对上；季度与预算条件牵连时以方案季度为准。"""
    p1 = _create("SEAS-T601", "2099-Q7", "测试绿地癸", ["内容"], 30.0)
    _action(p1["id"], "编制方案")
    batch = _submit("2099-Q7", [p1["id"]])["entry"]
    _approve(batch["批次号"])
    # 预算下限 100 与季度条件牵连：以方案季度为准，30 万的方案不被滤掉
    summary = client.get("/api/seasonplan/summary", params={"方案季度": "2099-Q7", "预算下限": 100}).json()
    assert summary["审批汇总"]["条数"] == 1
    assert summary["审批汇总"]["预算合计"] == 30.0
    assert "以方案季度为准" in summary["口径说明"]
    assert summary["台账核对"]["是否对上"]
    assert summary["台账核对"]["台账预算合计"] == summary["台账核对"]["批次留痕预算合计"]
    # 只给预算条件时按预算过滤
    summary2 = client.get("/api/seasonplan/summary", params={"预算下限": 25, "预算上限": 35}).json()
    numbers = [item["方案编号"] for item in summary2["明细"]]
    assert "SEAS-T601" in numbers
    assert summary2["台账核对"]["是否对上"]
