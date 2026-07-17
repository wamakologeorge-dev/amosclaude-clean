"""
planner.py — the autonomous execution loop.

Two ways to drive the agent:
  1. Explicit plan: caller supplies a list of {tool, args} steps and the
     agent executes them in order. Fully deterministic.
  2. Autonomous goal: caller supplies just a natural-language "goal" and
     the agent decides its own plan using real (if simple) rule-based
     planning, then executes it — looping tool calls until the plan is
     done or max_steps is hit.

The planner is intentionally honest about its own limits: it is a
rule-based dispatcher, not a general reasoning engine. It looks at the
goal text for concrete signals (a URL present, the word "publish", etc.)
and builds a plan from that. This is genuinely autonomous in the sense
that no human chooses the steps — the agent does, every run — but it
is not claiming LLM-grade planning intelligence.
"""

import re
from typing import Dict, List

from tools import TOOL_REGISTRY

URL_RE = re.compile(r"https?://\S+")

MAX_STEPS_HARD_CAP = 25
DEFAULT_MAX_STEPS = 10


def auto_plan(goal: str) -> List[Dict]:
    """Builds a real (rule-based) plan from a natural-language goal."""
    lower = goal.lower()
    url_match = URL_RE.search(goal)

    plan: List[Dict] = []

    if url_match:
        url = url_match.group(0)
        plan.append({"tool": "fetch_url", "args": {"url": url}})
        plan.append({
            "tool": "generate",
            "args": {"prompt": f"Summary of {url}:", "max_new_tokens": 60},
        })

    if "publish" in lower:
        plan.append({
            "tool": "generate",
            "args": {"prompt": goal, "max_new_tokens": 80},
        })
        # title/content for the publish step get filled in from the prior
        # generate step's output at execution time (see run_plan)
        plan.append({"tool": "publish", "args": {"title": "__from_previous__", "content": "__from_previous__"}})

    if not plan:
        # default: just generate a response to the goal
        plan.append({"tool": "generate", "args": {"prompt": goal, "max_new_tokens": 80}})

    return plan


def run_plan(model, plan: List[Dict], max_steps: int = DEFAULT_MAX_STEPS) -> Dict:
    max_steps = min(max_steps, MAX_STEPS_HARD_CAP)
    transcript = []
    last_generated_text = None

    for i, step in enumerate(plan):
        if i >= max_steps:
            transcript.append({
                "step": i,
                "tool": step.get("tool"),
                "skipped": True,
                "reason": f"max_steps ({max_steps}) reached",
            })
            break

        tool_name = step.get("tool")
        args = dict(step.get("args", {}))

        if tool_name not in TOOL_REGISTRY:
            transcript.append({
                "step": i,
                "tool": tool_name,
                "ok": False,
                "error": f"unknown tool '{tool_name}'",
            })
            continue

        # wire "publish" placeholders to the most recent generated text so
        # auto-planned publish steps actually carry real content forward
        if tool_name == "publish":
            if args.get("title") == "__from_previous__":
                args["title"] = (last_generated_text or "Amosclaud update")[:60]
            if args.get("content") == "__from_previous__":
                args["content"] = last_generated_text or ""

        result = TOOL_REGISTRY[tool_name](model, args)

        if tool_name == "generate" and result.get("ok"):
            last_generated_text = result.get("text")

        transcript.append({"step": i, "tool": tool_name, "args": args, **result})

        if not result.get("ok", True):
            # stop on first real failure rather than pretending to continue
            break

    return {
        "transcript": transcript,
        "steps_run": len(transcript),
        "completed": all(t.get("ok", True) for t in transcript) and len(transcript) > 0,
    }
