"""桃源科技官方商城的模拟数据（双十一促销场景）：商品、过去 60 天的订单、运营提报的活动方案。

    python3 example-company/tools/make_mall_data.py      # -> example-company/data/mall-*.json

固定随机种子，每次生成的内容一样。数字是按示例的情节凑的，生成完会打印校验：
- 运营方案里 65 寸电视 Q7（8 折）和扫地机器人 X9（7 折）低于毛利底线（MGN-2）；
- 按方案算，价保退差约 48.6 万，超过 30 万的审批线（PP-2）；
- 电视改 9 折、X9 改 8 折以后，毛利都过线，退差约 28.0 万；
- 三款商品活动前 7 天做过闪购，划线价要按 7 日最低成交价（PRC-1），不能用日常价。
"""

import json
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data"
START = date(2026, 11, 1)          # 活动开始
TODAY = START - timedelta(days=1)  # 数据截止 2026-10-31
rng = random.Random(20261111)

# sku, 名称, 品类, 日常价, 成本, 库存, 30 天价保, 方案折扣（%）, 方案参加满减
PRODUCTS = [
    ("TV65", "65 寸智能电视 Q7", "电视", 5399, 3700, 800, True, 80, True),
    ("TV55", "55 寸智能电视 Q5", "电视", 3299, 2300, 1200, False, 85, True),
    ("TV75", "75 寸 Mini LED 电视 Q9", "电视", 8999, 6200, 300, False, 85, True),
    ("AC35", "1.5 匹变频空调 KFR-35", "空调", 2999, 2050, 1500, True, 85, True),
    ("AC50", "2 匹柜机空调 KFR-50", "空调", 4599, 3200, 600, False, 85, True),
    ("RF500", "500L 十字门冰箱 R5", "冰箱", 4999, 3450, 500, False, 85, True),
    ("RF300", "300L 三门冰箱 R3", "冰箱", 2299, 1600, 900, False, 90, True),
    ("WM10", "10kg 滚筒洗衣机 W10", "洗衣机", 2799, 1900, 900, False, 85, True),
    ("WD10", "洗烘套装 WD10", "洗衣机", 6999, 4800, 300, False, 85, True),
    ("DW13", "13 套嵌入式洗碗机 D13", "厨卫", 3999, 2700, 400, False, 85, True),
    ("RH01", "烟灶套装 H1", "厨卫", 3699, 2500, 500, False, 85, True),
    ("X9", "扫地机器人 X9", "清洁", 2999, 1950, 1000, True, 70, True),
    ("V8", "无线吸尘器 V8", "清洁", 1599, 1050, 1200, True, 85, True),
    ("P5", "空气净化器 P5", "清洁", 1899, 1250, 800, False, 85, True),
    ("T1", "手机 T1 Pro", "数码", 3999, 3100, 2000, False, 95, False),
    ("PAD11", "平板 Pad 11", "数码", 2499, 1850, 1500, False, 90, False),
    ("BUDS3", "降噪耳机 Buds 3", "数码", 699, 420, 3000, True, 85, True),
    ("W2", "智能手表 W2", "数码", 1299, 850, 2000, True, 85, True),
    ("IH5", "IH 电饭煲 5L", "厨卫", 799, 480, 2500, True, 80, True),
    ("EH60", "60L 电热水器 E6", "厨卫", 1999, 1300, 700, False, 85, True),
]
# 活动前 7 天的闪购（让划线价不能用日常价）：sku -> (日期, 成交价, 单数)
FLASH = {"AC35": (date(2026, 10, 27), 2599, 2), "WD10": (date(2026, 10, 26), 6499, 3), "P5": (date(2026, 10, 28), 1699, 5)}
# 价保商品在 30 天里按日常价卖出的单数（价保退差主要来自这些）
PP_UNITS = {"TV65": 300, "X9": 147, "V8": 40, "BUDS3": 60, "W2": 40, "IH5": 37, "AC35": 0}
FULL = {"every": 2000, "off": 200}


def day(back: int) -> str:
    return (TODAY - timedelta(days=back)).isoformat()


