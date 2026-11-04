"""What the app says on the board, by code: every event the run emits (and the few status lines it shows) carries a
``code`` and its ``params`` beside the Chinese ``text``, so the board can say it in the language the person chose.
The templates live here, Chinese (ZH, which renders ``text``) and English (EN, for the audit trail in English); the
board has the same two under ``ev.<code>`` in ``ui/src/i18n``, and a test keeps them equal.

A template holds ``{name}`` for a param, and ``[[name|then]]`` / ``[[name|then|else]]`` for a part that shows only
when the param is set (not empty, not 0). A param named ``r_…`` holds a role key (or a list of them) and renders as
the role's name; ``g_…`` holds a role key and renders as its gate's label (or its name). A list renders joined by
``、``; a list of objects renders each with the template ``<code>.<name>``, joined by ``；``; an object with a
``code`` renders as that message.

What the params hold is not translated: the person's notes, the agents' summaries, check names, file paths, commits,
and the reasons the app passes on from the checks and the bench.
"""
from __future__ import annotations

import re
from typing import Any, Callable

ZH: dict[str, str] = {
    # the run
    "run.start": "运行开始：{title}",
    "run.stopped": "运行已停止",
    "run.error": "运行出错，停下了：{error}",
    "run.repo_failed": "运行失败：建仓库出错：{error}",
    "run.tests_failed": "运行失败：app 跑不了测试：{error}",
    "run.tests_first_failed": "运行失败：app 没法在需求提交上跑测试：{error}",
    "run.after_bench_failed": "运行失败：app 跑不了台架之后的检查：{error}",
    "run.ownership_failed": "运行失败：分工文件 {file} 用不了：{error}",
    "run.review_rounds": "运行结束：[[rounds|评审打回 {rounds} 轮后仍要改，交给人决定|评审要改]]",
    "run.done_red": "运行结束：审查说[[summary|{summary}|没有结论]]，但测试还有 {red} 项没过，交给人决定",
    "run.done_ok": "运行完成：审查说可以交付",
    "run.done": "运行完成[[verdict|：{verdict}]]",
    "run.held": "运行停下，交给人决定：{why}",
    "run.failed_roles": "运行失败：{r_roles}没做完，后面的角色没法开工",
    "retry.bench": "重试：{by}让台架从「{step}」接着做[[note|（{note}）]]",
    "retry.review": "重试：{by}按评审意见改[[note|，附人的决定：{note}]]",
    "retry.roles": "重试：{r_roles}",
    "signoff": "{by} 签字放行[[note|：{note}]][[pr|；PR #{pr} 合入 main（{merged}）]]",
    # members and roles
    "member.missing": "{r_role}没开工：Crew「代理」里还没有成员 {member}，加上就自动开工",
    "member.added": "成员 {member} 加上了，{r_role}开工",
    "handoff": "{r_from}把 [[outs|{outs}|产出]] 交给{r_role}",
    "spawned.dispatch": "编排器派活：{r_role} · {task}[[again|（{again}）]]",
    "spawned.start": "{r_role}开工[[again|（{again}）]]",
    "spawned.round": "{r_role}第 {n} 轮：{label}[[again|（{again}）]]",
    "tool": "{r_role}：{tool}",
    "committed": "{r_role}提交：{subject}",
    "committed.app": "app 替{r_role}提交了 {n} 个文件",
    "violation": "{r_role}改了不属于它的 {path}",
    "done": "{r_role}完成[[summary|：{summary}]]",
    "merged": "{r_role}的分支合入运行分支",
    "conflict": "{r_role}合入冲突：{note}",
    "failed.nochange": "{r_role}第 {n} 轮没有改动：[[summary|{summary}|没说原因]]",
    "failed.round": "{r_role}第 {n} 轮没修成：{why}",
    "failed.role": "{r_role}失败：{why}",
    "skipped": "{r_role}：{why}[[globs|；归它的检查（{globs}）这次不跑]]",
    "skipped.unneeded": "{r_role}：这个项目用不到，跳过",
    "ownership": "编排器按{r_from}的分工派活：{assigned}",
    "ownership.assigned": "{r_role} {files}",
    # findings
    "finding.add": "{by}补登 {id}（{check} 发现：{location}，{decision}），交给{r_role}，可写 [[paths|{paths}|不变]][[go_on|，接着运行]][[note|：{note}]]",
    "finding.extend": "{by}给已补登的 {id}（{check} 发现：{location}）加可写路径，交给{r_role}，可写 [[paths|{paths}|不变]][[go_on|，接着运行]][[note|：{note}]]",
    # sent back
    "bounce.finding": "按负责人补登的 {ids}，{cases} 交给{r_role}再修一轮",
    "bounce.split": "分工文件不对，退回{r_role}：{error}",
    "bounce.triage_format": "分诊文件不合格式，退回{r_role}：{error}",
    "bounce.conflict": "合入冲突，打回{r_role}",
    "bounce.tests": "{cases}[[more|等]] 失败，打回{r_role}",
    "bounce.tests_first": "测试先行没过，打回{r_role}：{why}",
    "bounce.checks": "检查 {cases} 没过，打回{r_role}",
    "bounce.test_writer": "{cases}[[more|等]] 失败，{r_owners}说测试本身有问题，打回{r_role}",
    "bounce.triage_changed": "人在{g_gate}关卡改了 {n} 条决定，退回{r_role}照着改",
    "bounce.gate_review": "人在{g_gate}关卡退回：按审查意见再改一轮[[note|：{note}]]",
    "bounce.gate": "人在{g_gate}关卡退回：{note}",
    "bounce.by_person": "按人的意见打回{r_role}",
    "bounce.rejected": "人退回了{g_gate}：[[note|{note}|没写原因]]",
    "bounce.trace": "{r_role}的提交没写清对应的发现，退回",
    "bounce.review": "评审要改，打回{r_role}（第 {round} 轮评审）",
    # tests and checks
    "tests.score": "测试 {passed}/{total}[[green|：全绿]][[red|：实现还没写，全红]]",
    "tests.first_ok": "{r_role}的新测试在需求提交上都失败了，开发开工",
    "tests.after": "台架之后的检查 {passed}/{total}",
    "tests.rerun": "独立重跑：release.sh {verdict}[[differs|，和上一轮结果不同的检查：{differs}]]",
    "failed.checks": "检查要人决定：{why}",
    # the bench
    "bench.go": "检查都过了，评审放行：上台架（第 {n} 次），先跑 doctor.sh",
    "bench.deploy": "台架就绪，部署 {artifact}：等人在操作台上批准这个构建",
    "bench.replay": "部署好了，回放录制的行驶数据：等人在操作台上批准",
    "bench.replayed": "回放完了，跑台架之后的检查（{run_dir}）",
    "bench.rerun": "台架之后的检查都过了：在新的结果目录里从头重跑全部检查，再跑 release.sh",
    "failed.bench": "台架要人处理：{why}",
    "hold.restart": "app 重启时台架上的「{step}」还没做完：到操作台看动作记录、核对目标状态，再重试",
    "hold.no_artifact": "没有要部署的构建 {artifact}（build.sh 的产物）",
    "hold.not_ready": "台架没准备好：{why}",
    "hold.deploy": "部署没做成（{kind}）：{why}",
    "hold.replay": "回放没做成（{kind}）：{why}",
    "hold.after_bench": "台架之后的检查要人决定：{why}",
    "hold.release": "独立重跑后 release.sh 没通过：{why}",
    # review, gates and plans
    "review": "审查：[[summary|{summary}|没有给结论]]",
    "gate.wait": "等人批准：{g_gate}",
    "gate.after_talk": "等人批准：{g_gate}（讨论之后）",
    "gate.overrule": "等人决定{g_gate}：[[rounds|审查打回 {rounds} 轮后仍要改|审查要改]]，人可以再退回一轮，或写明理由推翻审查放行",
    "talk.gate": "人在{g_gate}关卡和{r_role}讨论：{note}",
    "talk.answer": "{r_role}回答：{answer}",
    "talk.failed": "{r_role}没有回答：{error}",
    "approved": "人批准了{g_gate}[[note|：{note}]]",
    "approved.overrule": "人推翻审查结论，批准了{g_gate}：{note}",
    "plan.split": "{r_role}提议分工：{plan}[[skip|；这次不要：{skip}]]",
    "plan.split.plan": "{r_role} · {what}",
    "plan.split.skip": "{r_role}（{why}）",
    "plan.no_split": "{r_role}没有提出分工（{file}），按团队配置派活",
    "plan.delivery": "{r_role}提议交付标签：{delivery}",
    "plan.no_delivery": "{r_role}没有提出交付标签（{file}），按团队配置：{delivery}",
    "plan.delivery_confirmed": "人确认交付标签：{delivery}",
    "plan.questions": "{r_role}列出 {n} 件要人决定的事",
    "plan.triage": "{r_role}的分诊：{n} 件要人决定，{listed} 条照分诊做（见分诊文档）",
    "plan.triage_approved": "分诊批准（{by}），记在 {file}（sha256 {sha}）",
    "plan.triage_base": "分诊的 base 定为开工时的运行分支 {base}：之后每个提交都要写发现编号",
    # the delivery details (flow.py): segments, their results and the moments
    "flow.agent": "{r_role} · {label}",
    "flow.agent.talk": "{r_role} · 讨论",
    "flow.agent.round": "{r_role} · 第 {n} 轮",
    "flow.gate": "等人批准 · {g_gate}",
    "flow.rerun": "独立重跑全部检查",
    "flow.checks": "检查 第 {n} 轮",
    "flow.after_bench": "台架之后的检查",
    "flow.check_fail": "检查不过：{checks}[[more|等]]",
    "flow.console": "操作台 · [[action|{action}|台架动作]]",
    "flow.signoff": "{by} 签字放行",
    "result.error": "出错",
    "result.approved": "批准",
    "result.sent_back": "退回",
    "result.refused": "拒绝",
    "result.timeout": "超时",
    "result.differs": "不同",
    "result.same": "一致",
    "result.fail": "不过",
    "result.pass": "通过",
    # why a run cannot be signed off yet
    "sign.not_ended": "运行结束以后才能签字",
    "sign.release": "独立重跑后 release.sh 没通过，不能签字放行：{why}",
    "sign.failed": "运行失败了，没有交付，不能签字放行（可以重试失败的角色）",
    "sign.stopped": "运行停下了，没有交付，不能签字放行",
    "sign.no_rerun": "还没有独立重跑和 release.sh 的结果，不能签字放行",
}

