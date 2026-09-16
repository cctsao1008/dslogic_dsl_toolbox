# dslogic_dsl_toolbox

Read-only Python toolbox for inspecting and extracting data from DSView / DSLogic `.dsl` capture files.

The implementation was developed and verified against **DSView v1.3.2 / DSL format v3** captures using a ZIP-based container with non-RLE, bit-packed logic streams.

## Features

- `info` — show capture metadata
- `check` — validate DSL block structure and channel byte counts
- `stats` — count transitions, rising edges, and falling edges
- `export-csv` — export a DSView/sigrok-style transition-list CSV
- `edges` — export edge timestamps for one channel
- `rpm` — convert selected edge timing + PPR into mechanical RPM
- `pwm` — decode HIGH PWM pulse width, frequency, duty, and optional command mapping
- `plot` — plot raw digital waveforms or a transition-rate overview
- `analyze_esc_response.py` — generate an ESC step-response report from throttle PWM + optical/tach RPM channels

The toolbox never modifies the source `.dsl` file.

## Requirements

Python 3.9+ is recommended.

Most commands use only the Python standard library. Plotting and report generation additionally require Matplotlib:

```powershell
py -m pip install matplotlib
```

## Basic usage

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

## RPM from PPR

The `rpm` command converts the interval between selected edges into mechanical RPM:

```text
RPM = 60 / (edge_interval_seconds * PPR)
RPM = 60 * edge_frequency_hz / PPR
```

### Canonical PPR definition

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

Recommended bounded example for an E61 optical-RPM capture:

```powershell
py .\dslogic_dsl_toolbox.py rpm .\capture.dsl `
  --channel CH0 `
  --edge falling `
  --ppr 1 `
  --min-edge-spacing-ms 6 `
  --rpm-sanity-max 10500 `
  -o .\rpm.csv
```

The RPM CSV contains:

```text
sample,time_s,dt_s,edge_frequency_hz,ppr,rpm
```

The short-interval filter always evaluates the interval between **adjacent raw selected edges**. Rejected edges are not merged with neighbors, avoiding false low-RPM samples from dense glitch bursts.

### RPM signal-quality guard

Toolbox `v1.2.0` adds a guard against producing plausible-looking RPM from a channel that is incompatible with the requested edge/PPR model.

The command reports:

```text
Selected edges
Valid RPM samples
Rejected short intervals
Rejected sanity-limit intervals
Rejected interval ratio
```

By default, the command fails if fewer than 3 valid RPM samples remain or if at least 99% of considered intervals are rejected.

Example failure:

```text
Selected edges          : 351,724
Valid RPM samples       : 2
Rejected interval ratio : 99.9994%

ERROR: RPM signal quality check failed ...
```

This is a strong indication that the selected channel is not compatible with the requested tach/RPM model, or that channel mapping / PPR / edge polarity is wrong.

For deliberate debugging only, override with:

```powershell
--allow-low-quality
```

The thresholds are configurable:

```powershell
--quality-reject-ratio 0.99 `
--min-valid-samples 3
```

If neither `--min-edge-spacing-ms` nor `--rpm-sanity-max` is set, the tool prints a note that no RPM plausibility limits are active.

## PWM / throttle decoding

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

## Plotting

### Raw waveform mode

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

### Overview mode for dense signals

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

Overview mode bins the capture and plots **transition rate (edges/s)** per channel. This makes dense switching/activity envelopes visible without rendering hundreds of thousands of vertical edges.

For channels with very different transition rates:

```powershell
--overview-log-y
```

## ESC step-response report

`analyze_esc_response.py` is the higher-level report generator. Channel mapping is explicit rather than guessed.

Example for throttle PWM on CH1 and one-marker optical RPM on CH0:

```powershell
py .\analyze_esc_response.py .\capture.dsl `
  --throttle-channel CH1 `
  --rpm-channel CH0 `
  --rpm-edge falling `
  --ppr 1 `
  --pwm-low-us 1000 `
  --pwm-high-us 1900 `
  --throttle-max-pct 90 `
  --min-edge-spacing-ms 6 `
  --rpm-sanity-max 10500 `
  --target-rpm 8800 `
  --step-direction rise `
  -o .\capture_response_report.png
```

Channel names stored in the DSL session may be used instead of numeric IDs:

```powershell
--throttle-channel THROTTLE --rpm-channel RPM
```

For captures containing multiple throttle transitions, use:

```text
--step-direction rise|fall|any
--step-index N
```

The report contains:

- response milestone table: first response, 10%, 63.2% (tau), 90%, 95%, settled
- KPI cards: 10–90% rise time, time to target RPM, steady-state RPM, overshoot
- RPM response and throttle command on a common time axis
- T0 and target-crossing markers

It also writes:

```text
*_rpm.csv
*_throttle_segments.csv
*_metrics.json
```

### Report RPM quality guard

`analyze_esc_response.py v1.1.0` applies the same RPM-signal quality principle before generating a performance report. A suspect channel is rejected before a misleading report is written.

Debug override:

```powershell
--allow-low-quality-rpm
```

The metrics JSON records the RPM quality statistics used by the report.

## Supported DSL layout

Current parser support is deliberately conservative:

- `.dsl` is a ZIP container
- metadata is stored in `header`, `session`, and optionally `decoders`
- channel sample streams are stored as `L-<channel>/<block>`
- logic samples are bit-packed LSB-first, eight samples per byte
- non-RLE captures are supported

RLE-compressed captures are detected and rejected instead of being silently mis-decoded.

## Architecture

```text
DSLogic .dsl
    |
    v
dslogic_dsl_toolbox.py
    |-- edges
    |-- RPM / PPR scaling + quality guard
    |-- PWM
    |-- transition CSV
    |-- waveform plot
    `-- transition-rate overview
    |
    v
analyze_esc_response.py
    |-- explicit throttle / RPM channel mapping
    |-- RPM signal-quality guard
    |-- throttle step selection
    |-- response milestones
    |-- rise / settling / overshoot metrics
    `-- report PNG + CSV / JSON sidecars
    |
    v
Other higher-level analyzers
    |-- ESC doublet response
    |-- BEMF / gate timing analysis
    `-- other project-specific analysis
```

Keeping raw-capture parsing separate from domain-specific analysis makes the toolbox reusable across motor-control, embedded, and general logic-analyzer workflows.

## Status

Toolbox version: `v1.2.0`

ESC response report generator: `v1.1.0`

Known limitation: DSView RLE-compressed `.dsl` captures are not yet supported.
