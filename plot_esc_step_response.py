#!/usr/bin/env python3
"""Plot a single ESC step-response figure from a DSLogic/DSView .dsl capture.

Measurement contract:
  CH0 = tachometer pulse output
  CH1 = ESC command input (PWM in this plotter)
  CH2/CH3 = unused

Timing markers are independently configurable:
  --throttle-t auto|manual|none
  --rpm-t      auto|manual|none

PWM display units are independently configurable:
  --pwm-axis us|percent
"""

import argparse
import statistics
import sys
from pathlib import Path

from dslogic_dsl_toolbox import DSL, DSLError, pulse_iter, span

VERSION = "1.2.0"
RPM_CH = "CH0"
COMMAND_CH = "CH1"


def median_filter(rows, window):
    if window <= 1:
        return rows
    if window % 2 == 0:
        window += 1
    half = window // 2
    vals = [r[1] for r in rows]
    out = []
    for i, row in enumerate(rows):
        lo = max(0, i - half)
        hi = min(len(rows), i + half + 1)
        out.append((row[0], statistics.median(vals[lo:hi]), row[2], row[3]))
    return out


def decode_pwm(s, a):
    idx, name = s.resolve(COMMAND_CH)
    st, en = span(s, a.start_s, a.end_s)
    pulses = list(pulse_iter(s, idx, st, en, a.pwm_min_us, a.pwm_max_us))
    if not pulses:
        raise DSLError(f"No valid PWM command pulses on {COMMAND_CH} ({name})")
    rows = [(rise / s.hz, width) for rise, _fall, width, _period in pulses]
    return (idx, name), pulses, rows


def stable_segments(s, pulses, a):
    widths = [p[2] for p in pulses]
    ranges = []
    first = 0
    ref = widths[0]
    for k in range(1, len(widths)):
        if abs(widths[k] - ref) > a.segment_tolerance_us:
            if k - first >= a.segment_min_pulses:
                ranges.append((first, k))
            first = k
            ref = widths[k]
    if len(widths) - first >= a.segment_min_pulses:
        ranges.append((first, len(widths)))

    return [
        {
            "start_s": pulses[lo][0] / s.hz,
            "end_s": pulses[hi - 1][1] / s.hz,
            "median_us": statistics.median(widths[lo:hi]),
            "pulse_count": hi - lo,
        }
        for lo, hi in ranges
    ]


def choose_throttle_t(s, pulses, a):
    if a.throttle_t == "none":
        return None, None, None
    if a.throttle_t == "manual":
        if a.throttle_t_s is None:
            raise DSLError("--throttle-t manual requires --throttle-t-s")
        if not 0 <= a.throttle_t_s <= s.duration:
            raise DSLError("--throttle-t-s is outside the capture")
        return a.throttle_t_s, None, None

    segments = stable_segments(s, pulses, a)
    if len(segments) < 2:
        raise DSLError("Could not detect at least two stable PWM command segments")

    steps = []
    for k in range(len(segments) - 1):
        before, after = segments[k], segments[k + 1]
        delta = after["median_us"] - before["median_us"]
        if abs(delta) < a.min_step_us:
            continue
        steps.append(
            {
                "t0": after["start_s"],
                "before_us": before["median_us"],
                "after_us": after["median_us"],
                "delta_us": delta,
            }
        )

    candidates = steps
    if a.step_direction == "rise":
        candidates = [x for x in candidates if x["delta_us"] > 0]
    elif a.step_direction == "fall":
        candidates = [x for x in candidates if x["delta_us"] < 0]
    if a.step_index < 0 or a.step_index >= len(candidates):
        raise DSLError("Requested PWM step was not found")

    chosen = candidates[a.step_index]
    return chosen["t0"], chosen, segments