def main() -> None:
    products = [{"sku": s, "name": n, "category": c, "price": p, "cost": k, "stock": st, "priceProtect": pp}
                for s, n, c, p, k, st, pp, _, _ in PRODUCTS]
    orders, seq = [], 0

    def add(sku: str, paid: int, when: str, qty: int = 1, status: str = "已完成") -> None:
        nonlocal seq
        seq += 1
        orders.append({"id": f"TY{seq:06d}", "sku": sku, "paid": paid, "qty": qty, "date": when, "status": status})

    for s, _, _, price, _, _, pp, _, _ in PRODUCTS:
        # 31～60 天前：每款都有一些（在价保期外，也不在 7 天里）
        for _ in range(rng.randint(20, 60)):
            add(s, price, day(rng.randint(30, 59)))
        if pp:
            for _ in range(PP_UNITS.get(s, 0)):           # 30 天内按日常价、已完成：要退差
                add(s, price, day(rng.randint(0, 29)))
            for _ in range(rng.randint(5, 15)):           # 30 天内退货的：不退差
                add(s, price, day(rng.randint(0, 29)), status="已退货")
        else:
            for _ in range(rng.randint(30, 90)):          # 没有价保的商品，30 天内正常卖
                add(s, price, day(rng.randint(0, 29)))
    for s, (when, paid, n) in FLASH.items():
        for _ in range(n):
            add(s, paid, when.isoformat())
    orders.sort(key=lambda o: (o["date"], o["id"]))
    for i, o in enumerate(orders, 1):
        o["id"] = f"TY{i:06d}"

    campaign = {
        "name": "桃源科技官方商城 · 双十一",
        "start": "2026-11-01T00:00:00+08:00",
        "end": "2026-11-11T23:59:59+08:00",
        "fullReduction": {"every": FULL["every"], "off": FULL["off"], "withDiscount": True, "withCoupon": False},
        "items": [{"sku": s, "pct": pct, "fullReduction": fr, "linePriceInput": price}
                  for s, _, _, price, _, _, _, pct, fr in PRODUCTS],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "mall-products.json").write_text(json.dumps(products, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (OUT / "mall-orders.json").write_text(json.dumps(orders, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    (OUT / "mall-campaign.json").write_text(json.dumps(campaign, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    check(products, orders, campaign)


def check(products, orders, campaign) -> None:
    """The story the numbers have to tell (the same rules as the knowledge base: PRC-1, MGN-1/2, PP-1/2)."""
    by = {p["sku"]: p for p in products}
    lo7 = (TODAY - timedelta(days=6)).isoformat()
    lo30 = (TODAY - timedelta(days=29)).isoformat()

    def final(sku, pct):
        return (by[sku]["price"] * pct + 50) // 100

    def line(sku):
        seen = [o["paid"] for o in orders if o["sku"] == sku and o["status"] == "已完成" and o["date"] >= lo7]
        return min(seen) if seen else by[sku]["price"]

    def pp(pcts):
        amount, n = 0, 0
        for o in orders:
            p = by[o["sku"]]
            if not p["priceProtect"] or o["status"] != "已完成" or o["date"] < lo30:
                continue
            f = final(o["sku"], pcts[o["sku"]])
            if o["paid"] > f:
                amount += (o["paid"] - f) * o["qty"]
                n += 1
        return amount, n

    pcts = {i["sku"]: i["pct"] for i in campaign["items"]}
    fr = {i["sku"]: i["fullReduction"] for i in campaign["items"]}

    def below(pcts):
        out = []
        for s, pct in pcts.items():
            f = final(s, pct)
            low = (f * 9 + 5) // 10 if fr[s] else f
            if low * 100 < by[s]["cost"] * 108:
                out.append(s)
        return out

    print("划线价不等于日常价的：", {s: line(s) for s in by if line(s) != by[s]["price"]})
    print("方案：低于毛利底线", below(pcts), "价保退差", pp(pcts))
    fixed = {**pcts, "TV65": 90, "X9": 80}
    print("改后：低于毛利底线", below(fixed), "价保退差", pp(fixed))
    print("订单", len(orders), "条")


if __name__ == "__main__":
    main()
