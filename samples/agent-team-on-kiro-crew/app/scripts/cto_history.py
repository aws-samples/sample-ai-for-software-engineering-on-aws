"""CTO 视图的模拟历史：桃源科技研发中心（5 条业务线 × 12 人）近 12 周与引入 AI-DLC 之前 12 周的交付清单，以及此刻
进行中的需求（需求池、agent 在做、停在人的关卡上）。每项交付带 Issue（提出方、创建日）和合入 main 的 PR；部分修复是
某项新应用/新功能上线后的缺陷，两边互相链接。写到 cto/history.json，随 app 打包；后端（backend/team/cto.py）
把日期平移到今天，再并入这台 Mac 上签过字的运行（实测）和还没签字的运行（进行中）。

    python3 scripts/cto_history.py

固定随机种子，每次生成结果相同。这些数字是示例，用来让 CTO 视图开箱有内容，不代表任何实测的效率提升。
"""
from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "cto" / "history.json"
SEED = 20261016
TODAY = date(2026, 10, 16)
AGENT_START = TODAY - timedelta(days=83)       # 近 12 周的第一天
BASE_START = AGENT_START - timedelta(days=84)  # 前 12 周的第一天
rng = random.Random(SEED)

# 每条业务线每周的交付量（泊松均值）。基线按 v0.2 原型的 12 人小组校准；近 12 周为满负荷时的量，乘以逐周推广系数
BASE_RATE = {"S": 68 / 12, "M": 19 / 12, "L": 2 / 12}
AGENT_RATE = {"S": 18.4, "M": 9.3, "L": 0.85}
RAMP = [0.40, 0.48, 0.56, 0.64, 0.72, 0.80, 0.88, 0.96, 1.0, 1.0, 1.0, 1.0]
# 交付周期（日历天，均匀分布）：示例值
CYCLE = {"base": {"S": (1, 3), "M": (7, 13), "L": (26, 34)}, "agent": {"S": (0.3, 1.3), "M": (1.5, 3.5), "L": (5, 9)}}
# 规模 → 类型
KIND = {"S": [("fix", 1.0)], "M": [("feat", 0.9), ("app", 0.1)], "L": [("app", 0.8), ("feat", 0.2)]}

LINES = [
    {"key": "ec", "name": "电商", "signers": ["Zhang Min", "Liu Yang"],
     "app": ["以旧换新回收平台", "新品预售系统", "直播带货选品后台", "会员积分商城", "企业团购专区", "门店自提预约", "商品评价审核后台", "价格巡检工具", "优惠券中心", "套购组合配置后台", "安装服务预约"],
     "feat": ["商品详情页视频展示", "满减凑单推荐", "购物车价格明细", "以旧换新估价", "预售定金尾款", "商品参数对比", "限时秒杀", "晒单返券", "优惠券叠加规则", "搜索联想词", "分期免息展示", "价保自助申请", "收货地址智能识别", "发票自助开具", "到手价计算"],
     "fix": ["活动页首屏加载过慢", "划线价取数口径修正", "限购提示在小屏上被遮挡", "支付回调超时重试", "搜索结果排序异常", "优惠券过期提示文案", "商品图片懒加载失效", "订单导出字段缺失"],
     "var": ["空调", "冰箱", "洗衣机", "电视", "厨电", "小家电"]},
    {"key": "mob", "name": "移动应用", "signers": ["Chen Jing", "Zhou Tao"],
     "app": ["门店导购 App", "安装师傅接单 App", "门店巡检移动端", "会员小程序", "售后上门预约小程序", "经销商移动订货 App", "店长移动看板", "产品说明书小程序", "家电焕新小程序", "员工内购小程序"],
     "feat": ["扫码购", "一键登录", "导购客户标签", "消息推送分组", "直播间", "安装预约", "维修进度查询", "深色模式", "分享返券", "附近门店导航", "电子保修卡", "以旧换新拍照估价"],
     "fix": ["通知角标不更新", "支付页闪退", "分享卡片图片缺失", "弱网下单重复提交", "登录态过期", "推送点击跳转错误"],
     "var": ["iOS", "安卓", "小程序", "鸿蒙"]},
    {"key": "crm", "name": "客户关系管理", "signers": ["Wang Lei", "Xu Na"],
     "app": ["会员积分体系", "客服知识库", "售后工单系统", "会员分层营销平台", "客户之声分析", "400 来电助手", "延保管理", "会员权益中心", "投诉升级管理", "NPS 调研"],
     "feat": ["会员等级权益页", "生日礼券自动发放", "沉睡会员唤醒", "客服工单自动分派", "售后回访问卷", "积分到期提醒", "会员分层标签", "来电弹屏", "工单超时预警", "积分兑换审核", "客户画像标签"],
     "fix": ["积分到账延迟", "工单状态不同步", "会员手机号脱敏位数修正", "优惠券重复发放", "回访短信发送失败"],
     "var": ["金卡会员", "新客", "华东大区", "华南大区", "线上渠道", "门店渠道"]},
    {"key": "sc", "name": "供应链", "signers": ["Zhao Qiang", "Sun Peng"],
     "app": ["供应商对账平台", "经销商订货平台", "门店库存同步服务", "智能补货系统", "到货预约平台", "退货质检系统", "仓储作业看板", "供应商协同门户", "运费结算系统", "物料追溯"],
     "feat": ["安全库存预警", "订货额度控制", "补货建议", "物流轨迹查询", "退货入库质检", "仓间调拨审批", "供应商交期看板", "缺货自动提醒", "批次效期管理", "运单批量打印"],
     "fix": ["对账单金额四舍五入误差", "库存预警阈值配置", "调拨单重复生成", "运单号校验错误", "库存同步延迟"],
     "var": ["华东仓", "华南仓", "华北仓", "西南仓", "华中仓"]},
    {"key": "int", "name": "内部系统", "signers": ["Huang Li", "Wu Hao"],
     "app": ["会议室预订", "培训报名", "设备领用登记", "价保退差月报", "访客登记", "差旅报销查询", "部门周报汇总", "促销费用核算表", "合同审批台账", "新人入职清单"],
     "feat": ["加班申请审批", "会议室冲突提示", "通讯录按部门筛选", "报销单据拍照识别", "权限变更审批", "离职账号自动停用", "两步验证接入", "登录异常提醒", "月报自动推送"],
     "fix": ["通讯录部门排序", "月报导出金额格式", "退货订单口径修正", "锁定时长配置修正", "审批提醒重复发送"],
     "var": ["财务部", "行政部", "人力资源部", "法务部", "信息安全组"]},
]
LINE_IDX = {ln["key"]: i for i, ln in enumerate(LINES)}
GATES = ["需求关卡", "范围关卡", "上线关卡", "签字放行"]  # 模拟的进行中需求停在哪个人的关卡上

