from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import math
import random
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from watt_the_hack.playtest import run_playtest
from watt_the_hack.simulation.boot import boot_scenario, scenario_steps


ROOT = Path(__file__).resolve().parents[1]
BASE_STRATEGY = ROOT / "submissions" / "level2_frequency_frenzy" / "attempt1_strategy.py"


@dataclass(frozen=True)
class Params:
    dawn_target: float
    high_price_target: float
    price_threshold: float
    reserve_floor: float
    dawn_trigger_demand: float
    high_price_start: int
    high_price_flow_cap: float


@dataclass(frozen=True)
class StepView:
    demand: float
    solar: float
    price: float
    fd0: float | None
    fs0: float | None
    fp0: float | None
    max_deficit: float | None
    max_fp: float | None
    cheap_fp: float | None
    median_fp: float | None
    max_fd: float | None


BASELINE = Params(105.0, 95.0, 260.0, 0.12, 160.0, 23, 46.0)


def _collect_views():
    engine, state, _ = boot_scenario("frequency_frenzy")
    views: list[StepView] = []
    for _ in range(scenario_steps(state)):
        view = engine.controller_view(state)
        forecast = copy.deepcopy(view.get("forecast") or {})
        fd = [float(x) for x in (forecast.get("demand") or [])[:16]]
        fs = [float(x) for x in (forecast.get("solar") or [])[:16]]
        fp = [float(x) for x in (forecast.get("price") or [])[:16]]
        ordered_fp = sorted(fp)
        views.append(
            StepView(
                demand=float(view["demand"]),
                solar=float(view["solar"]),
                price=float(view.get("price", 0.0)),
                fd0=fd[0] if fd else None,
                fs0=fs[0] if fs else None,
                fp0=fp[0] if fp else None,
                max_deficit=max([d - s for d, s in zip(fd, fs)] or [0.0]) if fd and fs else None,
                max_fp=max(fp) if fp else None,
                cheap_fp=ordered_fp[max(0, len(ordered_fp) // 3)] if ordered_fp else None,
                median_fp=ordered_fp[len(ordered_fp) // 2] if ordered_fp else None,
                max_fd=max(fd) if fd else None,
            )
        )
        state, _ = engine.step(state, {})
    return views, engine.config


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _policy_action(params: Params, view: StepView, soc: float, t: int, biases: list[float]):
    demand = view.demand
    solar = view.solar
    price = view.price

    has_fd = view.fd0 is not None
    has_fs = view.fs0 is not None
    has_fp = view.fp0 is not None
    if has_fd:
        biases[0] = 0.85 * biases[0] + 0.15 * (demand - view.fd0)
    if has_fs:
        biases[1] = 0.85 * biases[1] + 0.15 * (solar - view.fs0)
    if has_fp:
        biases[2] = 0.85 * biases[2] + 0.15 * (price - view.fp0)

    target_soc = 0.18
    if view.max_deficit is not None:
        if view.max_deficit + biases[0] - biases[1] > 25.0:
            target_soc = max(target_soc, 0.62)
    if view.max_fp is not None and view.max_fp + biases[2] > price + 90.0:
        target_soc = max(target_soc, 0.70)
    if solar > demand + 5.0:
        target_soc = max(target_soc, 0.88)

    surplus = solar - demand
    deficit = max(demand - solar, 0.0)
    flow = 0.0

    if soc < target_soc - 0.015:
        if surplus > 1.0:
            flow = -min(42.0, surplus)
        elif _cheap_price(price, view.cheap_fp, biases[2]):
            flow = -min(34.0, max(8.0, (target_soc - soc) * 400.0))
    elif deficit > 0.0 and soc > 0.14:
        expensive_now = view.median_fp is None or price >= view.median_fp + biases[2] + 30.0
        max_future_demand = demand if view.max_fd is None else max(demand, view.max_fd + biases[0])
        peak_risk = demand > 0.88 * max_future_demand
        if expensive_now or peak_risk:
            spare_soc = max(0.0, soc - 0.12)
            flow = min(42.0, deficit, spare_soc * 380.0)

    if t >= params.high_price_start and deficit > 0.0 and price >= params.price_threshold:
        spare_soc = max(0.0, soc - params.reserve_floor)
        extra = min(
            params.high_price_flow_cap - max(flow, 0.0),
            deficit - max(flow, 0.0),
            max(0.0, demand - solar - flow - params.high_price_target),
            spare_soc * 380.0,
        )
        if extra > 0.0:
            flow += extra

    generator = 0.0
    grid_target = (
        params.dawn_target
        if demand > params.dawn_trigger_demand and solar < 5.0
        else 120.0
    )
    if demand - solar - flow > grid_target:
        generator = min(50.0, max(0.0, demand - solar - flow - grid_target))
        spare_soc = max(0.0, soc - 0.10)
        extra_discharge = min(
            max(0.0, 50.0 - max(flow, 0.0)),
            demand - solar - flow - grid_target,
            max(0.0, demand - solar - flow - generator - grid_target),
            spare_soc * 380.0,
        )
        if extra_discharge > 0.0:
            flow += extra_discharge

    net = demand - solar - flow - generator
    return flow, generator, max(0.0, -net - 50.0)


def _cheap_price(price: float, cheap_fp: float | None, price_bias: float) -> bool:
    if cheap_fp is None:
        return price < 80.0
    return price <= cheap_fp + price_bias


def evaluate(params: Params, views: list[StepView], cfg, want_breakdown: bool = False) -> tuple[float, float, dict[str, float]]:
    soc = 0.5
    peak = 0.0
    prev_grid = None
    total = 0.0
    unmet_mwh = 0.0
    if want_breakdown:
        breakdown = {
            "tariff_import": 0.0,
            "tariff_export": 0.0,
            "generator_fuel": 0.0,
            "blackout_penalty": 0.0,
            "overvoltage_penalty": 0.0,
            "battery_wear": 0.0,
            "demand_charge": 0.0,
            "carbon_cost": 0.0,
            "ramp_charge": 0.0,
        }
    else:
        breakdown = {}
    biases = [0.0, 0.0, 0.0]

    for t, view in enumerate(views):
        demand = view.demand
        solar = view.solar
        price = view.price
        requested_battery, requested_gen, requested_curtail = _policy_action(params, view, soc, t, biases)

        battery = _clip(requested_battery, -cfg.max_inverter_mw, cfg.max_inverter_mw)
        if battery > 0.0:
            max_discharge = (soc * cfg.battery_capacity_mwh * cfg.discharge_efficiency) / cfg.dt_hours
            battery = min(battery, max_discharge)
            next_soc = soc - (battery * cfg.dt_hours) / (
                cfg.battery_capacity_mwh * cfg.discharge_efficiency
            )
        elif battery < 0.0:
            headroom = (1.0 - soc) * cfg.battery_capacity_mwh
            max_charge = headroom / (cfg.charge_efficiency * cfg.dt_hours)
            battery = max(battery, -max_charge)
            next_soc = soc - (battery * cfg.charge_efficiency * cfg.dt_hours) / cfg.battery_capacity_mwh
        else:
            next_soc = soc
        soc = _clip(next_soc, 0.0, 1.0)

        generator = _clip(requested_gen, 0.0, cfg.max_emergency_generator_mw)
        curtail = _clip(requested_curtail, 0.0, solar)
        actual_solar = solar - curtail
        net_grid = demand - actual_solar - battery - generator

        unmet = 0.0
        overvoltage = 0.0
        if net_grid > cfg.grid_max_import_mw:
            unmet = net_grid - cfg.grid_max_import_mw
            net_grid = cfg.grid_max_import_mw
        elif net_grid < -cfg.grid_max_export_mw:
            overvoltage = abs(net_grid) - cfg.grid_max_export_mw
            net_grid = -cfg.grid_max_export_mw

        dt = cfg.dt_hours
        energy = net_grid * dt
        tariff_import = energy * price if energy > 0.0 else 0.0
        tariff_export = energy * cfg.export_tariff if energy <= 0.0 else 0.0
        diesel_mwh = generator * dt
        co2 = max(0.0, energy) * cfg.grid_co2_intensity_kg_per_mwh + diesel_mwh * cfg.diesel_co2_intensity_kg_per_mwh
        new_peak = max(peak, max(0.0, net_grid))
        ramp = 0.0 if prev_grid is None else (net_grid - prev_grid) ** 2 * cfg.ramp_charge_per_kw2

        generator_fuel = diesel_mwh * cfg.emergency_generator_cost_per_mwh
        blackout_penalty = unmet * dt * cfg.blackout_penalty_per_mwh
        overvoltage_penalty = overvoltage * dt * cfg.overvoltage_penalty_per_mwh
        battery_wear = abs(battery) * dt * cfg.battery_wear_cost_per_mwh
        demand_charge = max(0.0, new_peak - peak) * cfg.demand_charge_per_mw
        carbon_cost = co2 * cfg.carbon_price_per_kg
        total += (
            tariff_import
            + tariff_export
            + generator_fuel
            + blackout_penalty
            + overvoltage_penalty
            + battery_wear
            + demand_charge
            + carbon_cost
            + ramp
        )
        if want_breakdown:
            breakdown["tariff_import"] += tariff_import
            breakdown["tariff_export"] += tariff_export
            breakdown["generator_fuel"] += generator_fuel
            breakdown["blackout_penalty"] += blackout_penalty
            breakdown["overvoltage_penalty"] += overvoltage_penalty
            breakdown["battery_wear"] += battery_wear
            breakdown["demand_charge"] += demand_charge
            breakdown["carbon_cost"] += carbon_cost
            breakdown["ramp_charge"] += ramp
        unmet_mwh += unmet * dt
        peak = new_peak
        prev_grid = net_grid

    return total, unmet_mwh, breakdown


def generate_params(rng: random.Random, best: Params | None) -> Params:
    if best is not None and rng.random() < 0.55:
        scale = 0.35 + rng.random() * 1.5
        return Params(
            dawn_target=_clip(rng.gauss(best.dawn_target, 3.0 * scale), 98.0, 112.0),
            high_price_target=_clip(rng.gauss(best.high_price_target, 5.0 * scale), 78.0, 112.0),
            price_threshold=_clip(rng.gauss(best.price_threshold, 30.0 * scale), 180.0, 420.0),
            reserve_floor=_clip(rng.gauss(best.reserve_floor, 0.018 * scale), 0.095, 0.22),
            dawn_trigger_demand=_clip(rng.gauss(best.dawn_trigger_demand, 5.0 * scale), 150.0, 172.0),
            high_price_start=int(round(_clip(rng.gauss(best.high_price_start, 3.0 * scale), 18.0, 36.0))),
            high_price_flow_cap=_clip(rng.gauss(best.high_price_flow_cap, 2.5 * scale), 34.0, 50.0),
        )
    return Params(
        dawn_target=rng.uniform(98.0, 112.0),
        high_price_target=rng.uniform(78.0, 112.0),
        price_threshold=10 ** rng.uniform(math.log10(180.0), math.log10(420.0)),
        reserve_floor=rng.uniform(0.095, 0.22),
        dawn_trigger_demand=rng.uniform(150.0, 172.0),
        high_price_start=rng.randrange(18, 37),
        high_price_flow_cap=rng.uniform(34.0, 50.0),
    )


def render_candidate(params: Params) -> str:
    text = BASE_STRATEGY.read_text(encoding="utf-8")
    replacements = {
        "grid_target = 105.0 if demand > 160.0 and solar < 5.0 else import_cap":
            f"grid_target = {params.dawn_target!r} if demand > {params.dawn_trigger_demand!r} and solar < 5.0 else import_cap",
        "if time_index >= 23 and deficit > 0.0 and price >= 260.0:":
            f"if time_index >= {params.high_price_start} and deficit > 0.0 and price >= {params.price_threshold!r}:",
        "reserve_floor = max(0.12, floor + 0.03)":
            f"reserve_floor = max({params.reserve_floor!r}, floor + 0.03)",
        "high_price_target = 95.0":
            f"high_price_target = {params.high_price_target!r}",
        "46.0 - max(flow, 0.0)":
            f"{params.high_price_flow_cap!r} - max(flow, 0.0)",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def write_new_best(out_dir: Path, seq: int, score: float, params: Params, breakdown: dict[str, float]) -> None:
    candidates = out_dir / "candidates"
    candidates.mkdir(parents=True, exist_ok=True)
    stem = f"candidate_{seq:06d}_{score:.3f}"
    py_path = candidates / f"{stem}.py"
    json_path = candidates / f"{stem}.json"
    if py_path.exists() or json_path.exists():
        raise FileExistsError(f"candidate path already exists: {stem}")
    py_path.write_text(render_candidate(params), encoding="utf-8")
    json_path.write_text(
        json.dumps({"score": score, "params": params.__dict__, "breakdown": breakdown}, indent=2),
        encoding="utf-8",
    )


def validate_params(params: Params) -> tuple[float, float, dict[str, float]]:
    with tempfile.TemporaryDirectory(prefix="wth-l2-validate-") as temp_dir:
        temp = Path(temp_dir)
        candidate = temp / "candidate.py"
        candidate.write_text(render_candidate(params), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = run_playtest(
                candidate,
                "frequency_frenzy",
                out_dir=temp / "run",
                plots=False,
                verbose=False,
            )
    metrics = result["metrics"]
    return (
        float(metrics["final_score"]),
        float(metrics["unmet_demand_total"]),
        {k: float(v) for k, v in result["breakdown"].items()},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast global Level 2 search.")
    parser.add_argument("--seed", type=int, default=20260606)
    parser.add_argument("--min-rate", type=float, default=500.0)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--status-interval", type=float, default=5.0)
    args = parser.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out or ROOT / "runs" / f"level2_global_search_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    views, cfg = _collect_views()

    best_score, best_unmet, best_breakdown = validate_params(BASELINE)
    best_params = BASELINE
    proposal_score, proposal_params = best_score, best_params
    seq = 0
    write_new_best(out_dir, seq, best_score, best_params, best_breakdown)

    started = last = time.perf_counter()
    total = 0
    valid = 0
    log_path = out_dir / "search.jsonl"
    with log_path.open("a", encoding="utf-8") as log:
        log.write(json.dumps({"event": "start", "seed": args.seed, "baseline_score": best_score, "baseline_unmet": best_unmet}) + "\n")
        while True:
            params = generate_params(rng, proposal_params)
            score, unmet, _ = evaluate(params, views, cfg)
            total += 1
            if unmet == 0.0:
                valid += 1
                if score < proposal_score:
                    real_score, real_unmet, real_breakdown = validate_params(params)
                    log.write(
                        json.dumps(
                            {
                                "event": "proposal",
                                "tested": total,
                                "fast_score": score,
                                "real_score": real_score,
                                "real_unmet": real_unmet,
                                "params": params.__dict__,
                            }
                        )
                        + "\n"
                    )
                    if real_unmet == 0.0 and real_score < best_score:
                        seq += 1
                        best_score = real_score
                        best_params = params
                        proposal_score = score
                        proposal_params = params
                        write_new_best(out_dir, seq, real_score, params, real_breakdown)
                        log.write(json.dumps({"event": "best", "tested": total, "score": real_score, "params": params.__dict__}) + "\n")
                    log.flush()

            now = time.perf_counter()
            if now - last >= args.status_interval:
                elapsed = now - started
                rate = total / max(elapsed, 1e-9)
                status = {
                    "event": "status",
                    "tested": total,
                    "valid": valid,
                    "rate_candidates_per_sec": rate,
                    "best_score": best_score,
                    "best_params": best_params.__dict__,
                    "out_dir": str(out_dir),
                    "rate_ok": rate >= args.min_rate,
                }
                (out_dir / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
                print(json.dumps(status), flush=True)
                last = now


if __name__ == "__main__":
    raise SystemExit(main())
