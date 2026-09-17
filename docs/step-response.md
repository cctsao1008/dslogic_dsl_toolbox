# ESC Step-Response Workflow

This document describes the current high-level ESC workflow implemented by `plot_esc_step_response.py`.

The goal is deliberately narrow: generate one engineering plot that overlays mechanical RPM and ESC command on a common time base, with optional automatic timing from the throttle step to a target RPM.

## Measurement contract

The step-response plotter uses a fixed wiring contract:

```text
CH0 = Tachometer PULSE output
CH1 = ESC PWM command input
CH2 = unused
CH3 = unused
```

The fixed mapping is intentional. It removes channel-selection ambiguity from the formal ESC measurement path.

`plot_esc_step_response.py` currently decodes PWM on CH1. DShot decoding is not implemented in this plotter yet.

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
PPR + event interval -> raw RPM
    |
    +----> target-RPM timing detection
    |       valid unsmoothed RPM samples
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

- target timing uses valid, unsmoothed RPM samples;
- median filtering affects only the plotted RPM curve.

This prevents plot smoothing from moving `Ttarget`.

## Recommended command

The following command matches the currently validated single-reflective-marker setup:

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

The `100..400 us` tach qualification window is an observed valid range for the current setup. It is not a universal tachometer setting.

## Validated example

The command above produced:

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

The important observation is that pulse qualification removes narrow tach glitches before RPM conversion while preserving the measured target-RPM timing.

## Tach pulse-width qualification

Tach pulse qualification is optional and occurs before RPM conversion.

Example:

```powershell
--tach-pulse-level low `
--tach-pulse-min-us 100 `
--tach-pulse-max-us 400
```

Conceptually:

```text
selected tach pulse
      |
      v
pulse-width check
      |
      +-- reject implausible glitch
      |
      `-- accept valid tach event
               |
               v
      event-to-event interval
               |
               v
              RPM
```

Qualification is disabled unless a pulse-width bound is provided. Configure the bounds from the tachometer output definition or from verified valid pulses.

## RPM validity and smoothing

### Physical plausibility

Use a physical RPM ceiling when one is known:

```powershell
--rpm-sanity-max 10500
```

Derived RPM values above that limit are rejected.

`--min-edge-spacing-ms` is also available for explicit interval rejection, but an RPM ceiling and/or tach pulse-width qualification is usually easier to interpret physically.

### Plot smoothing

```powershell
--rpm-median-window 3
```

The median filter is applied only to the displayed RPM trace. Target timing remains based on valid unsmoothed RPM samples.

Disable plot smoothing with:

```powershell
--rpm-median-window 1
```

## Target-RPM timing

`--rpm-t` controls whether a target-RPM time is detected, supplied manually, or omitted:

```text
--rpm-t auto
--rpm-t manual
--rpm-t none
```

### Auto

```powershell
--rpm-t auto `
--target-rpm 8800 `
--target-hold-ms 100 `
--target-min-samples 3
```

The target crossing must satisfy the configured persistence criteria.

### Manual

```powershell
--rpm-t manual `
--rpm-t-s 1.880450
```

`--rpm-t-s` is absolute capture time.

### None

```powershell
--rpm-t none
```

No target-time annotation is generated.

## Throttle-step timing

`--throttle-t` independently controls throttle-step timing:

```text
--throttle-t auto
--throttle-t manual
--throttle-t none
```

### Auto

```powershell
--throttle-t auto `
--step-direction rise `
--step-index 0
```

Small PWM segment changes may be ignored with:

```powershell
--min-step-us 100
```

The detected throttle step becomes `t = 0` on the plot.

### Manual

```powershell
--throttle-t manual `
--throttle-t-s 1.598512
```

### None

```powershell
--throttle-t none
```

The X axis remains absolute capture time.

## PWM display axis

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

## RPM Y-axis limits

Automatic Y-axis scaling is used by default.

Use fixed limits for comparison plots:

```powershell
--rpm-y-min 0 `
--rpm-y-max 10000
```

## PPR

PPR is defined as selected edge events per mechanical revolution. It must follow the actual sensor/marker configuration and selected edge polarity.

See [PPR and Optical RPM Measurement Definition](ppr-and-optical-rpm.md).

## Output philosophy

The primary deliverable is a single figure containing:

- mechanical RPM response;
- PWM command as a dashed grey line;
- throttle-step-relative time when enabled;
- target-RPM reference line;
- target-RPM timing annotation when enabled.

The plotter intentionally does not generate the superseded milestone/KPI dashboard layout.