def poisson(lam: float) -> int:
    l, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= l:
            return k
        k += 1


def pick_kind(size: str) -> str:
    r, acc = rng.random(), 0.0
    for kind, w in KIND[size]:
        acc += w
        if r < acc:
            return kind
    return KIND[size][-1][0]


def title_for(line: dict, kind: str, used: dict) -> str:
    if kind == "app":
        base = rng.choice(line["app"])
        n = used.get(base, 0) + 1
        used[base] = n
        return base if n == 1 else f"{base}（{'二三四五六七八九十'[min(n - 2, 8)]}期）"
    return f"{rng.choice(line[kind])}（{rng.choice(line['var'])}）"


# 需求流动看板的列（AI-DLC 阶段）；人的关卡落在哪一列
GATE_COL = {"范围关卡": "构思", "需求关卡": "启动", "上线关卡": "运维", "签字放行": "运维"}
AGENT_COL = (["构思", "启动", "构建", "运维"], [2, 2, 5, 1])
SCOPE_Q = ["毛利率按销售额还是成本计", "统计窗口从哪天起算", "已退货订单是否计入", "外包人员是否可见", "手机号显示几位", "跨大区数据能否合并"]


def focus(gate: str, line: dict) -> str:
    """卡片上「人要决定什么」。"""
    if gate == "范围关卡":
        n = rng.randint(1, 3)
        return f"{n} 个口径待答复：{rng.choice(SCOPE_Q)}" + ("等" if n > 1 else "")
    if gate == "需求关卡":
        return f"确认分工与验收标准（{rng.randint(4, 8)} 位成员）"
    if gate == "上线关卡":
        if line["key"] == "ec":
            return f"上线前核算：价保退差 {rng.randint(31, 60)} 万元，超过 30 万需 CFO 审批"
        return "独立审查已通过，待批准上线"
    return "已部署并通过健康检查，待签字放行"


def wip(used: dict) -> list[dict]:
    """此刻的需求流动（模拟）：需求池里待组队的，agent 在做的，停在人的关卡上等人决定的。"""
    out = []
    for li, line in enumerate(LINES):
        for _ in range(rng.randint(1, 2)):
            size = rng.choices("SML", weights=[5, 4, 1])[0]
            kind = pick_kind(size)
            out.append({"t": title_for(line, kind, used), "line": li, "kind": kind, "size": size, "state": "pool", "col": "需求池",
                        "mins": rng.randint(1, 50)})
        for _ in range(rng.randint(5, 7)):
            size = rng.choices("SML", weights=[5, 4, 1])[0]
            kind = pick_kind(size)
            it = {"t": title_for(line, kind, used), "line": li, "kind": kind, "size": size}
            if rng.random() < 0.33:
                gate = rng.choice(GATES)
                it.update(state="wait", gate=gate, col=GATE_COL[gate], who=rng.choice(line["signers"]),
                          hours=round(rng.uniform(0.2, 3.6), 1), focus=focus(gate, line))
            else:
                it.update(state="agent", col=rng.choices(*AGENT_COL)[0], members=rng.randint(3, 8), mins=rng.randint(3, 40))
            out.append(it)
    return out


