#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Model Evaluation Diagnostic — local health-check for answer-quality
governance: does the project measure whether its AI is actually right?

Read-only survey. Report contains NO secret values and NO file contents.

Usage:
    python eval_diagnose.py [project_dir] [--output DIR] [--json]
    python eval_diagnose.py [project_dir] --compare OLD_REPORT.json
"""
import argparse
import json
import os
import re
import subprocess
import sys

TOOL_VERSION = "1.0.0"
SCHEMA_VERSION = 2
SEV_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3}

SELF_FIX_HOURS = {
    "EV-NO-STACK": 0, "EV-STACK-OK": 0,
    "EV-NO-EVAL-SET": 4, "EV-NO-REGRESSION-TEST": 3,
    "EV-NO-HALLUCINATION-CHECK": 4, "EV-NO-VERSION-PIN": 1,
    "EV-NO-HUMAN-REVIEW": 2, "EV-NO-A-B": 3,
}


def fix_hours(fid):
    return SELF_FIX_HOURS.get(fid.split(":", 1)[0], 0)


def finding(fid, severity, title, detail="", advice=""):
    return {"id": fid, "severity": severity, "title": title,
            "detail": detail, "advice": advice, "self_fix_hours": fix_hours(fid)}


def safe_read(path, limit=200_000):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except Exception:
        return ""


def walk_files(root, depth=2, max_files=2000):
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv",
            "site-packages", "dist-info", ".cache", "data", "logs"}
    count = 0
    root_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        if dirpath.rstrip(os.sep).count(os.sep) - root_depth >= depth:
            dirnames[:] = []
        for name in filenames:
            yield os.path.join(dirpath, name)
            count += 1
            if count >= max_files:
                return


CODE_EXTS = (".py", ".js", ".ts")
DATA_EXTS = (".json", ".jsonl", ".csv", ".yaml", ".yml")

MODEL_CALL_RE = re.compile(
    r"(chat\.completions\.create|messages\.create|generate_content|"
    r"ChatCompletion|invoke\(|\.generate\()", re.IGNORECASE)
EVAL_FRAMEWORK_RE = re.compile(
    r"(ragas|deepeval|promptfoo|evalplus|lm_eval|lighteval|"
    r"truera|uptrain|phoenix|arize|braintrust|langsmith.*eval|"
    r"evaluate\()", re.IGNORECASE)
EVAL_SET_HINT_RE = re.compile(
    r"(eval(uation)?[_ -]?(set|cases?|data|samples?)|golden[_ -]?(set|qa|answers?)|"
    r"test[_ -]?cases?\.json|expected[_ -](output|answer)|ground[_ -]?truth)",
    re.IGNORECASE)
REGRESSION_RE = re.compile(
    r"(regression|\.github/workflows|gitlab-ci|jenkinsfile|"
    r"pre-commit|pytest|jest|vitest)", re.IGNORECASE)
HALLUCINATION_RE = re.compile(
    r"(hallucinat|factuality|faithfulness|groundedness|"
    r"answer[_ -]?correctness|事实性|幻觉)", re.IGNORECASE)
HUMAN_REVIEW_RE = re.compile(
    r"(human[_ -]?review|manual[_ -]?review|annotation|reviewer|"
    r"spot[_ -]?check|抽检|人工(审核|复核))", re.IGNORECASE)
MODEL_NAME_RE = re.compile(
    r"""model\s*[=:]\s*['"]([^'"]+)['"]""", re.IGNORECASE)
PIN_HINT_RE = re.compile(
    r"(gpt-4|gpt-3\.5|claude|gemini|deepseek|qwen|glm|moonshot|"
    r"-latest|-preview|-\d{4,})", re.IGNORECASE)
AB_RE = re.compile(
    r"(a/b|ab[_ -]?test|shadow|canary|champion[_ -]?challenger|"
    r"experiment|variant)", re.IGNORECASE)


def pip_packages():
    pkgs = set()
    try:
        out = subprocess.run([sys.executable, "-m", "pip", "list", "--format=freeze"],
                             capture_output=True, text=True, timeout=60)
        for line in out.stdout.splitlines():
            if "==" in line:
                pkgs.add(line.split("==", 1)[0].strip().lower())
    except Exception:
        pass
    return pkgs


def check_stack(project_dir, pip):
    findings, facts = [], {}
    has_client = bool(pip & {"openai", "anthropic", "dashscope", "litellm",
                             "cohere", "google-generativeai"})
    code_files = []
    for fp in walk_files(project_dir, depth=2):
        if not fp.endswith(CODE_EXTS):
            continue
        text = safe_read(fp, 100_000)
        if not text:
            continue
        code_files.append(fp)
        if MODEL_CALL_RE.search(text):
            has_client = True
    facts["llm_stack_detected"] = has_client
    facts["code_files_scanned"] = len(code_files)
    if not has_client:
        findings.append(finding(
            "EV-NO-STACK", "info",
            "No model-calling code detected in this directory",
            "No model API call patterns found in scanned files.",
            "If your agents run elsewhere, run this tool there too — one "
            "report per deployment."))
    else:
        findings.append(finding(
            "EV-STACK-OK", "info",
            "Model-calling code detected",
            "%d code file(s) scanned." % len(code_files),
            "Answer quality is a property of the whole system — evaluate it "
            "end to end, not per prompt."))
    return findings, facts, code_files


def check_eval_set(project_dir, code_files):
    findings, facts = [], {}
    eval_files = []
    for fp in walk_files(project_dir, depth=3):
        if not fp.endswith(DATA_EXTS):
            continue
        text = safe_read(fp, 100_000)
        if text and EVAL_SET_HINT_RE.search(text):
            eval_files.append(os.path.relpath(fp, project_dir))
    has_framework = bool(pip_packages() & {"ragas", "deepeval", "promptfoo"})
    facts["eval_set_files"] = eval_files[:10]
    if eval_files or has_framework:
        findings.append(finding(
            "EV-NO-EVAL-SET", "info",
            "Evaluation set detected",
            "Eval-like data files: %s; framework: %s." % (
                ", ".join(eval_files[:5]) or "none",
                "yes" if has_framework else "no"),
            "Keep the set versioned and growing — every real failure you "
            "meet in production should become a case in it."))
    else:
        findings.append(finding(
            "EV-NO-EVAL-SET", "high",
            "No evaluation set found for a model-calling project",
            "No eval/golden/test-case data files and no evaluation framework "
            "detected. Prompt or model changes ship with zero quality "
            "measurement — regressions reach users unnoticed.",
            "Build a golden set of 30-50 real business questions with "
            "known-correct answers. Run it after every prompt, model or "
            "retrieval change. Without it, every release is a guess."))
    return findings, facts


def check_regression(project_dir, code_files):
    findings, facts = [], {}
    has_ci = any(REGRESSION_RE.search(safe_read(fp, 100_000))
                 for fp in code_files)
    ci_dir = os.path.join(project_dir, ".github", "workflows")
    has_ci = has_ci or os.path.isdir(ci_dir)
    facts["ci_or_regression_tests_found"] = has_ci
    if has_ci:
        findings.append(finding(
            "EV-NO-REGRESSION-TEST", "info",
            "CI or regression-test infrastructure detected",
            "CI config or test framework found.",
            "Wire the golden-set evaluation into CI so a quality drop fails "
            "the build, not the user."))
    else:
        findings.append(finding(
            "EV-NO-REGRESSION-TEST", "medium",
            "No CI or regression tests for answer quality",
            "No CI config or test framework detected. Nothing automatically "
            "re-checks answer quality when prompts, models or retrieval "
            "change.",
            "Add a scheduled or pre-deploy job that runs the golden set and "
            "fails on score drop. Quality regressions should be caught by "
            "machines, not by angry users."))
    return findings, facts


def check_hallucination(project_dir, code_files):
    findings, facts = [], {}
    has_check = any(HALLUCINATION_RE.search(safe_read(fp, 100_000))
                    for fp in code_files)
    facts["factuality_check_found"] = has_check
    if has_check:
        findings.append(finding(
            "EV-NO-HALLUCINATION-CHECK", "info",
            "Factuality/faithfulness checking detected",
            "Hallucination or groundedness checks found in the project.",
            "Sample from production traffic weekly — offline checks drift "
            "from what users actually ask."))
    else:
        findings.append(finding(
            "EV-NO-HALLUCINATION-CHECK", "medium",
            "No factuality or hallucination checks detected",
            "No faithfulness/groundedness evaluation found. Confident wrong "
            "answers ship silently — in operations or finance, users act on "
            "them.",
            "Add a faithfulness check: sample answers weekly, verify claims "
            "against source documents (manually or with a judge model), and "
            "track the wrong-answer rate as a first-class metric."))
    return findings, facts


def check_version_pin(project_dir, code_files):
    findings, facts = [], {}
    unpinned = []
    for fp in code_files:
        text = safe_read(fp, 100_000)
        if not text:
            continue
        for m in MODEL_NAME_RE.finditer(text):
            name = m.group(1)
            if not PIN_HINT_RE.search(name) and name not in ("gpt-4o",):
                unpinned.append((os.path.relpath(fp, project_dir), name))
    facts["unpinned_model_refs"] = [{"file": f, "model": m} for f, m in unpinned[:10]]
    if unpinned:
        files = ", ".join(sorted({f for f, _ in unpinned})[:5])
        findings.append(finding(
            "EV-NO-VERSION-PIN", "medium",
            "Model references without a pinned version: %d" % len(unpinned),
            "Files: %s (names only). Unpinned models can be swapped "
            "server-side at any time — behavior changes without a deploy."
            % files,
            "Pin the model version explicitly (e.g. gpt-4o-2024-xx) and "
            "upgrade deliberately, re-running your golden set each time."))
    else:
        findings.append(finding(
            "EV-NO-VERSION-PIN", "info",
            "Model versions are pinned (or none referenced)",
            "No unpinned model references detected.",
            "Re-verify pins after every provider announcement — 'latest' "
            "aliases change under your feet."))
    return findings, facts


def check_human_review(project_dir, code_files):
    findings, facts = [], {}
    has_review = any(HUMAN_REVIEW_RE.search(safe_read(fp, 100_000))
                     for fp in code_files)
    facts["human_review_found"] = has_review
    if has_review:
        findings.append(finding(
            "EV-NO-HUMAN-REVIEW", "info",
            "Human review process detected",
            "Review/annotation workflow found in the project.",
            "Track reviewer agreement over time — disagreement means the "
            "guidelines or the model drifted."))
    else:
        findings.append(finding(
            "EV-NO-HUMAN-REVIEW", "low",
            "No human spot-check workflow detected",
            "No review/annotation process found. Automated metrics miss "
            "failure modes only humans notice.",
            "Institute a weekly 30-minute spot-check of real answers. It is "
            "the cheapest quality signal you will ever get."))
    return findings, facts


def check_ab(project_dir, code_files):
    findings, facts = [], {}
    has_ab = any(AB_RE.search(safe_read(fp, 100_000)) for fp in code_files)
    facts["ab_testing_found"] = has_ab
    if has_ab:
        findings.append(finding(
            "EV-NO-A-B", "info",
            "A/B or shadow testing detected",
            "Experiment/variant infrastructure found.",
            "Define the promotion rule before the experiment: what score "
            "wins, over how many samples."))
    else:
        findings.append(finding(
            "EV-NO-A-B", "low",
            "No A/B or shadow traffic for prompt/model changes",
            "No experiment infrastructure found. Every change is all-or-"
            "nothing for all users.",
            "Route 5-10% of traffic to candidate prompts/models and compare "
            "against the golden set before full rollout."))
    return findings, facts


def compare_reports(current, old_path):
    with open(old_path, encoding="utf-8") as f:
        old = json.load(f)

    def idmap(rep):
        return {f["id"]: f for f in rep.get("findings", []) if f.get("id")}

    cur, oldm = idmap(current), idmap(old)
    new_ids = sorted(set(cur) - set(oldm))
    resolved_ids = sorted(set(oldm) - set(cur))
    persist_ids = sorted(set(cur) & set(oldm))
    sev_changed = [{"id": i, "from": oldm[i]["severity"], "to": cur[i]["severity"]}
                   for i in persist_ids if oldm[i]["severity"] != cur[i]["severity"]]
    return {
        "compared_against": os.path.abspath(old_path),
        "old_generated_at": old.get("generated_at"),
        "new": [cur[i] for i in new_ids],
        "resolved": [{"id": i, "severity": oldm[i]["severity"], "title": oldm[i]["title"]}
                     for i in resolved_ids],
        "persisting": [cur[i] for i in persist_ids],
        "severity_changed": sev_changed,
    }


def render_markdown(report):
    lines = [
        "# Model Evaluation Diagnostic Report",
        "",
        "Generated: %s  |  Project: %s  |  Tool: v%s (schema v%s)" % (
            report["generated_at"], report["facts"].get("project_dir", ""),
            report.get("tool_version", "?"), report.get("schema_version", "?")),
        "",
        "**Summary:** %d high · %d medium · %d low · %d info" % (
            report["summary"]["high"], report["summary"]["medium"],
            report["summary"]["low"], report["summary"]["info"]),
        "",
        "> %s" % report["note"],
        "",
    ]
    for f in report["findings"]:
        hours = f.get("self_fix_hours")
        hours_txt = " · self-fix ~%s h" % hours if hours else ""
        lines.append("### [%s] %s" % (f["severity"].upper(), f["title"]))
        lines.append("- Finding ID: `%s`%s" % (f.get("id", "?"), hours_txt))
        if f["detail"]:
            lines.append("- %s" % f["detail"])
        if f["advice"]:
            lines.append("- **Advice:** %s" % f["advice"])
        lines.append("")
    cmp_ = report.get("compare")
    if cmp_:
        lines += ["## Comparison with previous report", "",
                  "- Baseline: `%s` (generated %s)" % (
                      cmp_["compared_against"], cmp_.get("old_generated_at") or "unknown"), ""]
        for label, key in (("Resolved", "resolved"), ("New", "new")):
            if cmp_[key]:
                lines.append("**%s:**" % label)
                for r in cmp_[key]:
                    lines.append("- %s `%s` %s" % (label.upper(), r["id"], r["title"]))
                lines.append("")
        if cmp_["severity_changed"]:
            lines.append("**Severity changed:**")
            for s in cmp_["severity_changed"]:
                lines.append("- CHANGED `%s`: %s -> %s" % (s["id"], s["from"], s["to"]))
            lines.append("")
        if cmp_["persisting"]:
            lines.append("**Persisting** (not yet fixed, follow the advice):")
            for p in cmp_["persisting"]:
                lines.append("- `%s` %s" % (p["id"], p["title"]))
            lines.append("")
    return "\n".join(lines)


def build_report(project_dir):
    pip = pip_packages()
    all_findings = []
    facts = {"generated_at": __import__("datetime").datetime.now().isoformat(),
             "project_dir": os.path.abspath(project_dir)}
    stack_findings, stack_facts, code_files = check_stack(project_dir, pip)
    all_findings.extend(stack_findings)
    facts.update(stack_facts)
    for fn in (check_eval_set, check_regression, check_hallucination,
               check_version_pin, check_human_review, check_ab):
        f, fa = fn(project_dir, code_files)
        all_findings.extend(f)
        facts.update(fa)
    all_findings.sort(key=lambda x: (SEV_RANK.get(x["severity"], 9), x.get("id", "")))
    summary = {s: sum(1 for f in all_findings if f["severity"] == s)
               for s in ("high", "medium", "low", "info")}
    return {
        "report_type": "model_evaluation_diagnostic",
        "tool_version": TOOL_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": facts["generated_at"],
        "summary": summary,
        "findings": all_findings,
        "facts": facts,
        "note": ("This report contains NO secret values and NO file contents — "
                 "only filenames, counts, pattern names and recommendations. "
                 "It is safe to share back for a remediation proposal."),
    }


def main():
    ap = argparse.ArgumentParser(description="Model evaluation diagnostic (read-only)")
    ap.add_argument("project_dir", nargs="?", default=os.getcwd())
    ap.add_argument("--output", default=None,
                    help="Directory for reports (default: <project_dir>/eval_diag_reports)")
    ap.add_argument("--compare", metavar="OLD_REPORT.json",
                    help="Compare with a previous JSON report (new/resolved/persisting)")
    ap.add_argument("--json", action="store_true", help="Also print JSON to stdout")
    args = ap.parse_args()

    report = build_report(args.project_dir)
    if args.compare:
        if not os.path.exists(args.compare):
            print("Compare failed: old report not found: %s" % args.compare)
            sys.exit(2)
        try:
            report["compare"] = compare_reports(report, args.compare)
        except Exception:
            print("Compare failed: old report unreadable (%s)" % type(e).__name__)
            sys.exit(2)

    outdir = args.output or os.path.join(args.project_dir, "eval_diag_reports")
    os.makedirs(outdir, exist_ok=True)
    md_path = os.path.join(outdir, "model_evaluation_report.md")
    js_path = os.path.join(outdir, "model_evaluation_report.json")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(report))
    with open(js_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    s = report["summary"]
    print("Model evaluation diagnostic complete.")
    print("  high: %d | medium: %d | low: %d | info: %d" % (
        s["high"], s["medium"], s["low"], s["info"]))
    cmp_ = report.get("compare")
    if cmp_:
        print("  compare: %d new | %d resolved | %d persisting" % (
            len(cmp_["new"]), len(cmp_["resolved"]), len(cmp_["persisting"])))
    print("Report: %s" % md_path)
    print("        %s" % js_path)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
