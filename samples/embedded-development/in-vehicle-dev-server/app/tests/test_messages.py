"""What the app says by code (backend/team/messages.py): every code the backend uses has a Chinese and an English
template with the same params, the board's dictionaries (ui/src/i18n) hold the same templates, every code renders
in both languages from its params, and the audit trail speaks English on ?lang=en while an older event without a
code keeps its Chinese text."""

import json
import re

from teamkit import ROOT, mod

messages, audit = mod("messages"), mod("audit")
BACKEND = ROOT / "backend" / "team"
I18N = ROOT / "ui" / "src" / "i18n"
PARAM = re.compile(r"\{(\w+)\}")
OPT = re.compile(r"\[\[(\w+)\|")


def names(template: str) -> set[str]:
    return set(PARAM.findall(template)) | set(OPT.findall(template))


def used_codes() -> set[str]:
    """The codes the backend passes (messages.py aside): the first string of say("kind", "code", …), of _end(…, "code"),
    _bench_hold("code", …), code="…", flow.py's say("code"); and every other literal that is a template's code (the
    other branch of a choice, ``"talk.failed" if failed else "talk.answer"``), and the result.* codes of flow.py."""
    out: set[str] = set()
    for f in BACKEND.glob("*.py"):
        if f.name == "messages.py":
            continue
        text = f.read_text(encoding="utf-8")
        out |= set(re.findall(r'\.say\("\w+",\s*"([\w.]+)"', text))
        out |= set(re.findall(r'_end\("\w+",\s*"([\w.]+)"', text))
        out |= set(re.findall(r'_bench_hold\("([\w.]+)"', text))
        out |= set(re.findall(r'code="([\w.]+)"', text))
        out |= set(re.findall(r'"([a-z_]+(?:\.[a-z_]+)+)"', text)) & set(messages.ZH)
        if f.name == "flow.py":
            out |= set(re.findall(r'\bsay\("([\w.]+)"', text))
            out |= {f"result.{r}" for r in re.findall(r'"(error|approved|sent_back|refused|timeout|differs|same|fail|pass)"', text)}
    return out


def sample(template: str) -> dict:
    """A value for each param of *template*: role keys for r_/g_, a list for list-ish names, text otherwise."""
    out: dict = {}
    for n in names(template):
        out[n] = "dev-fix" if n.startswith(("r_", "g_")) else 3 if n in ("n", "rounds", "round", "red", "passed", "total", "listed", "pr") else f"<{n}>"
    for n in ("r_roles", "r_owners", "cases", "ids", "outs", "paths", "globs", "checks", "differs", "files"):
        if n in out:
            out[n] = ["dev-fix", "reviewer"] if n.startswith("r_") else ["a", "b"]
    return out


def test_every_code_has_both_languages_with_the_same_params():
    assert set(messages.ZH) == set(messages.EN)
    for code, zh in messages.ZH.items():
        assert names(zh) == names(messages.EN[code]), code


def test_every_code_the_backend_uses_exists_and_every_template_is_used():
    used = used_codes()
    assert used - set(messages.ZH) == set(), "codes without a template"
    # a list param's item template (plan.split.plan, ownership.assigned): <code>.<one of its params>
    subs = {c for c in messages.ZH if "." in c and (p := c.rsplit(".", 1))[0] in messages.ZH and p[1] in names(messages.ZH[p[0]])}
    assert set(messages.ZH) - used - subs == set(), "templates no code uses"


def test_the_boards_dictionaries_hold_the_same_templates():
    for lang, templates in (("zh", messages.ZH), ("en", messages.EN)):
        d = json.loads((I18N / f"{lang}.json").read_text(encoding="utf-8"))
        ev = {k[3:]: v for k, v in d.items() if k.startswith("ev.") and not k.startswith("ev.sep.")}
        assert ev == templates, lang


def test_every_code_renders_in_both_languages_from_its_params():
    title = {"dev-fix": "开发 · 修复", "reviewer": "评审"}.get
    title_en = {"dev-fix": "Developer · fix", "reviewer": "Reviewer"}.get
    for code, zh in messages.ZH.items():
        p = sample(zh)
        if code == "failed.bench":
            p["why"] = {"code": "hold.restart", "params": {"step": "deploy"}}
        for lang, name in (("zh", title), ("en", title_en)):
            text = messages.render(code, p, lambda k: name(k) or k, lambda k: name(k) or k, lang)
            assert text and not re.search(r"\{\w+\}|\[\[|\]\]", text), (code, lang, text)
            if lang == "en":
                assert not re.search(r"[\u4e00-\u9fff]", text), (code, text)
    # the optional parts: shown with the param, the else branch without it
    assert messages.render("done", {"r_role": "x", "summary": ""}, str) == "x完成"
    assert messages.render("review", {"summary": None}, lang="en") == "Review: no verdict given"
    assert messages.render("handoff", {"r_from": "a", "outs": ["x.md", "y.md"], "r_role": "b"}, lang="en") == "a hands x.md, y.md to b"


def test_params_are_one_line_and_bounded():
    p = messages.clean({"note": "a\n  b" + "x" * 400, "gone": None, "list": ["p\nq"], "obj": {"k": "v\nw", "n": None}})
    assert p == {"note": ("a b" + "x" * 400)[:messages.PARAM_MAX], "list": ["p q"], "obj": {"k": "v w"}}


def test_the_audit_trail_in_english_and_an_older_event_without_a_code():
    s = {"id": "r1", "title": "t", "status": "done", "team": {"name": "T", "roles": [
        {"key": "triage", "title": "分诊", "title_en": "Triage", "gate_label": "分诊", "gate_label_en": "Triage"}]}}
    events = [
        {"seq": 1, "at": 1.0, "kind": "gate", "role": "triage", "text": "等人批准：分诊", "from": "triage", "to": "person",
         "code": "gate.wait", "params": {"g_gate": "triage"}},
        {"seq": 2, "at": 2.0, "kind": "approved", "role": "triage", "text": "人批准了分诊：好", "from": "person", "to": "triage",
         "code": "approved", "params": {"g_gate": "triage", "note": "好"}},
        {"seq": 3, "at": 3.0, "kind": "done", "role": "triage", "text": "分诊完成：旧的记录", "from": None, "to": None},
    ]
    zh = audit.build(s, events, [])
    en = audit.build(s, events, [], "en")
    assert [x["what"] for x in zh["entries"]] == ["关卡打开，等人批准：分诊", "人批准了分诊：好", "分诊完成：旧的记录"]
    assert [x["what"] for x in en["entries"]] == ["Gate opened: Waiting for approval: Triage", "The person approved Triage: 好",
                                                   "分诊完成：旧的记录"]
    assert [x["who"] for x in en["entries"]] == ["app", "owner", "Triage"]
    md = audit.markdown(en, "en")
    assert md.startswith("# Audit trail · r1") and "| Time (UTC) | Who | What | Evidence |" in md and "## Gate: triage" in md
    assert audit.markdown(zh).startswith("# 审计记录 · r1")  # the audit.md written at sign-off: Chinese, as before