# Issue 的提出方（按业务线）；上线后缺陷由谁报
REPORTERS = {"ec": ["运营部", "商品部", "市场部"], "mob": ["用户体验组", "门店运营部"], "crm": ["会员运营部", "客服中心"],
             "sc": ["供应链管理部", "仓储物流部"], "int": ["行政部"]}
DEFECT_FROM = ["客服中心", "线上监控"]
DEFECT_RATE = {"base": 0.08, "agent": 0.05}  # 新应用/新功能上线后 30 天内报出缺陷的比例
ISSUE0, PR0 = 1001, 1201


def trace(items: list[dict], wips: list[dict]) -> None:
    """给交付和进行中的需求补上 Issue 与 PR，并把部分修复链接到它修的那项交付。用另一个随机种子，不改动已有的
    任何数字（条数、类型、规模、周期、上线日）。"""
    r = random.Random(SEED + 1)
    for it in items:
        it["created"] = (date.fromisoformat(it["ship"]) - timedelta(days=int(it["cyc"]))).isoformat()
        line = LINES[it["line"]]
        var = it["t"].rsplit("（", 1)[-1].rstrip("）") if "（" in it["t"] else ""
        it["reporter"] = var if line["key"] == "int" and var.endswith(("部", "组")) else r.choice(REPORTERS[line["key"]])
    fixes = sorted((i for i in items if i["kind"] == "fix"), key=lambda i: i["ship"])
    taken: set[int] = set()
    for it in sorted((i for i in items if i["kind"] != "fix"), key=lambda i: i["ship"]):
        if r.random() >= DEFECT_RATE[it["period"]]:
            continue
        ship = date.fromisoformat(it["ship"])
        cands = [k for k, f in enumerate(fixes) if k not in taken and f["line"] == it["line"]
                 and 3 <= (date.fromisoformat(f["ship"]) - ship).days <= 30]
        if not cands:
            continue
        k = r.choice(cands)
        taken.add(k)
        fix = fixes[k]
        fix["t"] = f"{it['t']}上线后缺陷修复"
        fix["reporter"] = r.choice(DEFECT_FROM)
        fix["origin"] = id(it)
        it.setdefault("defects", []).append(id(fix))
    by_created = sorted(items, key=lambda i: (i["created"], i["ship"], i["t"]))
    num = {id(i): f"TY-{ISSUE0 + n}" for n, i in enumerate(by_created)}
    for n, it in enumerate(sorted(items, key=lambda i: (i["ship"], i["created"], i["t"]))):
        it["issue"], it["pr"] = num[id(it)], PR0 + n
    for it in items:
        if "origin" in it:
            it["origin"] = num[it["origin"]]
        if "defects" in it:
            it["defects"] = [num[d] for d in it["defects"]]
    nxt, pr = ISSUE0 + len(items), PR0 + len(items)
    for w in wips:
        w["issue"], nxt = f"TY-{nxt}", nxt + 1
        w["reporter"] = r.choice(REPORTERS[LINES[w["line"]]["key"]])
        if w.get("gate") == "签字放行":
            w["pr"], pr = pr, pr + 1


def gen() -> list[dict]:
    items, used = [], {}
    for period, start, rates in (("base", BASE_START, None), ("agent", AGENT_START, AGENT_RATE)):
        for w in range(12):
            wk0 = start + timedelta(days=7 * w)
            for li, line in enumerate(LINES):
                for size in ("S", "M", "L"):
                    lam = BASE_RATE[size] if period == "base" else rates[size] * RAMP[w]
                    for _ in range(poisson(lam)):
                        ship = wk0 + timedelta(days=rng.randrange(7))
                        if ship > TODAY:
                            continue
                        cyc = round(rng.uniform(*CYCLE[period][size]), 1)
                        kind = pick_kind(size)
                        items.append({"t": title_for(line, kind, used), "line": li, "kind": kind, "size": size, "period": period,
                                      "ship": ship.isoformat(), "cyc": cyc, "signer": rng.choice(line["signers"]) if period == "agent" else "",
                                      "real": None})
    return items, used


def main() -> None:
    items, used = gen()
    items.sort(key=lambda x: (x["ship"], x["t"]), reverse=True)
    meta = {"today": TODAY.isoformat(), "agentStart": AGENT_START.isoformat(),
            "weeks": [(BASE_START + timedelta(days=7 * i)).isoformat() for i in range(24)],
            "lines": [ln["name"] for ln in LINES], "peoplePerLine": 12,
            "eq": {"S": 1, "M": 5, "L": 30}, "human": {"S": 0.25, "M": 1, "L": 7},
            "dayRate": 2000, "seatUsdMonth": 40, "fx": 7.1, "months": 3}
    wips = wip(used)
    trace(items, wips)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"meta": meta, "items": items, "wip": wips}, ensure_ascii=False, separators=(",", ":")) + "\n",
                   encoding="utf-8")
    base = sum(1 for i in items if i["period"] == "base")
    linked = sum(len(i.get("defects", [])) for i in items)
    print(f"{OUT}：前 12 周 {base} 项，近 12 周 {len(items) - base} 项（不含实测）；上线后缺陷链接 {linked} 条")


if __name__ == "__main__":
    main()
