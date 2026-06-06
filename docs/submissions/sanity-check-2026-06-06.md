# Level 2 Sanity Check - 2026-06-06

Command:

```bash
.venv/bin/python -m watt_the_hack.playtest submissions/level2_frequency_frenzy/attempt1_strategy.py --scenario frequency_frenzy --no-plots --quiet --out runs/level2_laptop_final
```

Result:

- Final score: `$1,211,212.093404`
- Unmet demand: `0.0 MWh`
- Controller errors: `0`
- Blackout penalty: `$0.00`
- Overvoltage penalty: `$0.00`
- FCAS shortfall penalty: `$0.00`

Compared with the copied starting point, score improved from `$9,307,219.835` to `$1,211,212.093404` by eliminating the dawn blackout.

## Level 2 Attempt 2

Command:

```bash
.venv/bin/python -m watt_the_hack.playtest submissions/level2_frequency_frenzy/attempt2_strategy.py --scenario frequency_frenzy --no-plots --quiet --out runs/level2_qp_polish_revalidate
```

Result:

- Final score: `$1,064,526.4041564139`
- Unmet demand: `0.0 MWh`
- Controller errors: `0`
- Blackout penalty: `$0.00`
- Ramp charge: `$8,553.6528`
- Demand charge: `$85,000.0012`
