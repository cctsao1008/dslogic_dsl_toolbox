# dslogic_dsl_toolbox

Read-only Python toolbox for inspecting, extracting, and analyzing DSView / DSLogic `.dsl` capture files.

The implementation was developed and verified against **DSView v1.3.2 / DSL format v3** captures using a ZIP-based container with non-RLE, bit-packed logic streams.

The toolbox is intentionally split into two layers:

- **raw capture / signal tools** in `dslogic_dsl_toolbox.py`
- **ESC step-response visualization** in `plot_esc_step_response.py`

`analyze_esc_response.py` remains available as an extended / legacy analysis path for milestone tables, KPI cards, and sidecar metrics.

The toolbox never modifies the source `.dsl` file.

---

## Features

### `dslogic_dsl_toolbox.py`

- `info` — show capture metadata
- `check` — validate DSL block structure and channel byte counts
- `stats` — count transitions, rising edges, and falling edges
- `export-csv` — export a DSView/sigrok-style transition-list CSV
- `edges` — export edge timestamps for one channel
- `rpm` — convert selected edge timing + PPR into mechanical RPM
- `pwm` — decode HIGH PWM pulse width, frequency, duty, and optional command mapping
- `plot` — plot raw digital waveforms or a transition-rate overview

### `plot_esc_step_response.py` — recommended ESC workflow

- fixed measurement contract: **CH0 = tachometer PULSE, CH1 = ESC PWM command**
- optional tach-pulse width qualification before RPM conversion
- PPR-based mechanical RPM conversion
- RPM plausibility filtering
- unsmoothed target-RPM timing detection
- independent median filtering for plotted RPM only
- PWM display as `us` or mapped `%`
- independent throttle-T and RPM-T handling: `auto`, `manual`, or `none`
- optional RPM Y-axis limits
- single publication-ready step-response figure

### `analyze_esc_response.py` — extended / legacy analysis

- configurable channel mapping
- response milestone table
- 10–90% rise time
- settling time
- overshoot
- target-RPM timing
- CSV / JSON sidecars

---

## Requirements

Python 3.9+ is recommended.

Most commands use only the Python standard library. Plotting requires Matplotlib:

```powershell
py -m pip install matplotlib
```

---

# Basic DSL usage

```powershell
py .\dslogic_dsl_toolbox.py info .\capture.dsl
py .\dslogic_dsl_toolbox.py check .\capture.dsl
py .\dslogic_dsl_toolbox.py stats .\capture.dsl
```

Export a transition-list CSV:

```powershell
py .\dslogic_dsl_toolbox.py export-csv .\capture.dsl `
  -o .\capture_from_dsl.csv
```

Export falling edges from CH0:

```powershell
py .\dslogic_dsl_toolbox.py edges .\capture.dsl `
  --channel CH0 `
  --edge falling `
  -o .\ch0_falling.csv
```

---

# RPM from PPR

The `rpm` command converts the interval between selected edges into mechanical RPM:

```text
RPM = 60 / (edge_interval_seconds * PPR)
RPM = 60 * edge_frequency_hz / PPR
```

## Canonical PPR definition

`PPR` means **selected edge events per mechanical revolution**.

PPR must come from the events that the sensor actually produces per mechanical revolution for the selected edge mode. It must **not** be inferred from propeller blade count alone.

| Physical setup | Selected edge mode | Events / rev | `--ppr` |
|---|---|---:|---:|
| Two-blade propeller, reflective marker on one blade only | rising | 1 | 1 |
| Two-blade propeller, reflective marker on one blade only | falling | 1 | 1 |
| Optical sensor detects both blade passages | rising | 2 | 2 |
| Optical sensor detects both blade passages | falling | 2 | 2 |
| One detected pulse/rev, both edges counted | both | 2 | 2 |
| Two detected pulses/rev, both edges counted | both | 4 | 4 |

For the current single-reflective-marker setup:

```text
Propeller          : two-blade
Reflective markers : one marker on one blade
Selected edge      : rising OR falling
PPR                : 1
```

At 8800 RPM:

```text
edge frequency ~= 146.67 Hz
edge interval  ~= 6.82 ms
```

If both blades are actually detected with one selected edge polarity, use `PPR = 2`; at 8800 RPM the corresponding edge interval is about 3.41 ms.

See [`docs/ppr-and-optical-rpm.md`](docs/ppr-and-optical-rpm.md).

Basic example:

```powershell
py .\dslogic_dsl_toolbox.py rpm .\capture.dsl `
  --channel CH0 `
  --edge falling `
  --ppr 1 `
  -o .\rpm.csv
```

A bounded example:

```powershell
py .\dslogic_dsl_toolbox.py rpm .\capture.dsl `
  --channel CH0 `
  --edge falling `
  --ppr 1 `
  --rpm-sanity-max 10500 `
  -o .\rpm.csv
