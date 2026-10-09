import argparse
import collections
import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "third_party/webarena/config_files/test.raw.json"
KINDS = ("pass", "fail", "error", "ungraded", "missing")


def load(dirs: list[Path]) -> tuple[dict[int, dict[str, Any]], collections.Counter[int]]:
    # a later directory's row replaces an earlier one for the same task
    rows: dict[int, dict[str, Any]] = {}
    seen: collections.Counter[int] = collections.Counter()
    for directory in dirs:
        with open(directory / "ledger.jsonl") as f:
            for line in f:
                row = json.loads(line)
                rows[row["task_id"]] = {**row, "run": directory.name}
                seen[row["task_id"]] += 1
    return rows, seen


def kind(row: dict[str, Any] | None) -> str:
    if row is None:
        return "missing"
    if row["score"] is None:
        # run.py logs an exception instead of a score; only the GPT-4 judge's missing key leaves
        # an answer ungraded, any other exception is an episode that crashed
        return "ungraded" if "OPENAI_API_KEY" in (row["failure"] or "") else "error"
    return "pass" if row["score"] == 1.0 else "fail"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", type=Path, nargs="+", help="run directories; later ones win")
    ap.add_argument("--csv", type=Path, help="write one row per task")
    options = ap.parse_args()
    with open(TASKS) as f:
        tasks = {c["task_id"]: c for c in json.load(f)}
    rows, seen = load(options.dirs)

    by_site: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for task_id, config in tasks.items():
        by_site["+".join(sorted(config["sites"]))][kind(rows.get(task_id))] += 1
    total: collections.Counter[str] = collections.Counter()
    print(f"{'sites':28s} {'tasks':>5s} " + " ".join(f"{k:>8s}" for k in KINDS))
    for site, counts in sorted(by_site.items()):
        total.update(counts)
        print(f"{site:28s} {sum(counts.values()):5d} " + " ".join(f"{counts[k]:8d}" for k in KINDS))
    print(f"{'total':28s} {len(tasks):5d} " + " ".join(f"{total[k]:8d}" for k in KINDS))
    print(f"success rate {total['pass']}/{len(tasks)} = {100 * total['pass'] / len(tasks):.2f}%")
    repeated = sorted(t for t, n in seen.items() if n > 1)
    print(f"tasks with more than one row across the directories: {len(repeated)} {repeated}")

    if options.csv:
        with open(options.csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "task_id",
                    "template_id",
                    "sites",
                    "result",
                    "steps",
                    "seconds",
                    "answer",
                    "failure",
                    "run",
                ]
            )
            for task_id, config in sorted(tasks.items()):
                row = rows.get(task_id) or {}
                writer.writerow(
                    [
                        task_id,
                        config["intent_template_id"],
                        "+".join(sorted(config["sites"])),
                        kind(rows.get(task_id)),
                        row.get("steps", ""),
                        row.get("seconds", ""),
                        row.get("answer", ""),
                        row.get("failure") or "",
                        row.get("run", ""),
                    ]
                )


if __name__ == "__main__":
    main()
