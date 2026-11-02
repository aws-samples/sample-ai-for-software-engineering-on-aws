"""Build the Kiro agent templates of the vstatd team: the four AWS AI-DLC experts it uses, their definitions verbatim
as the prompt, plus how to work in Kiro Crew on vstatd (adapted from the agent-team sample's make_templates.py).

    python3 make_templates.py <vendor/aidlc-workflows/agents> <out dir> <kirocrew binary>

Writes <out>/<name>.json, one per expert. Nothing else is touched; setup.sh copies them to ~/.kiro/agents/. The tools
are those of the agent-team templates: file reads and writes, shell commands, and Kiro Crew's own MCP server
(``@kirocrew-core``, whose ``local_knowledge_search`` answers from the knowledge source ``vstatd``). D2 in
docs/kiro-crew-app.md says what this allows.
"""
import json
import sys
from pathlib import Path

KNOWLEDGE = "vstatd"

# display name, one line in Chinese (what Kiro Crew's Teammates page shows)
TEAM = {
    "aidlc-developer-agent": ("开发", "AI-DLC 开发专家：分诊、修复和重构 vstatd"),
    "aidlc-architect-agent": ("架构", "AI-DLC 架构专家：重构方案和按源文件分工"),
    "aidlc-quality-agent": ("质量", "AI-DLC 质量专家：测试先行，先失败的单元测试"),
    "aidlc-architecture-reviewer-agent": ("架构评审", "AI-DLC 架构评审：独立、只读，复核说明和保住的行为"),
}

CREW = f"""

---

## 在 Kiro Crew 里工作（车载平台服务 vstatd）

- 你是一支 agent 团队里的一员。编排器会把任务发给你：任务里写明了要做什么、你能改哪些文件、先读哪些上游产出、做完怎么提交。以任务为准，不做任务以外的事。
- **接口规范、平台说明、团队规则和静态分析待办都在 Kiro Crew 的知识库里**（来源「{KNOWLEDGE}」）。先用 `local_knowledge_search` 查知识库，再动手；产出里写引用，比如 `[VSTATD-IF p.7 §4.1]`、`[CC1-PN §6]`、`[TR §4.1]`。知识库里没有的数据和规则不要编。
- 只改任务允许的文件。改完 `git add` 并 `git commit`，提交说明写上对应的发现编号（F-nnn）。
- 检查和台架上的动作由 app 跑，部署和回放由人在操作台上批准：不要自己连台架、不要动台架状态（`~/.cc1-bench`）和检查的结果目录。
- 回复最后用三行总结：改了哪些文件、引用了哪些规范、还有没有没做完的。
"""


def official_prompt(official: Path, name: str) -> str:
    text = (official / f"{name}.md").read_text(encoding="utf-8")
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    return text.replace("{{HARNESS_DIR}}", "aidlc/official").strip() + CREW


def template(name: str, display: str, desc: str, prompt: str, kirocrew: str) -> dict:
    return {
        "name": name,
        "description": f"{display} · {desc}",
        "prompt": prompt,
        "tools": ["fs_read", "fs_write", "execute_bash", "@kirocrew-core"],
        "allowedTools": ["fs_read", "fs_write", "execute_bash", "@kirocrew-core"],
        "includeMcpJson": False,
        "includeCrewContext": False,
        "mcpServers": {"kirocrew-core": {"command": kirocrew, "args": ["mcp-core"]}},
    }


def build(official: Path, out: Path, kirocrew: str) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, (display, desc) in TEAM.items():
        path = out / f"{name}.json"
        t = template(name, display, desc, official_prompt(official, name), kirocrew)
        path.write_text(json.dumps(t, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written


def main(argv: list) -> int:
    if len(argv) != 3:
        print("usage: python3 make_templates.py <vendor/aidlc-workflows/agents> <out dir> <kirocrew binary>", file=sys.stderr)
        return 2
    print(f"{len(build(Path(argv[0]), Path(argv[1]), argv[2]))} templates -> {argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
