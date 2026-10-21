"""demo 分支：接手一个已有项目，以及测试墙上的四类检查（功能 / 安全 / 合规 / 上架）."""

import asyncio

from teamkit import OUTPUTS, FakeManager, act, default_tests, drive, finish, make_run, mini_team, mod, sh

gitwork, checks, constants = mod("gitwork"), mod("checks"), mod("constants")


def test_case_ids_of_the_four_groups_sort_by_group_then_number():
    ids = ["STORE-2", "AC-10", "SEC-1", None, "COMP-3", "AC-2", "STORE-1"]
    assert sorted(ids, key=checks.case_order) == ["AC-2", "AC-10", "SEC-1", "COMP-3", "STORE-1", "STORE-2", None]
    assert checks.AC_RE.match("STORE-7 账号可在 App 外删除").group(1) == "STORE-7"
    assert checks.AC_RE.match("SEC-1 日志里没有手机号明文").group(1) == "SEC-1"
    assert checks.AC_RE.match("XYZ-1 别的前缀") is None


def test_an_existing_project_keeps_its_title_and_is_committed_as_taken_over(tmp_path):
    src = tmp_path / "im"
    (src / "server").mkdir(parents=True)
    (src / "README.md").write_text("# 我们的 IM\n\n介绍\n", encoding="utf-8")
    (src / "server" / "app.js").write_text("// server\n", encoding="utf-8")
    (src / "node_modules").mkdir()
    (src / "node_modules" / "x.js").write_text("", encoding="utf-8")

    async def go():
        repo = tmp_path / "runs" / "r1" / "repo"
        base = await gitwork.create_repo(src, repo, "加上账号注销", "加上账号注销", existing=True)
        return repo, base

    repo, base = asyncio.run(go())
    readme = (repo / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# 我们的 IM\n") and readme.rstrip().endswith("## 需求\n\n加上账号注销")
    assert (repo / "server" / "app.js").exists() and not (repo / "node_modules").exists()
    assert sh(repo, "log", "-1", "--format=%s").strip() == "接手：加上账号注销"
    assert len(base) == 40


def test_a_review_names_who_fixes_what():
    roles = mod("team").load_team(constants.TEAM_DIR / "team-aidlc.json")["roles"]
    targets = mod("team").review_targets
    text = ("**1. 文件鉴权能被绕过**（归后端）\n**2. 注销不是真删除**（归后端，文案归前端、移动端和体验设计）\n"
            "- 检查也有漏洞（归合规）\n**3. 拍照入口没了**（归移动端）")
    assert targets(text, roles) == ["designer", "compliance", "backend", "frontend", "mobile"]
    assert targets("DONE: 要改\n打回：backend、安卓\n（归运维）", roles) == ["backend", "mobile"]  # its own line wins
    assert targets("要改：没说归谁", roles) == [] and targets("（归评审）", roles) == []  # the reviewer writes nothing
    # one 打回 line per role, as list items (r10135470: the second one alone was read, then neither)
    review = ("DONE: 要改：后端用转义绕过检查\n\n### F-1\n- 怎么改：…\n- 打回：测试（改 `tests/ac-server-password.test.js:165` 的正则）\n"
              "- 打回：后端（删掉 `sendCheck` 的转义）\n")
    assert targets(review, roles) == ["tester", "backend"]
    assert targets("1. 打回：网页\n2. **打回**：后端", roles) == ["backend", "frontend"]


def _review_flow(tmp_path, verdicts, limit):
    team = mini_team()
    team["defaults"]["max_review_rounds"] = limit
    reviews, fixes = [], []

    async def go():
        mgr = FakeManager()
        run = make_run(tmp_path, mgr, default_tests(), team=team, requirement="小需求")
        said = iter(verdicts)

        def behave(a, role):
            if role == "reviewer":
                reviews.append(a.task)
                verdict = next(said)
                a.result, a.done = f"核对了全部改动。\n\nDONE: {verdict}", True  # a session's reply is whole
            elif "评审意见原文" in a.task:
                fixes.append(role)
                act(a, {"backend/server.js": f"// v2 校验邮箱 {len(fixes)}\n"})
                finish(a, "按评审改好了")
            else:
                act(a, OUTPUTS[role])
                finish(a)

        await drive(run, mgr, behave)
        return run, mgr

    run, mgr = asyncio.run(go())
    return run, mgr, reviews, fixes


def test_a_review_that_says_change_it_goes_back_to_the_named_roles_and_is_looked_at_again(tmp_path):
    run, mgr, reviews, fixes = _review_flow(tmp_path, ["要改：一条\n\n1. 邮箱没校验（归后端）", "可以交付"], limit=2)
    assert fixes == ["backend"] and run.s["status"] == "done" and run.s["review_rounds"] == 1
    fix = run.lane("backend")["attempts"][-1]
    assert fix["kind"] == "review" and fix["via"] == "continue" and "邮箱没校验（归后端）" in fix["task"]
    assert any(e["kind"] == "bounce" and e["text"] == "评审要改，打回后端（第 1 轮评审）" for e in run.events)
    assert "这是第 2 轮评审" in reviews[1] and "邮箱没校验" in reviews[1]  # the reviewer checks its own list again
    assert [e["text"] for e in run.events if e["kind"] == "run"][-1] == "运行完成：审查说可以交付"


def test_after_its_rounds_a_review_that_still_says_change_it_goes_to_a_person(tmp_path):
    run, _, reviews, fixes = _review_flow(tmp_path, ["要改：一（归后端）", "要改：二（归后端）"], limit=1)
    assert fixes == ["backend"] and len(reviews) == 2 and run.s["status"] == "failed"
    assert [e["text"] for e in run.events if e["kind"] == "run"][-1] == "运行结束：评审打回 1 轮后仍要改，交给人决定"

    async def again():  # the person's 重试 sends the last review back once more, with their decisions
        return await run.retry(note="拍照：补回系统拍照入口")

    assert asyncio.run(again()) == ["backend"] and run.s["status"] == "fixing" and run.s["review_rounds"] == 2
    task = run.lane("backend")["attempts"][-1]["task"]
    assert "人已经定了" in task and "拍照：补回系统拍照入口" in task and "要改：二（归后端）" in task