# The same in English: what GET /runs/<id>/audit?lang=en says (the board has these as ev.<code> in ui/src/i18n/en.json).
EN: dict[str, str] = {
    "run.start": "Run started: {title}",
    "run.stopped": "Run stopped",
    "run.error": "The run hit an error and stopped: {error}",
    "run.repo_failed": "Run failed: could not set up the repository: {error}",
    "run.tests_failed": "Run failed: the app cannot run the tests: {error}",
    "run.tests_first_failed": "Run failed: the app cannot run the tests on the request commit: {error}",
    "run.after_bench_failed": "Run failed: the app cannot run the post-bench checks: {error}",
    "run.ownership_failed": "Run failed: the division file {file} cannot be used: {error}",
    "run.review_rounds": "Run ended: [[rounds|review still asks for changes after {rounds} rounds sent back; handed to a person|review asks for changes]]",
    "run.done_red": "Run ended: review says [[summary|{summary}|nothing]], but {red} tests still fail; handed to a person",
    "run.done_ok": "Run complete: review says it can be delivered",
    "run.done": "Run complete[[verdict|: {verdict}]]",
    "run.held": "Run paused, handed to a person: {why}",
    "run.failed_roles": "Run failed: {r_roles} did not finish, so the roles after them cannot start",
    "retry.bench": "Retry: {by} lets the bench continue from \"{step}\"[[note| ({note})]]",
    "retry.review": "Retry: {by} sends the review's changes back[[note|, with the person's decisions: {note}]]",
    "retry.roles": "Retry: {r_roles}",
    "signoff": "{by} signed off[[note|: {note}]][[pr|; PR #{pr} merged into main ({merged})]]",
    "member.missing": "{r_role} has not started: member {member} is not on Crew's Agents page yet; it starts once added",
    "member.added": "Member {member} added, {r_role} starts",
    "handoff": "{r_from} hands [[outs|{outs}|its outputs]] to {r_role}",
    "spawned.dispatch": "Orchestrator dispatches: {r_role} · {task}[[again| ({again})]]",
    "spawned.start": "{r_role} starts[[again| ({again})]]",
    "spawned.round": "{r_role} round {n}: {label}[[again| ({again})]]",
    "tool": "{r_role}: {tool}",
    "committed": "{r_role} committed: {subject}",
    "committed.app": "The app committed {n} files for {r_role}",
    "violation": "{r_role} changed {path}, which is not its to change",
    "done": "{r_role} done[[summary|: {summary}]]",
    "merged": "{r_role}'s branch merged into the run branch",
    "conflict": "{r_role} merge conflict: {note}",
    "failed.nochange": "{r_role} made no changes in round {n}: [[summary|{summary}|no reason given]]",
    "failed.round": "{r_role} did not fix it in round {n}: {why}",
    "failed.role": "{r_role} failed: {why}",
    "skipped": "{r_role}: {why}[[globs|; the checks it owns ({globs}) are not run this time]]",
    "skipped.unneeded": "{r_role}: not needed in this project, skipped",
    "ownership": "Orchestrator dispatches per {r_from}'s division: {assigned}",
    "ownership.assigned": "{r_role} {files}",
    "finding.add": "{by} added {id} ({check} finding: {location}, {decision}) and gave it to {r_role}; writes [[paths|{paths}|unchanged]][[go_on|, run continues]][[note|: {note}]]",
    "finding.extend": "{by} added writable paths to {id} ({check} finding: {location}) for {r_role}; writes [[paths|{paths}|unchanged]][[go_on|, run continues]][[note|: {note}]]",
    "bounce.finding": "{ids} added by the owner: {cases} go back to {r_role} for one more round",
    "bounce.split": "Division file is wrong, sent back to {r_role}: {error}",
    "bounce.triage_format": "Triage file is malformed, sent back to {r_role}: {error}",
    "bounce.conflict": "Merge conflict, sent back to {r_role}",
    "bounce.tests": "{cases}[[more| and more]] failed, sent back to {r_role}",
    "bounce.tests_first": "Tests-first failed, sent back to {r_role}: {why}",
    "bounce.checks": "Checks {cases} failed, sent back to {r_role}",
    "bounce.test_writer": "{cases}[[more| and more]] failed; {r_owners} say the tests themselves are wrong, sent back to {r_role}",
    "bounce.triage_changed": "The person changed {n} decisions at the {g_gate} gate; sent back to {r_role} to apply them",
    "bounce.gate_review": "Sent back at the {g_gate} gate: one more round on the review's points[[note|: {note}]]",
    "bounce.gate": "Sent back at the {g_gate} gate: {note}",
    "bounce.by_person": "Sent back to {r_role} as the person asked",
    "bounce.rejected": "The person sent back {g_gate}: [[note|{note}|no reason given]]",
    "bounce.trace": "{r_role}'s commits do not name their findings; sent back",
    "bounce.review": "Review asks for changes, sent back to {r_role} (review round {round})",
    "tests.score": "Tests {passed}/{total}[[green|: all green]][[red|: nothing implemented yet, all red]]",
    "tests.first_ok": "{r_role}'s new tests all fail on the request commit; development starts",
    "tests.after": "Post-bench checks {passed}/{total}",
    "tests.rerun": "Independent rerun: release.sh {verdict}[[differs|; checks that differ from the last round: {differs}]]",
    "failed.checks": "Checks need a person's decision: {why}",
    "bench.go": "All checks passed and review cleared it: to the bench (time {n}), doctor.sh first",
    "bench.deploy": "Bench ready, deploying {artifact}: waiting for a person to approve this build on the console",
    "bench.replay": "Deployed; replaying the recorded drive data: waiting for a person's approval on the console",
    "bench.replayed": "Replay done; running the post-bench checks ({run_dir})",
    "bench.rerun": "Post-bench checks all passed: rerunning every check from scratch in a new results folder, then release.sh",
    "failed.bench": "The bench needs a person: {why}",
    "hold.restart": "The bench's \"{step}\" was not finished when the app restarted: check the action log and the target state on the console, then retry",
    "hold.no_artifact": "No build to deploy: {artifact} (the output of build.sh)",
    "hold.not_ready": "The bench is not ready: {why}",
    "hold.deploy": "Deploy did not succeed ({kind}): {why}",
    "hold.replay": "Replay did not succeed ({kind}): {why}",
    "hold.after_bench": "Post-bench checks need a person's decision: {why}",
    "hold.release": "release.sh did not pass on the independent rerun: {why}",
    "review": "Review: [[summary|{summary}|no verdict given]]",
    "gate.wait": "Waiting for approval: {g_gate}",
    "gate.after_talk": "Waiting for approval: {g_gate} (after the discussion)",
    "gate.overrule": "Waiting for a decision on {g_gate}: [[rounds|review still asks for changes after {rounds} rounds|review asks for changes]]; send it back once more, or overrule the review with a written reason",
    "talk.gate": "The person discusses with {r_role} at the {g_gate} gate: {note}",
    "talk.answer": "{r_role} answers: {answer}",
    "talk.failed": "{r_role} did not answer: {error}",
    "approved": "The person approved {g_gate}[[note|: {note}]]",
    "approved.overrule": "The person overruled the review and approved {g_gate}: {note}",
    "plan.split": "{r_role} proposes the division: {plan}[[skip|; not this time: {skip}]]",
    "plan.split.plan": "{r_role} · {what}",
    "plan.split.skip": "{r_role} ({why})",
    "plan.no_split": "{r_role} proposed no division ({file}); dispatching per the team file",
    "plan.delivery": "{r_role} proposes the delivery labels: {delivery}",
    "plan.no_delivery": "{r_role} proposed no delivery labels ({file}); per the team file: {delivery}",
    "plan.delivery_confirmed": "The person confirmed the delivery labels: {delivery}",
    "plan.questions": "{r_role} lists {n} things for a person to decide",
    "plan.triage": "{r_role}'s triage: {n} for a person to decide, {listed} done as triaged (see the triage document)",
    "plan.triage_approved": "Triage approved ({by}), recorded in {file} (sha256 {sha})",
    "plan.triage_base": "Triage base set to the run branch at kickoff, {base}: every commit from now on names its findings",
    "flow.agent": "{r_role} · {label}",
    "flow.agent.talk": "{r_role} · discussion",
    "flow.agent.round": "{r_role} · round {n}",
    "flow.gate": "Waiting for approval · {g_gate}",
    "flow.rerun": "Independent rerun of all checks",
    "flow.checks": "Checks round {n}",
    "flow.after_bench": "Post-bench checks",
    "flow.check_fail": "Checks failed: {checks}[[more| and more]]",
    "flow.console": "Console · [[action|{action}|bench action]]",
    "flow.signoff": "{by} signed off",
    "result.error": "error",
    "result.approved": "approved",
    "result.sent_back": "sent back",
    "result.refused": "refused",
    "result.timeout": "timed out",
    "result.differs": "differs",
    "result.same": "same",
    "result.fail": "failed",
    "result.pass": "passed",
    "sign.not_ended": "A run can be signed off only after it ends",
    "sign.release": "release.sh did not pass on the independent rerun, so it cannot be signed off: {why}",
    "sign.failed": "The run failed and delivered nothing, so it cannot be signed off (you can retry the failed roles)",
    "sign.stopped": "The run was stopped and delivered nothing, so it cannot be signed off",
    "sign.no_rerun": "There is no independent rerun and release.sh result yet, so it cannot be signed off",
}

