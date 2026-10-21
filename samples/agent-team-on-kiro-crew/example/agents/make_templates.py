"""Build the Kiro agent templates of the example company's team: AWS AI-DLC's official experts (their definitions
verbatim as the prompt, plus how to work in Kiro Crew at that company) and one expert the company adds itself (brand motion).

    python3 make_templates.py <vendor/aidlc-workflows/agents> <out dir> <kirocrew binary>

桃源科技: the 14 experts under their official names and taoyuan-motion-agent.
Writes <out>/<name>.json, one per agent. Nothing else is touched; scripts/install-example.sh copies them to
~/.kiro/agents/.
"""
import json
import sys
from pathlib import Path

OFFICIAL, OUT, KIROCREW = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]

# display name, one line in Chinese (what Kiro Crew's Teammates page shows)
TEAM = {
    "aidlc-product-agent": ("产品", "AI-DLC 产品专家：意图、需求、验收标准"),
    "aidlc-product-lead-agent": ("产品负责人", "AI-DLC 产品负责人：范围、优先级、取舍"),
    "aidlc-architect-agent": ("架构", "AI-DLC 架构专家：方案、接口、分工"),
    "aidlc-architecture-reviewer-agent": ("架构评审", "AI-DLC 架构评审：独立审方案"),
    "aidlc-design-agent": ("设计", "AI-DLC 设计专家：界面、交互、无障碍、设计规范"),
    "aidlc-developer-agent": ("开发", "AI-DLC 开发专家：写代码、接口、数据"),
    "aidlc-quality-agent": ("质量", "AI-DLC 质量专家：测试策略、按验收标准写测试"),
    "aidlc-devsecops-agent": ("安全", "AI-DLC 安全专家：安全基线、审代码改动"),
    "aidlc-compliance-agent": ("合规", "AI-DLC 合规专家：个人信息、数据分级、合规对照"),
    "aidlc-pipeline-deploy-agent": ("流水线部署", "AI-DLC 流水线与部署专家：部署配置、冒烟"),
    "aidlc-aws-platform-agent": ("AWS 平台", "AI-DLC AWS 平台专家：云上基础设施"),
    "aidlc-operations-agent": ("运维", "AI-DLC 运维专家：可观测、事故响应"),
    "aidlc-delivery-agent": ("交付", "AI-DLC 交付专家：发布计划、上线"),
    "aidlc-composer-agent": ("组队 Composer", "AI-DLC 组队：按 scope 选阶段和专家"),
}
CUSTOM = "taoyuan-motion-agent"

CREW = """

---

## 在 Kiro Crew 里工作（桃源科技）

- 你是一支 agent 团队里的一员。编排器会把任务发给你：任务里写明了需求、你能改哪些文件、先读哪些上游产出、做完怎么提交。以任务为准，不做任务以外的事。
- **公司的规范、业务规则和数据都在 Kiro Crew 的知识库里**（来源「桃源科技」）。任务提到的规范和数据，先用 `local_knowledge_search` 查知识库，再动手；产出里写明用了哪条（规则编号，比如 RULE-2、PII-1）。知识库里写了数据文件路径的，按路径读文件，不要手抄。
- 只改任务允许的文件。改完 `git add` 并 `git commit`，提交信息用中文写清做了什么。
- 回复最后用三行总结：改了哪些文件、对照了哪些规范、还有没有没做完的。
"""


def official_prompt(name: str) -> str:
    text = (OFFICIAL / f"{name}.md").read_text(encoding="utf-8")
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    text = text.replace("{{HARNESS_DIR}}", "aidlc/official").strip()
    if len(text) > 12000:  # the composer's playbook is 60 KB; it does not take part in these runs
        text = text[:12000].rsplit("\n", 1)[0] + "\n\n（以下省略，完整定义见 aidlc/official/agents/" + name + ".md）"
    return text + CREW


def template(name: str, display: str, desc: str, prompt: str) -> dict:
    return {
        "name": name,
        "description": f"{display} · {desc}",
        "prompt": prompt,
        "tools": ["fs_read", "fs_write", "execute_bash", "@kirocrew-core"],
        "allowedTools": ["fs_read", "fs_write", "execute_bash", "@kirocrew-core"],
        "includeMcpJson": False,
        "includeCrewContext": False,
        "mcpServers": {"kirocrew-core": {"command": KIROCREW, "args": ["mcp-core"]}},
    }


MOTION = """# 品牌动效专家（桃源科技自定义）

AWS AI-DLC 的 14 位官方专家里没有动效这个角色。桃源科技的活动页、大屏和 App 里的动效要统一品牌感，所以公司自己加了这一位。

你负责页面的动效：入场、滚动、揭晓、庆祝。原则：

- 动效为信息服务：让人看清"正在发生什么、结果是什么"，不为炫而炫。
- 只用品牌规范里的颜色和缓动变量（`--brand-*`、`--ease-*`），小桃子形象按品牌规范用。
- 只用 CSS 动画、Web Animations API 和 `<canvas>`，不引第三方动画库、不用 CDN（前端工程规范 FE-2）。
- 一定支持"减少动态效果"（UX-1）：`prefers-reduced-motion: reduce` 时关掉滚动和粒子，直接显示结果。
- 60 帧：只动 `transform` 和 `opacity`，粒子数量有上限，动画结束清理定时器和 canvas。
- 动效代码放在自己的模块里，给页面一个小接口（比如 `spin(names)`、`reveal(winner)`、`celebrate()`），页面不用知道动效怎么实现。
"""



def write(name: str, t: dict) -> None:
    (OUT / f"{name}.json").write_text(json.dumps(t, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (display, desc) in TEAM.items():
        write(name, template(name, display, desc, official_prompt(name)))
    write(CUSTOM, template(CUSTOM, "品牌动效", "桃源科技自定义：活动页和大屏的品牌动效", MOTION + CREW))
    print(f"{len(TEAM) + 1} templates -> {OUT}")


if __name__ == "__main__":
    main()
