# Model Evaluation Diagnostic

Free, read-only health-check for answer-quality governance: does the project
measure whether its AI is actually right — before and after every change?

Part of the [Huodou diagnostic package family](https://www.huodouai.com/sop-demo/)
(11 packages covering memory, environment, SOP, cost, retrieval, trust,
drift, injection, latency, evaluation and integration reliability).

## Why

Most agent projects ship prompt, model and retrieval changes with **zero
quality measurement**. Regressions reach users unnoticed — in operations,
finance or healthcare, users act on confident wrong answers. This tool
audits whether the project can even detect a quality drop.

## What it checks

| Finding ID | Severity | What it means |
|---|---|---|
| `EV-NO-EVAL-SET` | high | No golden/eval set — every release is a guess |
| `EV-NO-REGRESSION-TEST` | medium | No CI or scheduled job re-checks answer quality |
| `EV-NO-HALLUCINATION-CHECK` | medium | No factuality/faithfulness sampling |
| `EV-NO-VERSION-PIN` | medium | Unpinned model refs — provider can swap behavior server-side |
| `EV-NO-HUMAN-REVIEW` | low | No human spot-check workflow |
| `EV-NO-A-B` | low | No A/B or shadow traffic for changes |
| `EV-STACK-OK` / `EV-NO-STACK` | info | LLM stack detected / not detected |

## Quick start

```bash
python eval_diagnose.py /path/to/your/agent/project
```

Report written to `eval_diag_reports/model_evaluation_report.md` (and `.json`).

## Prove the fix worked

```bash
python eval_diagnose.py /path/to/project --compare eval_diag_reports/model_evaluation_report.json
```

Diffs by stable finding ID: resolved / new / persisting / severity changes.
Acceptance criterion: **high-severity findings N → 0**. Pair with
[Drift Watch](https://www.huodouai.com/whitepaper/drift-watch-package-20261125.html)
to keep it there.

## Privacy

Read-only, offline, standard library only. The report contains no secret
values and no file contents. Python 3.8+.

## Send the report back

Email it to **195162494@qq.com** (individuals and companies welcome) for a
written evaluation-governance proposal: golden set design, CI wiring,
faithfulness sampling.

## License

MIT — see [LICENSE](LICENSE).
