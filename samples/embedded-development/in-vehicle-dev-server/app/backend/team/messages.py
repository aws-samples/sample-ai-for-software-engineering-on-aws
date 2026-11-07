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

import functools
import json
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
    "approved.answers": "人批准了{g_gate}：[[note|{note}；]]决定：{answers}",
    "approved.answers.answers": "{id} 选 {choice}[[differs|（与建议不同）]]",
    "choice.other": "其他",
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
    # what a round is for (an attempt's label: the lanes, the graph, the delivery details)
    "label.fix": "修 {items}[[more|等]]",
    "label.conflict": "解决合入冲突",
    "label.review": "按评审意见改",
    "label.trace": "补写提交说明",
    "label.revise": "按意见重写",
    "label.discuss": "讨论",
    "label.again": "重新开工",
    "again.transient": "模型后端出错，换一个新会话接着做",
    # why the checks hold the run for a person: one item per check
    "checks.held": "{items}",
    "checks.held.items": "{check} {what}：{reason}",
    "held.usage": "检查配置错误",
    "held.blocked": "没法判定",
    "held.rounds": "修了 {n} 轮仍不过",
    "held.owner": "没过，负责的角色没法再改",
    # the triage gate's questions and options (triage.py)
    "triage.q.added": "{id} 是分诊新加的（{found_by}），定为 {decision}：{where}",
    "triage.q.justify": "{id} 分诊建议说明为误报或无害、不修[[label|（待办标的是 {label}）]]：{where}",
    "triage.q.defer": "{id} 分诊建议延后[[label|（待办标的是 {label}）]]：{where}",
    "triage.q.differs": "{id} 的决定和待办不同（待办标的是 {label}）：{decision}，{where}",
    "triage.opt.add": "同意加入本批",
    "triage.opt.no_add": "不同意：不加入（退回分诊）",
    "triage.opt.justify": "同意说明（评审还会复核引用）",
    "triage.opt.fix": "不同意：本批修复（退回分诊补齐证据和行为）",
    "triage.opt.defer": "同意延后",
    "triage.opt.agree": "同意",
    "triage.opt.disagree": "不同意（退回分诊）",
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
    "approved.answers": "The person approved {g_gate}: [[note|{note}; ]]decisions: {answers}",
    "approved.answers.answers": "{id} {choice}[[differs| (differs from the proposal)]]",
    "choice.other": "other",
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
    "label.fix": "fix {items}[[more| and more]]",
    "label.conflict": "resolve the merge conflict",
    "label.review": "change as the review says",
    "label.trace": "rewrite the commit messages",
    "label.revise": "redo as asked",
    "label.discuss": "discussion",
    "label.again": "start again",
    "again.transient": "the model backend failed; continuing in a new session",
    "checks.held": "{items}",
    "checks.held.items": "{check} {what}: {reason}",
    "held.usage": "is misconfigured",
    "held.blocked": "cannot be judged",
    "held.rounds": "still fails after {n} rounds",
    "held.owner": "failed, and the role that owns it can no longer change it",
    "triage.q.added": "{id} was added by triage ({found_by}), decided {decision}: {where}",
    "triage.q.justify": "{id}: triage proposes to explain it as a false positive or harmless, not fix it[[label| (the backlog says {label})]]: {where}",
    "triage.q.defer": "{id}: triage proposes to defer it[[label| (the backlog says {label})]]: {where}",
    "triage.q.differs": "{id}: the decision differs from the backlog (the backlog says {label}): {decision}, {where}",
    "triage.opt.add": "Agree to add it to this batch",
    "triage.opt.no_add": "Disagree: do not add it (send back to triage)",
    "triage.opt.justify": "Agree to explain it (the review still checks the citations)",
    "triage.opt.fix": "Disagree: fix it in this batch (send back to triage for evidence and behaviour)",
    "triage.opt.defer": "Agree to defer it",
    "triage.opt.agree": "Agree",
    "triage.opt.disagree": "Disagree (send back to triage)",
    "sign.not_ended": "A run can be signed off only after it ends",
    "sign.release": "release.sh did not pass on the independent rerun, so it cannot be signed off: {why}",
    "sign.failed": "The run failed and delivered nothing, so it cannot be signed off (you can retry the failed roles)",
    "sign.stopped": "The run was stopped and delivered nothing, so it cannot be signed off",
    "sign.no_rerun": "There is no independent rerun and release.sh result yet, so it cannot be signed off",
}

TEMPLATES = {"zh": ZH, "en": EN}
SEPS = {"zh": ("、", "；"), "en": (", ", "; ")}  # a list, a list of objects
LIST_JOINED = {"approved.answers.answers"}  # item templates whose items are joined like a plain list
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


_BOARD_BY = re.compile(r"^Kiro Crew 看板（(.+?)，(.+?)）$")  # a decision on the board at the bench (bench.py DECIDED_BY)
_VIA_KIRO = "（在 Kiro 会话里让 Kiro 代点）"  # a retry the person asked Kiro to click for them


