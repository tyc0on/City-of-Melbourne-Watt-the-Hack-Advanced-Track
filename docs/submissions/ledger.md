# Submission Ledger

## Level 2 - Frequency Frenzy

Artifact: `submissions/level2_frequency_frenzy/attempt1_strategy.py`

Local scenario: `frequency_frenzy`

Latest WSL2 confirmation:

- Date: 2026-06-06
- Run: `runs/level2_laptop_final`
- Final score: `$1,211,212.093404`
- Unmet demand: `0.0 MWh`
- Controller errors: `0`
- Notes: reliability fix for dawn heating spike plus tuned high-price shaving constants.

Artifact: `submissions/level2_frequency_frenzy/attempt2_strategy.py`

Latest WSL2 confirmation:

- Date: 2026-06-06
- Run: `runs/level2_attempt2_lp_final`
- Final score: `$1,066,497.4480180626`
- Unmet demand: `0.0 MWh`
- Controller errors: `0`
- Notes: open-loop LP dispatch with hard ramp cap, embedded as a guarded schedule. Beats the reported server best `$1,074,665.84` by about `$8,168`.
