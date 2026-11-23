"""Commit sizes (D18): each commit's changed, moved and not-moved lines, against real git in a temp dir."""

import asyncio
import json

from teamkit import FakeManager, make_run, mini_team, mod, sh

commits, scorecard = mod("commits"), mod("scorecard")

# git marks a block as moved only with at least 20 letters or digits in it: these lines have plenty
BLOCK_A = "".join(f"    int signal_value_{i} = decode_signal_from_frame(frame, {i});\n" for i in range(6))
BLOCK_B = "".join(f"    publish_signal_to_clients(table, \"vehicle.speed.{i}\", value_{i});\n" for i in range(4))


def write(wt, rel, text):
    (wt / rel).parent.mkdir(parents=True, exist_ok=True)
    (wt / rel).write_text(text, encoding="utf-8")


def commit(wt, msg):
    sh(wt, "add", "-A")
    sh(wt, "commit", "-q", "-m", msg)
    return sh(wt, "rev-parse", "--short=7", "HEAD").strip()


def repo(tmp):
    """base; a pure move; a move with two changed lines; an app commit; a leftover the app committed; a merge."""
    wt = tmp / "repo"
    wt.mkdir()
    sh(wt, "init", "-q", "-b", "main")
    write(wt, "src/service.cpp", "void run() {\n" + BLOCK_A + BLOCK_B + "}\n")
    base = commit(wt, "需求：拆分")
    write(wt, "src/service.cpp", "void run() {\n    decode();\n" + BLOCK_B + "}\n")
    write(wt, "src/decode.cpp", "void decode() {\n" + BLOCK_A + "}\n")
    moved = commit(wt, "[dev-refactor] F-031 搬移：decode()")
    write(wt, "src/service.cpp", "void run() {\n    decode();\n}\n")
    write(wt, "src/decode.cpp", "void decode() {\n" + BLOCK_A + "    ++decoded_frames;\n}\n")
    write(wt, "src/publish.cpp", "void publish() {\n" + BLOCK_B + "    ++published;\n}\n")
    changed = commit(wt, "[dev-refactor] F-031、F-023 修改：计数，publish() 搬出去")
    write(wt, "docs/decisions.md", "人批准了\n")
    commit(wt, "[run] 人在关卡上的决定")
    write(wt, "src/left.cpp", "int x;\n")
    commit(wt, "[dev-fix] （app 代提交）")
    sh(wt, "checkout", "-q", "-b", "side")
    write(wt, "src/side.cpp", "int y;\n")
    side = commit(wt, "[dev-fix] F-004 side")
    sh(wt, "checkout", "-q", "main")
    sh(wt, "merge", "-q", "--no-ff", "-m", "[run] 合入开发 · 修复（第 1 轮）", "side")
    return wt, base, moved, changed, side


def test_moved_lines_and_what_is_not_counted(tmp_path):
    wt, base, moved, changed, side = repo(tmp_path)
    got = asyncio.run(commits.measure(wt, base, "HEAD"))
    rows = {c["sha"]: c for c in got["commits"]}
    assert list(rows) == [moved, changed, side]  # oldest first; the merge commit is not one of them
    # pure move: BLOCK_A out of run() into decode.cpp (6 + 6); the new function's signature, braces and call are not
    size = lambda sha: tuple(rows[sha][k] for k in ("files", "lines", "moved", "not_moved"))  # noqa: E731
    assert size(moved) == (2, 15, 12, 3)
    assert rows[moved]["role"] == "dev-refactor" and rows[moved]["findings"] == ["F-031"]
    # move and change: BLOCK_B into publish.cpp (4 + 4), its function's three lines and one counter in decode()
    assert size(changed) == (3, 12, 8, 4) and rows[changed]["findings"] == ["F-031", "F-023"]
    assert rows[side]["findings"] == ["F-004"] and rows[side]["role"] == "dev-fix"
    # the app's own commits are listed apart, the leftover one recognised before its role tag is read
    assert [a["subject"] for a in got["app"]] == ["[run] 人在关卡上的决定", "[dev-fix] （app 代提交）"]


def test_kept_until_head_moves_and_the_summary(tmp_path):
    wt, base, moved, changed, side = repo(tmp_path)
    results = tmp_path / "results"
    first = asyncio.run(commits.ensure(results, wt, base))
    kept = json.loads((results / commits.FILE).read_text(encoding="utf-8"))
    assert kept["head"] == sh(wt, "rev-parse", "HEAD").strip() and len(kept["commits"]) == 3
    kept["commits"] = kept["commits"][:1]  # the kept file is what is read while HEAD stays
    (results / commits.FILE).write_text(json.dumps(kept), encoding="utf-8")
    assert len(asyncio.run(commits.ensure(results, wt, base))["commits"]) == 1
    write(wt, "src/more.cpp", "int z;\n")
    commit(wt, "[dev-fix] F-005 more")
    again = asyncio.run(commits.ensure(results, wt, base))
    assert len(again["commits"]) == 4 and again["head"] != first["head"]
    assert asyncio.run(commits.ensure(results, wt, base, moving=False)) == again  # an ended run keeps what it has
    big = max(again["commits"], key=lambda c: c["not_moved"])
    v = sorted(c["not_moved"] for c in again["commits"])
    assert commits.summary(again) == {"commits": 4, "max_not_moved": big["not_moved"],
                                      "median_not_moved": (v[1] + v[2]) / 2, "max_sha": big["sha"]}
    assert commits.summary(None) is None and commits.summary({"commits": []}) is None


def test_the_run_measures_its_commits_the_reviewer_gets_the_table_and_an_imported_run_has_none(tmp_path):
    run = make_run(tmp_path, FakeManager(), team=mini_team())
    asyncio.run(run._setup())
    wt = tmp_path / "work" / "runs" / run.rid / "wt" / "_run"
    assert str(wt) == run.s["run_wt"]
    write(wt, "backend/server.js", "// v2\n")
    sha = commit(wt, "[backend] F-001 v2")
    got = asyncio.run(run.commit_sizes())
    assert [c["sha"] for c in got["commits"]] == [sha]
    assert commits.load(tmp_path / "work" / "runs" / run.rid / "results") == got
    task = run._work_task("reviewer", 1, got)
    assert f"| {sha} | backend | F-001 | 1 | 1 | 0 | 1 | [backend] F-001 v2 |" in task
    assert "| 提交 |" not in run._work_task("reviewer", 1, None)
    row = scorecard.run_figures(run.s, [], [])
    assert row["commit_sizes"] == {"commits": 1, "max_not_moved": 1, "median_not_moved": 1, "max_sha": sha}
    run.s["imported"] = {"from": "alice"}
    assert asyncio.run(run.commit_sizes()) is None
    assert scorecard.run_figures(run.s, [], [])["commit_sizes"] is None
