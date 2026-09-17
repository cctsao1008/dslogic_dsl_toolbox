# dslogic_dsl_toolbox

Read-only Python toolbox for inspecting DSView / DSLogic `.dsl` captures and generating ESC step-response plots directly from raw logic-analyzer data.

The repository is intentionally split into two layers:

- `dslogic_dsl_toolbox.py` — generic `.dsl` parsing and signal utilities
- `plot_esc_step_response.py` — the current ESC step-response workflow

The source `.dsl` file is never modified.

## What it does

`dslogic_dsl_toolbox.py` provides:

- capture metadata and structure validation;
- transition / edge extraction;
- transition-list CSV export;
- PPR-to-RPM conversion;
- PWM decoding;
- raw waveform plotting;
- transition-rate overview plotting.

`plot_esc_step_response.py` provides:

- fixed ESC measurement wiring;
- optional tach pulse-width qualification;
- mechanical RPM conversion from tach pulses + PPR;
- RPM plausibility filtering;
- independent throttle-T and target-RPM-T handling;
- unsmoothed target timing with independently filtered display data;
- PWM display as microseconds or mapped percent;
- a single engineering step-response figure.

## Requirements

Python 3.9+ is recommended.

Most toolbox commands use only the standard library. Plotting requires Matplotlib:

```powershell
py -m pip install matplotlib
```

## Quick start

Inspect a capture:

```powershell
py .\dslogic_dsl_toolbox.py info .\capture.dsl
py .\dslogic_dsl_toolbox.py check .\capture.dsl
py .\dslogic_dsl_toolbox.py stats .\capture.dsl
```

Generate the currently validated ESC step-response plot:

```powershell
py .\plot_esc_step_response.py .\capture.dsl `
  --ppr 1 `
  --rpm-edge falling `
  --tach-pulse-level low `
  --tach-pulse-min-us 100 `
  --tach-pulse-max-us 400 `
  --rpm-sanity-max 10500 `
  --rpm-median-window 3 `
  --target-rpm 8800 `
  --target-hold-ms 100 `
  --target-min-samples 3 `
  --pwm-axis percent `
  --throttle-t auto `
  --rpm-t auto `
  --rpm-y-min 0 `
  --rpm-y-max 10000 `
  -o .\step_response.png
```

Current step-response wiring contract:

```text
CH0 = Tachometer PULSE output
CH1 = ESC PWM command input
CH2 = unused
CH3 = unused
```

The plotter currently decodes PWM on CH1. DShot decoding is not implemented in this high-level plotter yet.

## Current validated result

For the current single-reflective-marker capture and the command above:

```text
Tach pulse qualification: LOW 100..400 us | candidates=2,038, qualified=1,750, rejected=288
RPM quality: CHECKED | valid=1,749, interval-rejected=0.0000%
RPM timing source: raw valid samples (unsmoothed)
RPM plot filter: median window=3
Throttle step: 1010.2 -> 1900.4 us (1.02% -> 90.04%) @ 1.598512 s
RPM target T: 1.880450 s; elapsed from throttle T: 0.281937 s
```

Result:

```text
Time to 8800 RPM = 0.281937 s ~= 0.282 s
```

The tach pulse qualification removes narrow glitches before RPM conversion; the target timing is still measured from valid unsmoothed RPM samples.

## Documentation

Detailed usage and design notes live under `docs/`:

- [ESC Step-Response Workflow](docs/step-response.md) — timing modes, pulse qualification, filtering, PWM axis, plotting, and validated example
- [Toolbox Reference](docs/toolbox-reference.md) — generic `.dsl` commands, RPM/PWM utilities, plotting, and supported DSL layout
- [PPR and Optical RPM Measurement Definition](docs/ppr-and-optical-rpm.md) — canonical PPR semantics and optical/tach RPM equations

## Architecture

```text
DSLogic / DSView .dsl
        |
        v
dslogic_dsl_toolbox.py
        |
        |-- metadata / validation
        |-- transitions / edges
        |-- PPR -> RPM
        |-- PWM decode
        |-- CSV export
        `-- waveform / overview plot
        |
        v
plot_esc_step_response.py
        |
        |-- CH0 tach pulse qualification
        |-- CH1 PWM command
        |-- target timing from raw valid RPM
        |-- median-filtered RPM visualization
        `-- single step-response PNG
```

## Supported capture format

The parser has been verified against **DSView v1.3.2 / DSL format v3** captures using a ZIP-based, non-RLE, bit-packed sample layout.

RLE-compressed `.dsl` captures are detected and rejected rather than silently mis-decoded.

See [Toolbox Reference](docs/toolbox-reference.md) for the detailed layout.

## Status

```text
dslogic_dsl_toolbox.py      : v1.2.0
plot_esc_step_response.py   : v1.4.0
```