def person(who: str, lang: str = "zh") -> str:
    """A record's person in *lang*: the app's own words around a name (负责人, the board, a click via Kiro) in English;
    the name as it is. The UI's i18n/events.ts person() says the same."""
    if lang != "en":
        return who
    if who == "负责人":
        return "Release owner"
    m = _BOARD_BY.match(who)
    if m:
        return f"Kiro Crew board ({m.group(1)}, {m.group(2)})"
    if who.endswith(_VIA_KIRO):
        return who[: -len(_VIA_KIRO)] + " (asked Kiro to click it in a Kiro session)"
    return who


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
                sep = list_sep if f"{code}.{name}" in LIST_JOINED else item_sep
                return sep.join(render(f"{code}.{name}", x, title, gate, lang) for x in v)
            return list_sep.join(value(name, x) for x in v)
        if name in ("by", "who") and isinstance(v, str):
            return person(v, lang)
        if name.startswith("r_"):
            return title(str(v))
        if name.startswith("g_"):
            return (gate or title)(str(v))
        return str(v)

    def opt(m: re.Match[str]) -> str:
        return m.group(2) if p.get(m.group(1)) else (m.group(3) or "")

    text = _OPT.sub(opt, template)
    return _VAR.sub(lambda m: value(m.group(1), p[m.group(1)]) if m.group(1) in p else m.group(0), text)


# --- reading older events: their Chinese text back into a code and params -------------------------------------- #
# A run recorded before events carried a code has only the text. infer() matches it against the Chinese templates
# (with the run's role names), so that the board can say it in English too. Nothing is written back.

_LISTS = {"outs", "paths", "cases", "ids", "globs", "checks", "differs", "files", "items", "r_roles", "r_owners"}
_NUMBERS = {"n", "rounds", "round", "red", "passed", "total", "listed", "pr"}
_NESTED = {("failed.bench", "why"): ("hold.",), ("run.held", "why"): ("hold.", "checks.held"),
           ("failed.checks", "why"): ("checks.held",), ("spawned.round", "label"): ("label.",),
           ("flow.agent", "label"): ("label.",), ("spawned.dispatch", "again"): ("again.",),
           ("spawned.start", "again"): ("again.",), ("spawned.round", "again"): ("again.",),
           ("checks.held.items", "what"): ("held.",), ("approved.answers.answers", "choice"): ("choice.",)}
_TOKEN = re.compile(r"\[\[(\w+)\|([^|\]]*)(?:\|([^\]]*))?\]\]|\{(\w+)\}")


def _alt(names: list[str]) -> str:
    return "|".join(re.escape(n) for n in sorted(set(names), key=len, reverse=True) if n) or "(?!)"


def _compile(template: str, titles: tuple[str, ...], gates: tuple[str, ...]) -> tuple[re.Pattern[str], list[tuple[str, str]], int]:
    """A template as a regex: each {name} a group (role names as alternatives of the run's titles or gate labels,
    numbers as digits), each [[name|then|else]] a choice; returns it, the groups (group, param or ?opt), and how
    many literal characters it has (the more, the better a match)."""
    groups: list[tuple[str, str]] = []
    literal = 0

    def var(name: str) -> str:
        g = f"g{len(groups)}"
        groups.append((g, name))
        role = _alt(list(titles)) if name.startswith("r_") else _alt(list(gates) + list(titles)) if name.startswith("g_") else ""
        if role and name in _LISTS:
            body = f"(?:{role})(?:、(?:{role}))*"
        elif role:
            body = f"(?:{role})"
        else:
            body = r"\d+" if name in _NUMBERS else r".*?"
        return f"(?P<{g}>{body})"

    def part(text: str) -> str:
        nonlocal literal
        out, at = [], 0
        for m in _TOKEN.finditer(text):
            out.append(re.escape(text[at:m.start()]))
            literal += m.start() - at
            out.append(var(m.group(4)) if m.group(4) else "")
            at = m.end()
        out.append(re.escape(text[at:]))
        literal += len(text) - at
        return "".join(out)

    out, at = [], 0
    for m in _TOKEN.finditer(template):
        out.append(part(template[at:m.start()]))
        if m.group(4):
            out.append(var(m.group(4)))
        else:
            g = f"g{len(groups)}"
            groups.append((g, "?" + m.group(1)))
            # the else part first: "[[outs|{outs}|产出]]" reads 产出 as no outputs, not as outputs named 产出
            out.append(f"(?:{part(m.group(3) or '')}|(?P<{g}>{part(m.group(2))}))" if m.group(3)
                       else f"(?:(?P<{g}>{part(m.group(2))})|)")
        at = m.end()
    out.append(part(template[at:]))
    return re.compile("".join(out), re.S), groups, literal


@functools.lru_cache(maxsize=64)
def _patterns(titles: tuple[str, ...], gates: tuple[str, ...]) -> list[tuple[str, re.Pattern[str], list[tuple[str, str]], int]]:
    out = [(code, *_compile(t, titles, gates)) for code, t in ZH.items()]
    return sorted(out, key=lambda x: -x[3])


Roles = tuple[tuple[str, str, str], ...]  # (key, title, gate label) of a run's roles


