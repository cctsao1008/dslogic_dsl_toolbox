# Toolbox Reference

This document covers the generic DSLogic / DSView `.dsl` utilities provided by `dslogic_dsl_toolbox.py`.

## Requirements

Python 3.9+ is recommended.

Most commands use only the Python standard library. Plotting requires Matplotlib:

```powershell
py -m pip install matplotlib
```

## Supported DSL layout

Current parser support is intentionally conservative:

- `.dsl` is a ZIP container;
- metadata is stored in `header`, `session`, and optionally `decoders`;
- channel sample streams are stored as `L-<channel>/<block>`;
- logic samples are bit-packed LSB-first, eight samples per byte;
- non-RLE captures are supported.

RLE-compressed captures are detected and rejected rather than silently mis-decoded.

The implementation has been verified against DSView v1.3.2 / DSL format v3 captures.

## Command overview

```text
info         show capture metadata
check        validate DSL block structure and channel byte counts
stats        count transitions, rising edges, and falling edges
export-csv   export DSView/sigrok-style transition-list CSV
edges        export selected edge timestamps
rpm          convert selected edge timing + PPR into mechanical RPM
pwm          decode PWM width, frequency, duty, and optional command mapping
plot         draw raw digital waveforms or a transition-rate overview
```

## Basic inspection

```powershell
py .\dslogic_dsl_toolbox.py info .\capture.dsl
py .\dslogic_dsl_toolbox.py check .\capture.dsl
py .\dslogic_dsl_toolbox.py stats .\capture.dsl
```

## Transition-list CSV export

```powershell
py .\dslogic_dsl_toolbox.py export-csv .\capture.dsl `
  -o .\capture_from_dsl.csv
```

The export preserves the logic-state transition timeline rather than expanding the capture into one row per raw sample.

## Edge export

Example for CH0 falling edges:

```powershell
py .\dslogic_dsl_toolbox.py edges .\capture.dsl `
  --channel CH0 `
  --edge falling `
  -o .\ch0_falling.csv
```

A time window may also be selected with `--start-s` and `--end-s`.

## RPM conversion

Mechanical RPM is calculated as:

```text
RPM = 60 / (edge_interval_seconds * PPR)
RPM = 60 * edge_frequency_hz / PPR
```

Example:

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

### PPR semantics

PPR means selected edge events per mechanical revolution. It is not simply blade count.

See [PPR and Optical RPM Measurement Definition](ppr-and-optical-rpm.md).

### Interval handling

The short-interval filter evaluates intervals between adjacent raw selected edges. Rejected intervals are not bridged with neighboring edges, which avoids manufacturing false low-RPM samples from dense glitch bursts.

### RPM quality guard

The `rpm` command reports:

```text
Selected edges
Valid RPM samples
Rejected short intervals
Rejected sanity-limit intervals
Rejected interval ratio
```

When plausibility limits are active, the command can reject a signal that is incompatible with the requested RPM/PPR model.

If neither `--min-edge-spacing-ms` nor `--rpm-sanity-max` is active, plausibility is considered unchecked.

Debug override:

```powershell
--allow-low-quality
```

## PWM decoding

Example: decode an ESC-style PWM command on CH1 and map 1000–1900 us to 0–90%:

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

Typical output includes:

- valid pulse count;
- HIGH-width median and range;
- PWM period and frequency;
- optional mapped command percentage;
- stable command segments.

## Digital plotting

### Raw waveform mode

```powershell
py .\dslogic_dsl_toolbox.py plot .\capture.dsl `
  --channels CH0 CH1 `
  --start-s 0 `
  --end-s 6 `
  -o .\window.png
```

Raw waveform mode limits the number of rendered transitions per channel to avoid producing unusable plots.

The transition limit may be overridden explicitly:

```powershell
--max-transitions 300000
```

### Overview mode

For dense or long-duration signals, use transition-rate overview mode:

```powershell
py .\dslogic_dsl_toolbox.py plot .\capture.dsl `
  --channels CH0 CH1 `
  --start-s 12.5 `
  --end-s 18.5 `
  --plot-mode overview `
  --overview-bins 800 `
  -o .\overview.png
```

Overview mode bins the selected interval and plots transition rate in edges/s instead of drawing every edge.

For channels with very different activity levels:

```powershell
--overview-log-y
```

## Architecture boundary

`dslogic_dsl_toolbox.py` is the raw-capture / generic-signal layer. Project-specific interpretation should stay in higher-level tools.

```text
DSLogic / DSView .dsl
        |
        v
dslogic_dsl_toolbox.py
        |
        |-- metadata / validation
        |-- transition / edge extraction
        |-- PPR -> RPM conversion
        |-- PWM decoding
        |-- CSV export
        |-- raw waveform plotting
        `-- transition-rate overview
        |
        v
higher-level analysis / visualization
```

The current ESC-specific high-level tool is `plot_esc_step_response.py`; see [ESC Step-Response Workflow](step-response.md).