def decode_rpm(s, a):
    if a.ppr <= 0:
        raise DSLError("--ppr must be > 0")
    if not (0 <= a.quality_reject_ratio <= 1):
        raise DSLError("--quality-reject-ratio must be between 0 and 1")

    idx, name = s.resolve(RPM_CH)
    st, en = span(s, a.start_s, a.end_s)
    cur = s.bit(idx, st)
    prev = None
    min_dt = a.min_edge_spacing_ms * 1e-3
    selected = short_reject = sanity_reject = 0
    rows = []

    for n, new in s.rows(idx, max(1, st + 1), en):
        edge = "rising" if cur == 0 and new == 1 else "falling"
        cur = new
        if a.rpm_edge != "both" and edge != a.rpm_edge:
            continue
        selected += 1
        if prev is None:
            prev = n
            continue

        dt = (n - prev) / s.hz
        prev = n  # never bridge rejected intervals
        if dt <= 0:
            continue
        if min_dt > 0 and dt < min_dt:
            short_reject += 1
            continue

        freq = 1.0 / dt
        rpm = 60.0 * freq / a.ppr
        if a.rpm_sanity_max > 0 and rpm > a.rpm_sanity_max:
            sanity_reject += 1
            continue
        rows.append((n / s.hz, rpm, dt, freq))

    considered = len(rows) + short_reject + sanity_reject
    rejected = short_reject + sanity_reject
    reject_ratio = rejected / considered if considered else 1.0
    checked = a.min_edge_spacing_ms > 0 or a.rpm_sanity_max > 0

    if not rows:
        raise DSLError("No valid RPM samples; check tach pulse, edge polarity, PPR, and filters")

    bad = len(rows) < a.min_valid_rpm_samples or (
        checked
        and considered >= a.min_valid_rpm_samples
        and reject_ratio >= a.quality_reject_ratio
    )
    if bad:
        msg = (
            f"{RPM_CH} tachometer pulse does not match the requested RPM/PPR model: "
            f"valid={len(rows):,}, rejected={rejected:,}/{considered:,} "
            f"({100 * reject_ratio:.4f}%). Check tachometer pulse-output definition, "
            "reflective marker configuration, selected edge polarity, PPR, and filters."
        )
        if not a.allow_low_quality_rpm:
            raise DSLError(msg)
        print(f"WARNING: {msg}", file=sys.stderr)

    quality = {
        "checked": checked,
        "selected_edges": selected,
        "valid_samples": len(rows),
        "rejected_short": short_reject,
        "rejected_sanity": sanity_reject,
        "rejected_ratio": reject_ratio,
    }
    return (idx, name), median_filter(rows, a.rpm_median_window), quality


def sustained_target_cross(rows, start_s, end_s, target, hold_s, min_samples):
    q = [(t, rpm) for t, rpm, *_ in rows if start_s <= t <= end_s]
    for i, (t0, rpm0) in enumerate(q):
        if rpm0 < target:
            continue
        j = i
        count = 0
        while j < len(q) and q[j][0] - t0 <= hold_s:
            if q[j][1] < target:
                break
            count += 1
            j += 1
        if count >= min_samples and (hold_s <= 0 or q[j - 1][0] - t0 >= 0.8 * hold_s):
            return t0
    return None


def choose_rpm_t(s, rows, throttle_t, a):
    if a.rpm_t == "none":
        return None
    if a.rpm_t == "manual":
        if a.rpm_t_s is None:
            raise DSLError("--rpm-t manual requires --rpm-t-s")
        if not 0 <= a.rpm_t_s <= s.duration:
            raise DSLError("--rpm-t-s is outside the capture")
        return a.rpm_t_s

    start = throttle_t if throttle_t is not None else (a.start_s or 0.0)
    end = min(s.duration, a.end_s or s.duration)
    return sustained_target_cross(
        rows, start, end, a.target_rpm,
        a.target_hold_ms * 1e-3, a.target_min_samples,
    )


def pwm_percent(width_us, a):
    if a.pwm_high_us == a.pwm_low_us:
        raise DSLError("--pwm-high-us and --pwm-low-us must differ")
    return (width_us - a.pwm_low_us) * a.pwm_max_pct / (a.pwm_high_us - a.pwm_low_us)


def pwm_display_value(width_us, a):
    return width_us if a.pwm_axis == "us" else pwm_percent(width_us, a)


def build_pwm_plot_rows(pwm_rows, start_s, end_s, origin, a):
    q = [(t, w) for t, w in pwm_rows if start_s <= t <= end_s]
    if not q:
        return [], []
    return [t - origin for t, _ in q], [pwm_display_value(w, a) for _, w in q]


