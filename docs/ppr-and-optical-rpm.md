# PPR and Optical RPM Measurement Definition

## Purpose

This note defines the canonical interpretation of PPR for optical / tachometer RPM measurements used by this repository.

> **PPR is the number of selected edge events detected per mechanical revolution.**

PPR is determined by the actual sensor / marker configuration and the selected edge polarity. It is **not** determined by blade count alone.

## RPM equations

For selected-edge frequency `f_edge` in Hz:

```text
RPM = 60 * f_edge / PPR
```

For the interval `dt` in seconds between consecutive selected edges:

```text
RPM = 60 / (dt * PPR)
```

Use one edge mode consistently during a measurement:

- rising only;
- falling only; or
- both, with PPR adjusted accordingly.

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

Reference values:

| RPM | Selected-edge frequency | Selected-edge interval |
|---:|---:|---:|
| 1,000 | 16.67 Hz | 60.00 ms |
| 3,000 | 50.00 Hz | 20.00 ms |
| 6,000 | 100.00 Hz | 10.00 ms |
| 8,800 | 146.67 Hz | 6.82 ms |

For the current single-reflective-marker measurement setup, this is the canonical configuration.

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

Reference values:

| RPM | Selected-edge frequency | Selected-edge interval |
|---:|---:|---:|
| 1,000 | 33.33 Hz | 30.00 ms |
| 3,000 | 100.00 Hz | 10.00 ms |
| 6,000 | 200.00 Hz | 5.00 ms |
| 8,800 | 293.33 Hz | 3.41 ms |

## Edge-mode effect on PPR

If one detected event produces one HIGH pulse:

```text
         rising              falling
            |                   |
            v                   v
___________|-------------------|___________
```

Then:

- `rising` counts one edge per detected pulse;
- `falling` counts one edge per detected pulse;
- `both` counts two edges per detected pulse.

| Detected pulses / rev | Edge mode | PPR |
|---:|---|---:|
| 1 | rising | 1 |
| 1 | falling | 1 |
| 1 | both | 2 |
| 2 | rising | 2 |
| 2 | falling | 2 |
| 2 | both | 4 |

Changing edge mode without changing PPR can therefore create a 2x RPM error.

## Generic toolbox usage

The low-level toolbox allows explicit channel selection:

```powershell
py .\dslogic_dsl_toolbox.py rpm .\capture.dsl `
  --channel CH0 `
  --edge falling `
  --ppr 1 `
  -o .\rpm.csv
```

This generic command is intentionally reusable beyond the fixed ESC measurement wiring.

## ESC step-response measurement contract

`plot_esc_step_response.py` uses a fixed measurement contract:

```text
CH0 = Tachometer PULSE output
CH1 = ESC PWM command input
CH2 = unused
CH3 = unused
```

Both CH0 and CH1 are captured on the same logic-analyzer time base.

For a PWM step:

```text
T0 = selected throttle-command transition
```

For a target such as 8800 RPM:

```text
Ttarget = first valid sustained target-RPM crossing
Response time = Ttarget - T0
```

Pulse-width qualification, RPM plausibility limits, target persistence, and plot smoothing are analysis-policy parameters. They are intentionally separate from the PPR definition itself.

See [ESC Step-Response Workflow](step-response.md) for the current measurement pipeline.

## Sanity checks before formal analysis

Before relying on calculated RPM:

1. Verify the actual marker / sensor configuration.
2. Verify how many valid pulses are produced per mechanical revolution.
3. Select one edge polarity unless there is a deliberate reason to use both.
4. Set PPR to the number of selected edge events per mechanical revolution.
5. Check for narrow glitches, missing pulses, or duplicated pulses.
6. Compare calculated RPM against an independent displayed or expected RPM where possible.
7. Keep command and tachometer signals on the same capture time base for response-time analysis.

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