TEMPLATES = {"zh": ZH, "en": EN}
SEPS = {"zh": ("、", "；"), "en": (", ", "; ")}  # a list, a list of objects
PARAM_MAX = 300  # a param is one line on the board, as the text is

_OPT = re.compile(r"\[\[(\w+)\|([^|\]]*)(?:\|([^\]]*))?\]\]")
_VAR = re.compile(r"\{(\w+)\}")


def clean(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """*params* as they are stored: strings on one line and cut to PARAM_MAX, None dropped."""
    def one(v: Any) -> Any:
        if isinstance(v, str):
            return " ".join(v.split())[:PARAM_MAX]
        if isinstance(v, (list, tuple)):
            return [one(x) for x in v][:40]
        if isinstance(v, dict):
            return {k: one(x) for k, x in v.items() if x is not None}
        return v
    return {k: one(v) for k, v in params.items() if v is not None} if params else None


def scrubbed(params: Any, scrub: Callable[[str], str]) -> Any:
    """*params* with every string in them (in lists and nested messages too) passed through *scrub*: the board says
    an event from its params in English, so they go out redacted as its text does."""
    if isinstance(params, str):
        return scrub(params)
    if isinstance(params, list):
        return [scrubbed(x, scrub) for x in params]
    if isinstance(params, dict):
        return {k: scrubbed(v, scrub) for k, v in params.items()}
    return params


def render(code: str, params: dict[str, Any] | None = None, title: Callable[[str], str] = str,
           gate: Callable[[str], str] | None = None, lang: str = "zh") -> str:
    """The text of *code* with *params* in *lang* (Chinese by default: the event's text); *title* and *gate* name a
    role key (as its name and its gate)."""
    template = TEMPLATES[lang][code]
    list_sep, item_sep = SEPS[lang]
    p = params or {}

    def value(name: str, v: Any) -> str:
        if isinstance(v, dict) and v.get("code") in ZH:  # a message inside a message: the reason the bench is held
            return render(v["code"], v.get("params"), title, gate, lang)
        if isinstance(v, list):
            if v and all(isinstance(x, dict) for x in v):
                return item_sep.join(render(f"{code}.{name}", x, title, gate, lang) for x in v)
            return list_sep.join(value(name, x) for x in v)
        if name.startswith("r_"):
            return title(str(v))
        if name.startswith("g_"):
            return (gate or title)(str(v))
        return str(v)

    def opt(m: re.Match[str]) -> str:
        return m.group(2) if p.get(m.group(1)) else (m.group(3) or "")

    text = _OPT.sub(opt, template)
    return _VAR.sub(lambda m: value(m.group(1), p[m.group(1)]) if m.group(1) in p else m.group(0), text)
