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
- `plot` — plot selected digital channels over a chosen time range

The toolbox is intentionally read-only and never modifies the source `.dsl` file.

## Requirements

Python 3.9+ is recommended.

Most commands use only the Python standard library. Plotting additionally requires Matplotlib:

```powershell
py -m pip install matplotlib
```

## Usage

Show capture information:

```powershell
py .\dslogic_dsl_toolbox.py info .\capture.dsl
```

Validate the capture:

```powershell
py .\dslogic_dsl_toolbox.py check .\capture.dsl
```

Show channel statistics:

```powershell
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
```

Equivalent frequency form:

```text
RPM = 60 * edge_frequency_hz / PPR
```

`PPR` means **selected edge events per mechanical revolution**. For example, if a tachometer produces one pulse per revolution and only falling edges are selected, use `--ppr 1`. If both rising and falling edges are selected for that same pulse train, use `--ppr 2`.

Basic example:

```powershell
py .\dslogic_dsl_toolbox.py rpm .\capture.dsl `
  --channel CH0 `
  --edge falling `
  --ppr 1 `
  -o .\rpm.csv
```

Optional filtering for noisy edge captures:

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

The short-interval filter is applied to each interval between **adjacent raw selected edges**. Rejected intervals are not merged with neighboring intervals; this avoids creating false low-frequency/RPM samples from dense glitch bursts.

Decode an ESC-style PWM command on CH1, mapping 1000–1900 us to 0–90%:

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

Plot a selected time window:

```powershell
py .\dslogic_dsl_toolbox.py plot .\capture.dsl `
  --channels CH0 CH1 `
  --start-s 12.5 `
  --end-s 18.5 `
  -o .\window.png
```

## Supported DSL layout

Current parser support is deliberately conservative:

- `.dsl` is a ZIP container
- metadata is stored in `header`, `session`, and optionally `decoders`
- channel sample streams are stored as `L-<channel>/<block>`
- logic samples are bit-packed LSB-first, eight samples per byte
- non-RLE captures are supported

RLE-compressed captures are detected and rejected instead of being silently mis-decoded.

## Design principle

This repository is intended to be the **measurement extraction layer**, not an application-specific ESC analyzer.

```text
DSLogic .dsl
    |
    v
dslogic_dsl_toolbox.py
    |-- edges
    |-- RPM / PPR scaling
    |-- PWM
    |-- transition CSV
    |-- waveform plot
    |
    v
Higher-level analyzers
    |-- ESC step response
    |-- ESC doublet response
    |-- BEMF / gate timing analysis
    `-- other project-specific analysis
```

Keeping raw-capture parsing separate from domain-specific analysis makes the toolbox reusable across motor-control, embedded, and general logic-analyzer workflows.

## Status

Current version: `v1.1.0`

Known limitation: DSView RLE-compressed `.dsl` captures are not yet supported.
