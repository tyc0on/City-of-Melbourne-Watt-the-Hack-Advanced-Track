from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from wth_lab.level2_global_search import (
    BASELINE,
    Params,
    generate_params,
    render_candidate,
    validate_params,
)


ROOT = Path(__file__).resolve().parents[1]


def write_candidate(out_dir: Path, seq: int, score: float, unmet: float, params: Params, breakdown: dict[str, float]) -> None:
    candidates = out_dir / "candidates"
    candidates.mkdir(parents=True, exist_ok=True)
    stem = f"candidate_{seq:06d}_{score:.3f}"
    py_path = candidates / f"{stem}.py"
    json_path = candidates / f"{stem}.json"
    if py_path.exists() or json_path.exists():
        raise FileExistsError(stem)
    py_path.write_text(render_candidate(params), encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "score": score,
                "unmet": unmet,
                "params": params.__dict__,
                "breakdown": breakdown,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Exact Level 2 safe-region search.")
    parser.add_argument("--seed", type=int, default=20260606)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--status-interval", type=float, default=10.0)
    args = parser.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out or ROOT / "runs" / f"level2_exact_safe_search_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    best_params = BASELINE
    best_score, best_unmet, best_breakdown = validate_params(best_params)
    seq = 0
    write_candidate(out_dir, seq, best_score, best_unmet, best_params, best_breakdown)

    tested = valid = 0
    started = last = time.perf_counter()
    log_path = out_dir / "search.jsonl"
    with log_path.open("a", encoding="utf-8") as log:
        log.write(json.dumps({"event": "start", "seed": args.seed, "baseline_score": best_score}) + "\n")
        while True:
            params = generate_params(rng, best_params)
            score, unmet, breakdown = validate_params(params)
            tested += 1
            if unmet == 0.0:
                valid += 1
                if score < best_score:
                    seq += 1
                    best_score = score
                    best_params = params
                    write_candidate(out_dir, seq, score, unmet, params, breakdown)
                    log.write(json.dumps({"event": "best", "tested": tested, "score": score, "params": params.__dict__}) + "\n")
                    log.flush()

            now = time.perf_counter()
            if now - last >= args.status_interval:
                elapsed = now - started
                status = {
                    "event": "status",
                    "tested": tested,
                    "valid": valid,
                    "rate_candidates_per_sec": tested / max(elapsed, 1e-9),
                    "best_score": best_score,
                    "best_params": best_params.__dict__,
                    "out_dir": str(out_dir),
                }
                (out_dir / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
                print(json.dumps(status), flush=True)
                last = now


if __name__ == "__main__":
    raise SystemExit(main())
