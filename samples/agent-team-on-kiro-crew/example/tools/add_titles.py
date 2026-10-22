"""给员工花名册加「职位」和「上级」：每个部门入职最早的在职正式员工是部门负责人（没有上级）；研发中心和销售部另有两位组长
（入职第二、第三早的在职正式员工），组员按工号轮流分给组长；别的部门都直接向负责人汇报。职位按部门和入职年份定。
可以重复跑：只按已有字段算，结果一样。

    python3 example/tools/add_titles.py        # 改 example/data/employees.json，并重写 knowledge/data/员工花名册.md 里的样例表
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DATA = HERE / "data" / "employees.json"
DOC = HERE / "knowledge" / "data" / "员工花名册.md"

HEAD = {"研发中心": "研发总监", "产品部": "产品总监", "设计部": "设计总监", "市场部": "市场总监", "销售部": "销售总监",
        "客户成功部": "客户成功总监", "财务部": "财务总监", "人力资源部": "人力资源总监", "行政部": "行政经理"}
LEAD = {"研发中心": "技术经理", "销售部": "区域销售经理"}
# (入职在 2020 年以前的, 之后的)
STAFF = {"研发中心": ("高级工程师", "工程师"), "产品部": ("高级产品经理", "产品经理"), "设计部": ("高级设计师", "设计师"),
         "市场部": ("市场经理", "市场专员"), "销售部": ("高级销售", "销售代表"), "客户成功部": ("客户成功经理", "客户成功专员"),
         "财务部": ("财务经理", "会计"), "人力资源部": ("HRBP", "招聘专员"), "行政部": ("行政主管", "行政专员")}


def main() -> None:
    people = json.loads(DATA.read_text(encoding="utf-8"))
    by_dept: dict[str, list[dict]] = {}
    for p in people:
        by_dept.setdefault(p["dept"], []).append(p)
    for dept, staff in by_dept.items():
        senior = sorted((p for p in staff if p["status"] == "在职" and p["type"] == "正式"), key=lambda p: (p["joined"], p["id"]))
        head = senior[0]
        leads = senior[1:3] if dept in LEAD else []
        head["title"], head["manager"] = HEAD[dept], None
        for lead in leads:
            lead["title"], lead["manager"] = LEAD[dept], head["id"]
        rest = [p for p in sorted(staff, key=lambda p: p["id"]) if p is not head and p not in leads]
        for i, p in enumerate(rest):
            p["title"] = STAFF[dept][0 if p["joined"] < "2020" else 1]
            p["manager"] = leads[i % len(leads)]["id"] if leads else head["id"]
    keys = ["id", "name", "dept", "title", "manager", "joined", "status", "type", "phone"]
    people = [{k: p[k] for k in keys} for p in people]
    DATA.write_text(json.dumps(people, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rows = ["| 工号 | 姓名 | 部门 | 职位 | 上级 | 入职日期 | 状态 | 类型 | 手机号 |", "|---|---|---|---|---|---|---|---|---|"]
    for p in people[:10]:
        phone = p["phone"][:3] + "****" + p["phone"][-4:]
        rows.append(f"| {p['id']} | {p['name']} | {p['dept']} | {p['title']} | {p['manager'] or '—'} | {p['joined']} | {p['status']} | {p['type']} | {phone} |")
    doc = DOC.read_text(encoding="utf-8")
    doc = re.sub(r"\| 工号 \|.*?\n(?=\n|$)", "\n".join(rows) + "\n", doc, count=1, flags=re.S)
    DOC.write_text(doc, encoding="utf-8")
    heads = sum(1 for p in people if p["manager"] is None)
    print(f"{len(people)} 人，{heads} 位部门负责人，{sum(1 for p in people if p['title'] in LEAD.values())} 位组长")


if __name__ == "__main__":
    main()
