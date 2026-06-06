# Level 2 WSL2 Resume

Date: 2026-06-06

The local `/home/mike/watt` tree was not a Git checkout and only had the stale `watt-the-hack==0.2.8` wheel, which did not include `frequency_frenzy`. I cloned the public Python repo into `/home/mike/watt-upstream`, installed it editable, and copied the existing submission artifacts into that checkout.

Validation:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e '.[playtest]'
.venv/bin/python -m watt_the_hack.playtest submissions/level2_frequency_frenzy/attempt1_strategy.py --scenario frequency_frenzy --no-plots --quiet --out runs/level2_laptop_final
```

Result for `submissions/level2_frequency_frenzy/attempt1_strategy.py`:

- Final score: `$1,211,212.093404`
- Unmet demand: `0.0 MWh`
- Controller errors: `0`
- Blackout penalty: `$0.00`

Key repair:

- The prior strategy held SOC during the dawn heating spike and caused `$8.125M` in blackout penalties.
- The updated strategy treats import-cap breaches as reliability-critical, runs diesel during the 185 MW dawn spike, and reserves enough battery for the full spike window.
- A high-price post-dawn shaving rule reduces later imports while keeping zero unmet demand.

Follow-up optimization:

- `submissions/level2_frequency_frenzy/attempt2_strategy.py` is a generated LP ramp-smoothed schedule with a final score of `$1,066,497.4480180626`.
- It keeps unmet demand at `0.0 MWh`, cuts demand charge to about `$85k`, and lowers ramp charge to about `$9.4k`.