def _items() -> set[str]:
    """The item templates (plan.split.plan, checks.held.items …): matched only inside their list."""
    out = set()
    for code in ZH:
        parent, _, last = code.rpartition(".")
        if parent in ZH and ("{" + last + "}") in ZH[parent]:
            out.add(code)
    return out


def _value(code: str, name: str, raw: str, roles: Roles) -> Any:
    if name.startswith("r_"):
        by_title = {t: k for k, t, _ in roles}
        keys = [by_title.get(x, x) for x in raw.split("、")]
        return keys if name in _LISTS else keys[0]
    if name.startswith("g_"):
        return next((k for k, t, g in roles if raw in (g, t)), raw)
    if name in _NUMBERS:
        return int(raw)
    for prefix in _NESTED.get((code, name), ()):
        found = _match(raw, roles, prefix)
        if found:
            return {"code": found[0], "params": found[1]}
    sub = f"{code}.{name}"
    if sub in ZH:  # a list of objects, one message each
        parts, items = raw.split("、" if sub in LIST_JOINED else "；"), []
        for i, part in enumerate(parts):
            found = _match(part, roles, sub, exact=True)
            if found:
                items.append(found[1])
            elif i == len(parts) - 1 and items:
                break  # the text was cut there
            else:
                return raw
        return items
    if name in _LISTS:
        return [x for x in raw.split("、") if x]
    return raw


def kind_of(code: str) -> str:
    """The event kind a code is emitted as ('' for the templates that are no event's: labels, reasons, segments)."""
    head = code.split(".")[0]
    if head in ("flow", "result", "sign", "label", "again", "checks", "held", "hold", "choice", "triage"):
        return ""
    return {"retry": "run"}.get(head, head)


def _match(text: str, roles: Roles, prefix: str = "", exact: bool = False, kind: str = "") -> tuple[str, dict[str, Any]] | None:
    """The best template for *text*: among those starting with *prefix* (exactly *prefix* with *exact*) and emitted
    as *kind*, the matching one with the most literal characters; item templates only as items."""
    titles = tuple(t for _, t, _ in roles)
    gates = tuple(g for _, _, g in roles if g)
    items = _ITEMS
    for code, rx, groups, _ in _patterns(titles, gates):
        if (exact and code != prefix) or (not exact and (not code.startswith(prefix) or code in items)):
            continue
        if kind and kind_of(code) != kind:
            continue
        m = rx.fullmatch(text)
        if not m:
            continue
        params: dict[str, Any] = {}
        for g, name in groups:  # the values first, then whether each optional part was there
            raw = m.group(g)
            if not name.startswith("?") and raw is not None and name not in params:
                params[name] = _value(code, name, raw, roles)
        for g, name in groups:
            if name.startswith("?"):
                params.setdefault(name[1:], m.group(g) is not None)
        return code, {k: v for k, v in params.items() if v is not False and v is not None and v != "" and v != []}
    return None


def infer(text: str, roles: list[dict[str, Any]], kind: str) -> tuple[str, dict[str, Any]] | None:
    """The code and params of an event of *kind* recorded with its Chinese text only, or None when no template of
    that kind says it."""
    key: Roles = tuple((str(r["key"]), str(r.get("title") or r["key"]), str(r.get("gate_label") or "")) for r in roles)
    text = " ".join(str(text or "").split())
    return _infer(text, key, kind) if text and kind else None


@functools.lru_cache(maxsize=8192)
def _infer(text: str, roles: Roles, kind: str) -> tuple[str, dict[str, Any]] | None:
    found = _match(text, roles, kind=kind)
    return (found[0], json.loads(json.dumps(found[1]))) if found else None


def with_codes(events: list[dict[str, Any]], roles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """*events* as the board reads them: one recorded without a code gets the one its text says, if any (a copy;
    the record is not changed)."""
    out = []
    for e in events:
        if e.get("code") or not e.get("text"):
            out.append(e)
            continue
        found = infer(str(e["text"]), roles, str(e.get("kind") or ""))
        out.append({**e, "code": found[0], "params": json.loads(json.dumps(found[1]))} if found else e)
    return out


def label_of(label: Any) -> dict[str, Any] | None:
    """An attempt's label (its Chinese words) as a message, for the board in English."""
    found = _match(" ".join(str(label or "").split()), (), "label.") if label else None
    return {"code": found[0], "params": found[1]} if found else None


_ITEMS = _items()


def as_msg(text: Any, prefix: str) -> Any:
    """*text* as a message of a template starting with *prefix* when one says it, else *text* as it is."""
    if not isinstance(text, str) or not text:
        return text
    found = _match(" ".join(text.split()), (), prefix)
    return {"code": found[0], "params": found[1]} if found else text


# The params that hold what people, agents and tools wrote (and the requirement): never translated. The tests take
# them out before they look for Chinese in an English event.
FREE_TEXT = {"title", "summary", "task", "subject", "note", "answer", "tool", "reason", "error", "why", "by",
             "what", "path", "location", "outs", "files", "paths", "found_by", "where"}