def plot(s, capture_name, rpm_rows, pwm_rows, throttle_t, rpm_t, step, a):
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise DSLError("Install matplotlib: py -m pip install matplotlib") from exc

    if throttle_t is not None:
        origin = throttle_t
        plot_start = max(a.start_s or 0.0, throttle_t - a.plot_pre_s)
        plot_end = (
            min(s.duration, a.end_s or s.duration)
            if a.plot_post_s is None
            else min(s.duration, throttle_t + a.plot_post_s)
        )
        xlabel = "Time from throttle step (s)"
    else:
        origin = 0.0
        plot_start = a.start_s or 0.0
        plot_end = min(s.duration, a.end_s or s.duration)
        xlabel = "Capture time (s)"

    r = [(t - origin, rpm) for t, rpm, *_ in rpm_rows if plot_start <= t <= plot_end]
    if not r:
        raise DSLError("No RPM samples in selected plot window")
    px, py = build_pwm_plot_rows(pwm_rows, plot_start, plot_end, origin, a)

    fig, ax1 = plt.subplots(figsize=(12, 6), dpi=a.dpi)
    ax1.plot([x for x, _ in r], [y for _, y in r], linewidth=2.2)
    ax1.set_xlabel(xlabel)
    ax1.set_ylabel("RPM")
    ax1.grid(True, alpha=0.25)

    if a.target_rpm is not None:
        ax1.axhline(a.target_rpm, linestyle=":", linewidth=1.0)
    if throttle_t is not None:
        ax1.axvline(0.0, linestyle=":", linewidth=1.0)

    elapsed = None
    if rpm_t is not None:
        rpm_t_x = rpm_t - origin
        nearest = min(rpm_rows, key=lambda row: abs(row[0] - rpm_t))
        marker_rpm = nearest[1]
        ax1.scatter([rpm_t_x], [marker_rpm], s=45, zorder=5)
        if throttle_t is not None:
            elapsed = rpm_t - throttle_t
            label = f"{a.target_rpm:.0f} RPM @ {elapsed:.3f} s"
        else:
            label = f"{a.target_rpm:.0f} RPM @ t={rpm_t:.3f} s"
        ax1.annotate(
            label,
            xy=(rpm_t_x, marker_rpm),
            xytext=(rpm_t_x + a.annotation_dx_s, marker_rpm - a.annotation_dy_rpm),
            arrowprops=dict(arrowstyle="->"),
            fontsize=11,
        )

    ax2 = ax1.twinx()
    if px:
        ax2.step(
            px, py, where="post", linestyle="--", linewidth=1.8,
            color="0.55", alpha=0.9,
        )

    if a.pwm_axis == "us":
        pwm_axis_label = "PWM Ton (us)"
        pwm_subtitle = "PWM Ton"
    else:
        pwm_axis_label = "PWM command (%)"
        pwm_subtitle = "PWM command (%)"
        ax2.set_ylim(0, max(100.0, a.pwm_max_pct))
    ax2.set_ylabel(pwm_axis_label)

    title = a.title or f"{Path(capture_name).stem} Step Response"
    fig.suptitle(title, fontsize=18, y=0.97)
    subtitle = f"RPM — dashed grey line is {pwm_subtitle}"
    if rpm_t is not None:
        if elapsed is not None:
            subtitle += f" | Time to {a.target_rpm:.0f} RPM = {elapsed:.3f} s"
        else:
            subtitle += f" | {a.target_rpm:.0f} RPM crossing at t = {rpm_t:.3f} s"
    ax1.set_title(subtitle, fontsize=13, pad=10)

    if step is not None:
        if a.pwm_axis == "percent":
            before_pct = pwm_percent(step["before_us"], a)
            after_pct = pwm_percent(step["after_us"], a)
            print(
                f"Throttle step: {step['before_us']:.1f} -> {step['after_us']:.1f} us "
                f"({before_pct:.2f}% -> {after_pct:.2f}%) @ {throttle_t:.6f} s"
            )
        else:
            print(f"Throttle step: {step['before_us']:.1f} -> {step['after_us']:.1f} us @ {throttle_t:.6f} s")
    elif throttle_t is not None:
        print(f"Throttle T (manual): {throttle_t:.6f} s")
    else:
        print("Throttle T: disabled")

    if rpm_t is None:
        print("RPM target T: not found" if a.rpm_t == "auto" else "RPM target T: disabled")
    elif elapsed is not None:
        print(f"RPM target T: {rpm_t:.6f} s; elapsed from throttle T: {elapsed:.6f} s")
    else:
        print(f"RPM target T: {rpm_t:.6f} s")

    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(a.output, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote: {a.output}")


def parser():
    p = argparse.ArgumentParser(
        description="Single-figure ESC step-response plot from DSLogic .dsl (CH0=tach pulse, CH1=PWM command)"
    )
    p.add_argument("dsl")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    p.add_argument("--ppr", type=float, required=True, help="selected RPM-edge events per mechanical revolution")
    p.add_argument("--rpm-edge", choices=["rising", "falling", "both"], default="falling")
    p.add_argument("--target-rpm", type=float, default=8800.0)

    p.add_argument("--throttle-t", choices=["auto", "manual", "none"], default="auto",
                   help="auto=detect CH1 PWM step, manual=use --throttle-t-s, none=no T0 search/alignment")
    p.add_argument("--throttle-t-s", type=float, help="absolute capture time in seconds for --throttle-t manual")
    p.add_argument("--rpm-t", choices=["auto", "manual", "none"], default="auto",
                   help="auto=find target-RPM crossing, manual=use --rpm-t-s, none=no target-time search/annotation")
    p.add_argument("--rpm-t-s", type=float, help="absolute capture time in seconds for --rpm-t manual")

    p.add_argument("--step-direction", choices=["rise", "fall", "any"], default="rise")
    p.add_argument("--step-index", type=int, default=0)
    p.add_argument("--min-step-us", type=float, default=100.0, help="ignore detected PWM segment changes smaller than this")

    p.add_argument("--pwm-min-us", type=float, default=500.0)
    p.add_argument("--pwm-max-us", type=float, default=2500.0)
    p.add_argument("--pwm-axis", "--command-axis", dest="pwm_axis", choices=["us", "percent"], default="us",
                   help="right-axis display units: raw PWM Ton in microseconds or mapped command percent")
    p.add_argument("--pwm-low-us", type=float, default=1000.0, help="PWM width corresponding to 0%% in percent mode")
    p.add_argument("--pwm-high-us", type=float, default=1900.0, help="PWM width corresponding to --pwm-max-pct in percent mode")
    p.add_argument("--pwm-max-pct", "--throttle-max-pct", dest="pwm_max_pct", type=float, default=90.0)
    p.add_argument("--segment-tolerance-us", type=float, default=5.0)
    p.add_argument("--segment-min-pulses", type=int, default=3)

    p.add_argument("--target-hold-ms", type=float, default=100.0)
    p.add_argument("--target-min-samples", type=int, default=3)
    p.add_argument("--min-edge-spacing-ms", type=float, default=0.0)
    p.add_argument("--rpm-sanity-max", type=float, default=0.0)
    p.add_argument("--rpm-median-window", type=int, default=5)
    p.add_argument("--quality-reject-ratio", type=float, default=0.99)
    p.add_argument("--min-valid-rpm-samples", type=int, default=3)
    p.add_argument("--allow-low-quality-rpm", action="store_true")

    p.add_argument("--start-s", type=float)
    p.add_argument("--end-s", type=float)
    p.add_argument("--plot-pre-s", type=float, default=2.0)
    p.add_argument("--plot-post-s", type=float, help="seconds after throttle T; default plots to end of capture")
    p.add_argument("--title")
    p.add_argument("--annotation-dx-s", type=float, default=0.08)
    p.add_argument("--annotation-dy-rpm", type=float, default=1800.0)
    p.add_argument("--dpi", type=int, default=180)
    p.add_argument("-o", "--output", default="esc_step_response.png")
    return p


def main():
    a = parser().parse_args()
    try:
        if a.pwm_axis == "percent" and a.pwm_high_us == a.pwm_low_us:
            raise DSLError("--pwm-high-us and --pwm-low-us must differ in percent mode")
        with DSL(a.dsl) as s:
            _cmd, pulses, pwm_rows = decode_pwm(s, a)
            throttle_t, step, _segments = choose_throttle_t(s, pulses, a)
            _rpm, rpm_rows, quality = decode_rpm(s, a)
            rpm_t = choose_rpm_t(s, rpm_rows, throttle_t, a)

            if quality["checked"]:
                print(
                    f"RPM quality: CHECKED | valid={quality['valid_samples']:,}, "
                    f"rejected={100 * quality['rejected_ratio']:.4f}%"
                )
            else:
                print(
                    "RPM quality: UNCHECKED | no plausibility limits active "
                    "(--min-edge-spacing-ms=0 and --rpm-sanity-max=0)"
                )
            plot(s, Path(a.dsl).name, rpm_rows, pwm_rows, throttle_t, rpm_t, step, a)
        return 0
    except (DSLError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
