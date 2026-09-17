"""Explicit live evaluation; no fabricated scores when credentials are unavailable."""

import argparse
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from router.ai.errors import ReviewError
from router.ai.service import ProposalService

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ["response_1_weak", "response_2_medium", "response_3_strong", "response_4_overpromise"]


def strip_test_metadata(text):
    # Evaluation-only label removal, matching the existing UI. Never used by AI runtime.
    return "\n".join(
        line for line in text.split("\n") if not re.match(r"\s*\*\*Variant:", line, re.I)
    ).rstrip()


def checks(name, result):
    scores = {c.criterion: c.score for c in result.review.criteria}
    counts = result.counters
    if name == "response_1_weak":
        return {
            "gaps_found": counts["not_found"] + counts["partial_or_unclear"] >= 2,
            "pricing_weak": scores["pricing_clarity"] <= 2,
            "timeline_weak": scores["timeline_clarity"] <= 2,
            "risk_disclosure_weak": scores["risk_assumptions_transparency"] <= 2,
        }
    if name == "response_2_medium":
        return {
            "some_scope_satisfied": counts["satisfied"] >= 1,
            "pricing_qualified": scores["pricing_clarity"] < 4,
            "timeline_qualified": scores["timeline_clarity"] < 4,
            "risk_disclosure_weak": scores["risk_assumptions_transparency"] <= 2,
        }
    if name == "response_3_strong":
        return {
            "mostly_satisfied": counts["satisfied"] / sum(counts.values()) >= 0.6,
            "no_false_contradictions": counts["contradicted"] == 0,
            "generally_strong": sum(scores.values()) / 7 >= 4,
        }
    if name == "response_4_overpromise":
        return {
            "explicit_conflict_found": counts["contradicted"] >= 1,
            "not_ready_to_send": result.readiness in ("not_ready", "major_revision"),
            "risks_not_ignored": scores["risk_assumptions_transparency"] <= 2,
        }
    return {
        "synthetic_conflict_found": counts["contradicted"] >= 1,
        "binding_conflict_gated": result.readiness == "not_ready",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Call Gemini; consumes API quota")
    parser.add_argument("--output-dir", type=Path, default=Path("evaluation-output"))
    args = parser.parse_args()
    load_dotenv()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    names = [*SAMPLES, "synthetic_unseen"]
    report = {
        "mode": "live" if args.live else "not_run",
        "cases": [],
        "note": "Heuristic acceptance checks, not sponsor-assigned ground truth; human evidence/coverage review remains required.",
    }
    available = args.live and os.getenv("GEMINI_API_KEY") and os.getenv("GEMINI_MODEL")
    for name in names:
        if not available:
            report["cases"].append(
                {
                    "sample": name,
                    "status": "not_run",
                    "reason": "Set GEMINI_API_KEY and GEMINI_MODEL and pass --live; no model score was generated.",
                }
            )
            continue
        if name == "synthetic_unseen":
            rfp = (ROOT / "app/tests/data/synthetic_rfp.md").read_text()
            proposal = (ROOT / "app/tests/data/synthetic_proposal.md").read_text()
        else:
            rfp = (ROOT / "sample_data/rfp_nordframe.md").read_text().rstrip()
            proposal = strip_test_metadata((ROOT / f"sample_data/{name}.md").read_text())
        try:
            result = ProposalService().review({"rfp": rfp, "proposal": proposal})
            (args.output_dir / f"{name}.json").write_text(
                result.model_dump_json(by_alias=True, indent=2)
            )
            acceptance = checks(name, result)
            report["cases"].append(
                {
                    "sample": name,
                    "status": "pass" if all(acceptance.values()) else "needs_review",
                    "checks": acceptance,
                    "overall": result.overall,
                    "readiness": result.readiness,
                    "counters": result.counters,
                }
            )
        except ReviewError as exc:
            report["cases"].append({"sample": name, "status": "error", **exc.payload()})
    results = {case["sample"]: case for case in report["cases"]}
    if all("overall" in results[n] for n in SAMPLES[:3]):
        report["strong_medium_weak_order"] = (
            results[SAMPLES[2]]["overall"]
            > results[SAMPLES[1]]["overall"]
            > results[SAMPLES[0]]["overall"]
        )
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return (
        0
        if all(c["status"] == "pass" for c in report["cases"])
        and report.get("strong_medium_weak_order", True)
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
