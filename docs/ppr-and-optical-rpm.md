# PPR and Optical RPM Measurement Definition

## Purpose

This note defines the canonical interpretation of PPR for optical RPM measurements used with `dslogic_dsl_toolbox.py`.

The key rule is:

> **PPR is the number of selected edge events detected per mechanical revolution.**

PPR is determined by the actual sensor / marker configuration and the selected edge polarity. It is not determined by blade count alone.

---

## RPM equations

For selected edge frequency `f_edge` in Hz:

```text
RPM = 60 * f_edge / PPR
```

For the interval `dt` in seconds between consecutive selected edges:

```text
RPM = 60 / (dt * PPR)
```

Use one edge mode consistently during a measurement:

- rising only,
- falling only, or
- both, with PPR adjusted accordingly.

---

## Configuration A — single reflective marker

Example physical setup:

```text
Two-blade propeller
Blade A : reflective marker
Blade B : no reflective marker
```

Only one reflective event is detected per mechanical revolution.

With one edge polarity selected:

```text
Detected pulses / revolution : 1
Selected edges / revolution  : 1
PPR                          : 1
```

Recommended command:

```powershell
py .\dslogic_dsl_toolbox.py rpm .\capture.dsl `
  --channel CH0 `
  --edge falling `
  --ppr 1 `
  -o .\rpm.csv
```

Reference values:

| RPM | Selected-edge frequency | Selected-edge interval |
|---:|---:|---:|
| 1,000 | 16.67 Hz | 60.00 ms |
| 3,000 | 50.00 Hz | 20.00 ms |
| 6,000 | 100.00 Hz | 10.00 ms |
| 8,800 | 146.67 Hz | 6.82 ms |

For the current single-reflective-marker measurement setup, this is the canonical configuration.

---

## Configuration B — both blade passages are detected

Example physical setup:

```text
Two-blade propeller
Both blade passages produce valid optical pulses
```

Two optical events are detected per mechanical revolution.

With one edge polarity selected:

```text
Detected pulses / revolution : 2
Selected edges / revolution  : 2
PPR                          : 2
```

Recommended command:

```powershell
py .\dslogic_dsl_toolbox.py rpm .\capture.dsl `
  --channel CH0 `
  --edge rising `
  --ppr 2 `
  -o .\rpm.csv
```

Reference values:

| RPM | Selected-edge frequency | Selected-edge interval |
|---:|---:|---:|
| 1,000 | 33.33 Hz | 30.00 ms |
| 3,000 | 100.00 Hz | 10.00 ms |
| 6,000 | 200.00 Hz | 5.00 ms |
| 8,800 | 293.33 Hz | 3.41 ms |

---

## Edge-mode effect on PPR

If a pulse train generates one HIGH pulse for every detected event:

```text
         rising              falling
            |                   |
            v                   v
___________|-------------------|___________
```

Then:

- `--edge rising` counts one edge per detected pulse,
- `--edge falling` counts one edge per detected pulse,
- `--edge both` counts two edges per detected pulse.

Examples:

| Detected pulses / rev | Edge mode | PPR |
|---:|---|---:|
| 1 | rising | 1 |
| 1 | falling | 1 |
| 1 | both | 2 |
| 2 | rising | 2 |
| 2 | falling | 2 |
| 2 | both | 4 |

Therefore, changing edge mode without changing PPR can produce a 2x RPM error.

---

## Step-response measurement contract

For PWM + optical-RPM step-response measurements, both signals should be captured on the same logic-analyzer time base.

Recommended channel assignment:

```text
CH0 : optical RPM pulse
CH1 : throttle PWM command
```

Channel numbers are not intrinsic requirements; tools should allow explicit channel selection.

Example:

```text
--rpm-channel CH0
--throttle-channel CH1
```

The physical setup determines PPR independently:

```text
Single reflective marker -> PPR = 1 for one selected edge polarity
Both blade passages       -> PPR = 2 for one selected edge polarity
```

For a 1000 us -> 1900 us throttle step:

```text
T0 = first 1900 us PWM command frame
```

For a target RPM such as 8800 RPM:

```text
Ttarget = first valid RPM sample reaching the target according to the analyzer's acceptance criteria
Response time = Ttarget - T0
```

Higher-level analyzers may add blanking, persistence, floor, sanity, or settling criteria. Those are analysis-policy parameters and are intentionally separate from the raw PPR conversion.

---

## Sanity checks before formal analysis

Before relying on calculated RPM:

1. Verify the actual marker / sensor configuration.
2. Verify how many valid pulses are produced per mechanical revolution.
3. Select a single edge polarity unless there is a deliberate reason to use both.
4. Set PPR to the number of selected edge events per mechanical revolution.
5. Compare calculated RPM against an independent displayed or expected RPM where possible.
6. Check for missing, duplicated, or noisy edges.
7. Keep throttle and RPM signals on the same capture time base for response-time analysis.

---

## Summary

```text
PPR != blade count

PPR = selected edge events detected per mechanical revolution

RPM = 60 * edge_frequency_hz / PPR
RPM = 60 / (edge_interval_seconds * PPR)
```

For the current single-reflective-marker setup:

```text
selected edge : rising OR falling
PPR           : 1
8800 RPM      : ~146.67 Hz
edge interval : ~6.82 ms
```
