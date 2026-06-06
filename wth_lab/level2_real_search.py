from __future__ import annotations

import argparse
import contextlib
import io
import itertools
import tempfile
import time
from pathlib import Path

from watt_the_hack.playtest import run_playtest


ROOT = Path(__file__).resolve().parents[1]
STRATEGY = ROOT / "submissions" / "level2_frequency_frenzy" / "attempt1_strategy.py"
SCENARIO = "frequency_frenzy"


def _candidate_source(base: str, dawn: float, target: float, threshold: float, reserve: float) -> str:
    source = base
    source = source.replace(
        "grid_target = 105.0 if demand > 160.0 and solar < 5.0 else import_cap",
        f"grid_target = {dawn!r} if demand > 160.0 and solar < 5.0 else import_cap",
    )
    source = source.replace(
        "if time_index >= 23 and deficit > 0.0 and price >= 260.0:",
        f"if time_index >= 23 and deficit > 0.0 and price >= {threshold!r}:",
    )
    source = source.replace(
        "reserve_floor = max(0.12, floor + 0.03)",
        f"reserve_floor = max({reserve!r}, floor + 0.03)",
    )
    source = source.replace(
        "high_price_target = 95.0",
        f"high_price_target = {target!r}",
    )
    return source


def main() -> int:
    parser = argparse.ArgumentParser(description="Level 2 real-scenario parameter search.")
    parser.add_argument("--hours", type=float, default=2.0)
    parser.add_argument("--batch-size", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=101)
    args = parser.parse_args()

    base = STRATEGY.read_text(encoding="utf-8")
    deadline = time.monotonic() + max(0.0, args.hours) * 3600.0
    combos = list(
        itertools.product(
            [100.0, 105.0, 110.0, 115.0],
            [75.0, 80.0, 85.0, 90.0, 95.0],
            [220.0, 260.0, 300.0, 340.0],
            [0.12, 0.14, 0.16, 0.18],
        )
    )
    offset = args.seed % len(combos)
    combos = combos[offset:] + combos[:offset]

    best: tuple[float, float, float, float, float] | None = None
    tested = 0
    for dawn, target, threshold, reserve in itertools.islice(itertools.cycle(combos), args.batch_size):
        if time.monotonic() >= deadline:
            break
        with tempfile.TemporaryDirectory(prefix="wth-l2-") as temp_dir:
            temp = Path(temp_dir)
            candidate = temp / "strategy.py"
            candidate.write_text(
                _candidate_source(base, dawn, target, threshold, reserve),
                encoding="utf-8",
            )
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = run_playtest(
                    candidate,
                    SCENARIO,
                    out_dir=temp / "run",
                    plots=False,
                    verbose=False,
                )
        tested += 1
        metrics = result["metrics"]
        if metrics.get("controller_errors") or metrics.get("unmet_demand_total"):
            continue
        score = float(metrics["final_score"])
        row = (score, dawn, target, threshold, reserve)
        if best is None or row < best:
            best = row
            print(
                "best",
                f"score={score:.6f}",
                f"dawn={dawn}",
                f"target={target}",
                f"threshold={threshold}",
                f"reserve={reserve}",
                flush=True,
            )

    print(f"tested={tested}")
    if best is None:
        print("no zero-unmet candidates found")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
