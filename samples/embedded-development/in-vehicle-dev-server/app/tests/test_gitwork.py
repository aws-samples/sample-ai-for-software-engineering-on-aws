"""Git for a run, against real git in a temp dir."""

import asyncio

from teamkit import mod, sh

gitwork, constants = mod("gitwork"), mod("constants")


def write(wt, rel, text):
    (wt / rel).parent.mkdir(parents=True, exist_ok=True)
    (wt / rel).write_text(text, encoding="utf-8")


def commit(wt, msg):
    sh(wt, "add", "-A")
    sh(wt, "commit", "-q", "-m", msg)


def test_globs():
    m = gitwork.matches
    assert m("docs/product/acceptance.md", ["docs/product/**"]) and m("docs/product/a/b.md", ["docs/product/**"])
    assert not m("docs/productx/a.md", ["docs/product/**"]) and not m("docs/product", ["docs/product/**"])
    assert m("Dockerfile", ["ops/**", "Dockerfile"]) and not m("backend/Dockerfile", ["Dockerfile"])
    assert m("tests/api-signup.test.js", ["tests/api-*"]) and not m("tests/sub/api-x.js", ["tests/api-*"])
    assert m("a/b/c.js", ["**/*.js"]) and m("c.js", ["**/*.js"]) and m("tests/x/y", ["tests/"])
    assert m(".dockerignore", [".dockerignore"]) and not m("x.dockerignore", [".dockerignore"]) and not m("a", [])


def test_the_requirement_replaces_only_its_section():
    readme = (constants.TARGET_TEMPLATE / "README.md").read_text(encoding="utf-8")
    out = gitwork.with_requirement(readme, "做一个读书会报名小站。")
    assert out.startswith("# 活动报名小站\n\n## 需求\n\n做一个读书会报名小站。\n\n## 约束\n")
    assert "让主办方发布活动" not in out and out.endswith(readme[readme.index("## 约束"):])
    assert gitwork.with_requirement("# x\n", "要求") == "# x\n\n## 需求\n\n要求\n"


def test_repo_worktrees_stats_leftovers_merge_and_conflict(tmp_path):
    async def go():
        root = tmp_path / "runs" / "r1"
        repo, run_wt, be, fe = root / "repo", root / "wt" / "_run", root / "wt" / "backend", root / "wt" / "frontend"
        base = await gitwork.create_repo(constants.TARGET_TEMPLATE, repo, "做一个读书会报名小站", "读书会")
        assert sh(repo, "log", "--format=%s").strip() == "需求：读书会" and "读书会报名小站" in (repo / "README.md").read_text()
        assert sh(repo, "config", "commit.gpgsign").strip() == "false"  # the agents' own commits never prompt
        assert await gitwork.create_repo(constants.TARGET_TEMPLATE, repo, "x", "x") == base  # made already: kept
        assert await gitwork.add_worktree(repo, run_wt, "team/r1/run", base) is True
        assert await gitwork.add_worktree(repo, run_wt, "team/r1/run", base) is False
        for wt, branch in ((be, "team/r1/backend"), (fe, "team/r1/frontend")):
            await gitwork.add_worktree(repo, wt, branch, base)

        write(be, "backend/server.js", "a\nb\nc\n")
        commit(be, "[backend] 接口")
        write(be, "backend/server.js", "a\nB\nc\nd\n")  # not committed
        write(be, "backend/store.js", "x\ny\n")  # untracked
        write(be, "README.md", "改了别人的\n")  # outside its area
        st = await gitwork.stats(be, base)
        files = {f["path"]: f for f in st["files"]}
        assert files["backend/server.js"] == {"path": "backend/server.js", "added": 4, "removed": 0, "status": "A"}
        assert files["backend/store.js"] == {"path": "backend/store.js", "added": 2, "removed": 0, "status": "A"}
        assert files["README.md"]["status"] == "M" and files["README.md"]["added"] == 1
        assert st["count"] == 3 and st["lines"]["added"] == 7 and st["paths"][0] == "README.md"  # biggest first
        assert [c["subject"] for c in st["commits"]] == ["[backend] 接口"] and st["commits"][0]["at"] > 0

        paths, sha = await gitwork.commit_leftovers(be, ["backend/**"], "backend")
        assert sorted(paths) == ["backend/server.js", "backend/store.js"] and sh(be, "rev-parse", "--short", "HEAD").strip() == sha
        assert sh(be, "status", "--porcelain").strip() == "M README.md"  # the out-of-area edit is left alone
        assert sh(be, "log", "-1", "--format=%s").strip() == "[backend] （app 代提交）"
        assert await gitwork.commit_leftovers(be, ["backend/**"], "backend") == ([], None)
        assert await gitwork.committed_paths(be, base) == ["backend/server.js", "backend/store.js"]

        write(fe, "backend/server.js", "前端顺手改的\n")
        write(fe, "frontend/index.html", "<h1/>\n")
        commit(fe, "[frontend] 页面")
        ok = await gitwork.merge(run_wt, "team/r1/backend", "[run] 合入后端")
        assert ok == {"ok": True, "conflicts": [], "note": None}
        assert await gitwork.merge(run_wt, "team/r1/backend", "again") == ok  # merged already: nothing happens
        assert sh(run_wt, "log", "-1", "--format=%s %P").startswith("[run] 合入后端 ")  # a real merge commit
        bad = await gitwork.merge(run_wt, "team/r1/frontend", "[run] 合入前端")
        assert bad == {"ok": False, "conflicts": ["backend/server.js"], "note": "backend/server.js"}
        assert sh(run_wt, "status", "--porcelain") == "" and await gitwork.merge_base(run_wt, "team/r1/frontend", "HEAD") == base

        write(run_wt, "data/test-run.json", "{}")  # what a test run may leave behind
        await gitwork.reset_clean(run_wt)
        assert not (run_wt / "data").exists()

    asyncio.run(go())


def test_kirocrew_host_paths_are_recognized():
    """KiroCrew writes .kiro/settings/cli.json into every agent's cwd: not counted, not committed, not a violation."""
    import asyncio
    from backend.team import gitwork

    assert gitwork.is_host_path(".kiro/settings/cli.json")
    assert not gitwork.is_host_path("docs/.kiro-notes.md")
    assert asyncio.run is not None


def test_a_glob_starting_with_an_exclamation_mark_leaves_out_what_it_matches():
    gitwork = mod("gitwork")
    globs = ["**", "!tests/**"]
    assert gitwork.matches("server/routes/people.js", globs) and gitwork.matches("README.md", globs)
    assert not gitwork.matches("tests/regress-a.test.js", globs) and not gitwork.matches("tests/enterprise/x.test.js", globs)
    assert not gitwork.matches("web/a.js", ["!web/**"])  # nothing to keep: nothing matches