```

The RPM CSV contains:

```text
sample,time_s,dt_s,edge_frequency_hz,ppr,rpm
```

The short-interval filter evaluates the interval between **adjacent raw selected edges**. Rejected edges are not bridged with neighbors, avoiding false low-RPM samples from dense glitch bursts.

## RPM signal-quality guard

The toolbox can guard against producing plausible-looking RPM from a signal that is incompatible with the requested edge/PPR model.

The command reports:

```text
Selected edges
Valid RPM samples
Rejected short intervals
Rejected sanity-limit intervals
Rejected interval ratio
```

If neither `--min-edge-spacing-ms` nor `--rpm-sanity-max` is active, RPM plausibility is considered **unchecked**.

For deliberate debugging only, the quality guard can be overridden with:

```powershell
--allow-low-quality
```

---

# PWM / throttle decoding

Example: decode an ESC-style PWM command on CH1, mapping 1000–1900 us to 0–90%:

```powershell
py .\dslogic_dsl_toolbox.py pwm .\capture.dsl `
  --channel CH1 `
  --min-us 500 `
  --max-us 2500 `
  --map-low-us 1000 `
  --map-high-us 1900 `
  --map-max-pct 90 `
  --show-segments `
  -o .\throttle.csv
```

---

# Generic digital plotting

## Raw waveform mode

```powershell
py .\dslogic_dsl_toolbox.py plot .\capture.dsl `
  --channels CH0 CH1 `
  --start-s 0 `
  --end-s 6 `
  -o .\window.png
```

Raw waveform mode protects against rendering an excessive number of transitions. The default limit is 200,000 transitions per channel.

The limit may be explicitly raised:

```powershell
--max-transitions 300000
```

## Overview mode for dense signals

For long windows or high-transition-rate channels, use overview mode instead of drawing every edge:

```powershell
py .\dslogic_dsl_toolbox.py plot .\capture.dsl `
  --channels CH0 CH1 `
  --start-s 12.5 `
  --end-s 18.5 `
  --plot-mode overview `
  --overview-bins 800 `
  -o .\overview.png
```

Overview mode bins the capture and plots **transition rate (edges/s)** per channel.

For channels with very different transition rates:

```powershell
--overview-log-y
```

---

# ESC step-response plotting

`plot_esc_step_response.py` is the recommended high-level ESC plotting tool.

## Measurement contract

```text
CH0 = Tachometer PULSE output
CH1 = ESC command PWM input
CH2 = unused
CH3 = unused
```

The channel mapping is intentionally fixed for this workflow. The user normally only configures:

```text
PPR
RPM edge polarity
PWM display units
filter / qualification limits
timing mode
plot limits
```

## Signal-processing pipeline

```text
CH0 tach signal
    |
    v
optional pulse-width qualification
    |
    v
valid tach events
    |
    v
PPR + edge interval -> raw RPM
    |
    +----> target-RPM timing detection
    |       raw valid samples only
    |       no smoothing
    |
    `----> median filter -> plotted RPM curve

CH1 PWM
    |
    v
Ton decode
    |
    +----> raw microseconds
    `----> mapped command percent
```

The separation between timing and visualization is deliberate:

- **target timing uses unsmoothed valid RPM samples**
- **median filtering affects only the plotted RPM curve**

This avoids moving `Ttarget` merely to make the curve look smoother.

---

## Recommended command

This command corresponds to the currently validated E61-style setup:

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

### Latest validated result

For the current validated capture, the command above produced:

```text
Tach pulse qualification: LOW 100..400 us | candidates=2,038, qualified=1,750, rejected=288
RPM quality: CHECKED | valid=1,749, interval-rejected=0.0000%
RPM timing source: raw valid samples (unsmoothed)
RPM plot filter: median window=3
Throttle step: 1010.2 -> 1900.4 us (1.02% -> 90.04%) @ 1.598512 s
RPM target T: 1.880450 s; elapsed from throttle T: 0.281937 s
```

Therefore:

```text
Throttle T0       = 1.598512 s
8800-RPM T        = 1.880450 s
Time to 8800 RPM  = 0.281937 s ~= 0.282 s
```

This example also confirms that pulse qualification removes narrow tach glitches **before** RPM conversion while preserving the measured 8800-RPM timing.

---

## Tach pulse-width qualification

Optional tach pulse qualification can reject narrow glitches before they become RPM samples.

Example:

```powershell
--tach-pulse-level low `
--tach-pulse-min-us 100 `
--tach-pulse-max-us 400
```

Conceptually:

```text
falling edge
    |
    v
LOW pulse width check
    |
    +-- reject implausible glitch pulse
    |
    `-- accept valid tach pulse
             |
             v
      pulse-to-pulse interval
             |
             v
            RPM
```

Qualification is disabled unless a pulse-width bound is supplied.

Use values derived from the actual tachometer pulse-output definition or observed valid pulse widths; do not assume that `100..400 us` applies universally.

---

## RPM filtering

### Physical plausibility / validity

Example:

```powershell
--rpm-sanity-max 10500
```

This rejects derived RPM values above the configured physical limit.

`--min-edge-spacing-ms` is also available for explicit raw-edge interval rejection, but a physical RPM limit and/or tach pulse-width qualification is generally easier to interpret.

### Plot smoothing

```powershell
--rpm-median-window 3
```

Median filtering is applied to the plotted RPM trace only.

Disable plot smoothing with:

```powershell
--rpm-median-window 1
```

---

## Throttle command axis

Raw PWM width:

```powershell
--pwm-axis us
```

Mapped command percentage:

```powershell
--pwm-axis percent `
--pwm-low-us 1000 `
--pwm-high-us 1900 `
--pwm-max-pct 90
```

Mapping:

```text
command_pct = (Ton - pwm_low_us)
              / (pwm_high_us - pwm_low_us)
              * pwm_max_pct
```

For the current mapping:

```text
1000 us -> 0%
1500 us -> 50%
1700 us -> 70%
1900 us -> 90%
```

---

## Throttle-T handling

```text
--throttle-t auto
--throttle-t manual
--throttle-t none
```

### Auto

Detect a stable PWM command transition and align that point to `t = 0`.

```powershell
--throttle-t auto `
--step-direction rise `
--step-index 0
```

Small segment changes can be ignored with:

```powershell
--min-step-us 100
```

### Manual

```powershell
--throttle-t manual `
--throttle-t-s 1.598512
```

`--throttle-t-s` uses absolute capture time.

### None

```powershell
--throttle-t none
```

The X axis remains absolute capture time.

---

## RPM target-T handling

```text
--rpm-t auto
--rpm-t manual
--rpm-t none
```

### Auto

Find a sustained target-RPM crossing using valid, unsmoothed RPM samples:

```powershell
--rpm-t auto `
--target-rpm 8800 `
--target-hold-ms 100 `
--target-min-samples 3
```

### Manual

```powershell
--rpm-t manual `
--rpm-t-s 1.880450
```

### None

```powershell
--rpm-t none
```

No target-time annotation is added.

---

## RPM Y-axis limits

Automatic scaling is used by default.

Optional fixed limits:

```powershell
--rpm-y-min 0 `
--rpm-y-max 10000
```

This is useful when comparing multiple ESC captures with a common RPM scale.

---

# Extended response analysis

`analyze_esc_response.py` remains available when a full report rather than a single response figure is needed.

It supports:

- configurable throttle / RPM channel mapping
- first response
- 10%
- 63.2% / time constant
- 90%
- 95%
- settling
- 10–90% rise time
- overshoot
- target-RPM time
- RPM CSV
- throttle-segment CSV
- metrics JSON

Example:

```powershell
py .\analyze_esc_response.py .\capture.dsl `
  --throttle-channel CH1 `
  --rpm-channel CH0 `
  --rpm-edge falling `
  --ppr 1 `
  --rpm-sanity-max 10500 `
  --target-rpm 8800 `
  --step-direction rise `
  -o .\capture_response_report.png
```

The single-figure `plot_esc_step_response.py` is preferred for current ESC step-response visualization.

---

# Supported DSL layout

Current parser support is deliberately conservative:

- `.dsl` is a ZIP container
- metadata is stored in `header`, `session`, and optionally `decoders`
- channel sample streams are stored as `L-<channel>/<block>`
- logic samples are bit-packed LSB-first, eight samples per byte
- non-RLE captures are supported

RLE-compressed captures are detected and rejected instead of being silently mis-decoded.

---

# Architecture

```text
DSLogic / DSView .dsl
        |
        v
dslogic_dsl_toolbox.py
        |
        |-- metadata / validation
        |-- edge extraction
        |-- RPM / PPR conversion
        |-- PWM decoding
        |-- CSV export
        |-- raw waveform plotting
        `-- transition-rate overview
        |
        +-----------------------------+
        |                             |
        v                             v
plot_esc_step_response.py     analyze_esc_response.py
        |                             |
        |-- CH0 tach contract         |-- extended metrics
        |-- CH1 PWM contract          |-- milestone table
        |-- tach qualification        |-- KPI report
        |-- raw timing path           `-- CSV / JSON sidecars
        |-- plot filter path
        `-- single response PNG
```

Keeping raw-capture parsing separate from domain-specific analysis makes the toolbox reusable across motor-control, embedded, and general logic-analyzer workflows.

---

# Status

```text
dslogic_dsl_toolbox.py      : v1.2.0
plot_esc_step_response.py   : v1.4.0
analyze_esc_response.py     : v1.1.0
```

Known limitation:

- DSView RLE-compressed `.dsl` captures are not yet supported.
