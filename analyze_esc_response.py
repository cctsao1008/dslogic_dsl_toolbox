#!/usr/bin/env python3
"""ESC step-response report generator for DSLogic/DSView .dsl captures."""
import argparse, csv, json, math, statistics, sys
from pathlib import Path
from dslogic_dsl_toolbox import DSL, DSLError, pulse_iter, span

VERSION = "1.0.0"


def medf(rows, win):
    if win <= 1:
        return rows
    if win % 2 == 0:
        win += 1
    h = win // 2; vals = [r[1] for r in rows]; out = []
    for i, r in enumerate(rows):
        out.append((r[0], statistics.median(vals[max(0,i-h):min(len(rows),i+h+1)]), r[2], r[3]))
    return out


def throttle(s, ch, a):
    i, name = s.resolve(ch); st, en = span(s, a.start_s, a.end_s)
    p = list(pulse_iter(s, i, st, en, a.pwm_min_us, a.pwm_max_us))
    if not p: raise DSLError(f"No valid throttle PWM on CH{i} ({name})")
    w = [x[2] for x in p]; ranges=[]; first=0; ref=w[0]
    for k in range(1,len(w)):
        if abs(w[k]-ref) > a.segment_tolerance_us:
            if k-first >= a.segment_min_pulses: ranges.append((first,k))
            first=k; ref=w[k]
    if len(w)-first >= a.segment_min_pulses: ranges.append((first,len(w)))
    if len(ranges) < 2: raise DSLError("Need at least two stable throttle segments")
    seg=[]
    for lo,hi in ranges:
        u=statistics.median(w[lo:hi]); pct=(u-a.pwm_low_us)*a.throttle_max_pct/(a.pwm_high_us-a.pwm_low_us)
        seg.append(dict(start_s=p[lo][0]/s.hz,end_s=p[hi-1][1]/s.hz,pulses=hi-lo,median_us=u,command_pct=pct))
    steps=[]
    for k in range(len(seg)-1):
        b,n=seg[k],seg[k+1]
        steps.append(dict(index=k,t0=n["start_s"],before_pct=b["command_pct"],after_pct=n["command_pct"],delta_pct=n["command_pct"]-b["command_pct"],response_end_s=seg[k+2]["start_s"] if k+2<len(seg) else min(s.duration,a.end_s or s.duration)))
    cand=steps
    if a.step_direction=="rise": cand=[x for x in cand if x["delta_pct"]>0]
    if a.step_direction=="fall": cand=[x for x in cand if x["delta_pct"]<0]
    if not cand or a.step_index >= len(cand): raise DSLError("Requested throttle step was not found")
    return (i,name),seg,cand[a.step_index]


def rpm_data(s, ch, a):
    if a.ppr <= 0: raise DSLError("--ppr must be > 0")
    i,name=s.resolve(ch); st,en=span(s,a.start_s,a.end_s); cur=s.bit(i,st); prev=None; out=[]; mindt=a.min_edge_spacing_ms*1e-3
    for n,new in s.rows(i,max(1,st+1),en):
        typ="rising" if cur==0 and new==1 else "falling"; cur=new
        if a.rpm_edge!="both" and typ!=a.rpm_edge: continue
        if prev is None: prev=n; continue
        dt=(n-prev)/s.hz; prev=n
        if dt<=0 or (mindt>0 and dt<mindt): continue
        f=1/dt; r=60*f/a.ppr
        if a.rpm_sanity_max>0 and r>a.rpm_sanity_max: continue
        out.append((n/s.hz,r,dt,f))
    if not out: raise DSLError("No valid RPM samples; check channel/edge/PPR/filters")
    return (i,name),medf(out,a.rpm_median_window)


def vals(rows,a,b): return [v for t,v,*_ in rows if a<=t<b]
def cross(rows,t0,end,y,rise):
    for t,v,*_ in rows:
        if t<t0: continue
        if t>=end: break
        if (rise and v>=y) or ((not rise) and v<=y): return t
    return None


def target_cross(rows,t0,end,y,rise,hold,minn):
    q=[(t,v) for t,v,*_ in rows if t0<=t<end]
    for i,(t,v) in enumerate(q):
        if not ((rise and v>=y) or ((not rise) and v<=y)): continue
        j=i; n=0
        while j<len(q) and q[j][0]-t<=hold:
            ok=q[j][1]>=y if rise else q[j][1]<=y
            if not ok: break
            n+=1; j+=1
        if n>=minn and (hold<=0 or q[j-1][0]-t>=0.8*hold): return t
    return None


def metrics(rows,step,a):
    t0,end=step["t0"],step["response_end_s"]
    basev=vals(rows,max(a.start_s or 0,t0-a.baseline_window_s),t0); post=vals(rows,t0,end)
    if len(basev)<a.min_metric_samples or len(post)<a.min_metric_samples: raise DSLError("Insufficient RPM samples around selected step")
    finalv=vals(rows,max(t0,end-a.final_window_s),end)
    if len(finalv)<a.min_metric_samples: finalv=post[-max(a.min_metric_samples,len(post)//4):]
    base,final=statistics.median(basev),statistics.median(finalv); amp=final-base
    if abs(amp)<a.min_response_amplitude_rpm: raise DSLError(f"RPM response amplitude too small: {amp:.1f} RPM")
    rise=amp>0; ms={}
    for name,f in (("10%",.10),("63.2% (tau)",.632),("90%",.90),("95%",.95)):
        y=base+f*amp; t=cross(rows,t0,end,y,rise); ms[name]=dict(time=t,elapsed=None if t is None else t-t0,rpm=y)
    sig=statistics.pstdev(basev) if len(basev)>1 else 0; delta=max(a.first_response_abs_rpm,a.first_response_sigma*sig); first=None
    for t,v,*_ in rows:
        if t<t0: continue
        if t>=end: break
        if abs(v-base)>=delta: first=t; break
    ms={"First response":dict(time=first,elapsed=None if first is None else first-t0,rpm=None),**ms}
    band=max(abs(final)*a.settling_band_pct/100,a.settling_band_abs_rpm); hold=a.settling_hold_ms*1e-3; settle=None
    q=[(t,v) for t,v,*_ in rows if t0<=t<end]
    for i,(t,v) in enumerate(q):
        if abs(v-final)>band: continue
        j=i
        while j<len(q) and abs(q[j][1]-final)<=band:
            if q[j][0]-t>=hold: settle=t; break
            j+=1
        if settle is not None: break
    ms["Settled"]=dict(time=settle,elapsed=None if settle is None else settle-t0,rpm=final)
    t10,t90=ms["10%"]["time"],ms["90%"]["time"]; rt=None if t10 is None or t90 is None else abs(t90-t10)
    response=[v for t,v,*_ in rows if t0<=t<end]; ext=max(response) if rise else min(response); ov=max(0,ext-final) if rise else max(0,final-ext); ovp=100*ov/abs(final) if final else math.nan
    tt=None
    if a.target_rpm is not None: tt=target_cross(rows,t0,end,a.target_rpm,a.target_rpm>=base,a.target_hold_ms*1e-3,a.target_min_samples)
    return dict(t0=t0,response_end_s=end,baseline_rpm=base,steady_state_rpm=final,amplitude_rpm=amp,direction="rise" if rise else "fall",milestones=ms,rise_time_10_90_s=rt,settling_time_s=None if settle is None else settle-t0,extremum_rpm=ext,overshoot_pct=ovp,target_rpm=a.target_rpm,target_cross_time_s=tt,time_to_target_s=None if tt is None else tt-t0)


def ftime(x): return "-" if x is None else f"{x:.3f} s"
def card(ax,x,y,w,h,title,value):
    from matplotlib.patches import FancyBboxPatch
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0.018,rounding_size=0.025",fill=False,transform=ax.transAxes))
    ax.text(x+.04,y+h*.67,title,fontsize=8.5,transform=ax.transAxes); ax.text(x+.04,y+h*.23,value,fontsize=15,fontweight="bold",transform=ax.transAxes)


def report(out,capture,th,rp,rows,seg,step,m,a):
    try:
        import matplotlib.pyplot as plt
        from matplotlib.gridspec import GridSpec
    except ImportError as e: raise DSLError("Install matplotlib: py -m pip install matplotlib") from e
    fig=plt.figure(figsize=(14,9)); gs=GridSpec(3,2,figure=fig,height_ratios=[.8,1.8,5],width_ratios=[1.45,1])
    h=fig.add_subplot(gs[0,:]); h.axis("off"); h.text(0,.72,a.title or "ESC Step Response Report",fontsize=18,fontweight="bold",transform=h.transAxes)
    sub=f"{capture} | throttle CH{th[0]} ({th[1]}) | RPM CH{rp[0]} ({rp[1]}) | {a.rpm_edge} edge | PPR={a.ppr:g}"+(f" | {a.test_condition}" if a.test_condition else "")
    h.text(0,.25,sub,fontsize=9.5,transform=h.transAxes)
    ta=fig.add_subplot(gs[1,0]); ta.axis("off"); ta.text(0,1.03,"Response Milestones",fontsize=11.5,fontweight="bold",transform=ta.transAxes)
    tab=ta.table(cellText=[[n,ftime(v["time"]),ftime(v["elapsed"])] for n,v in m["milestones"].items()],colLabels=["Milestone","Absolute Time","Elapsed from T0"],cellLoc="left",colLoc="left",loc="upper left",bbox=[0,0,.96,.90]); tab.auto_set_font_size(False); tab.set_fontsize(8.7)
    ka=fig.add_subplot(gs[1,1]); ka.axis("off"); ka.text(0,1.03,"Key Metrics",fontsize=11.5,fontweight="bold",transform=ka.transAxes)
    card(ka,0,.50,.47,.38,"10-90% Rise Time",ftime(m["rise_time_10_90_s"])); title=f"Time to {a.target_rpm:.0f} RPM" if a.target_rpm is not None else "Settling Time"; value=ftime(m["time_to_target_s"] if a.target_rpm is not None else m["settling_time_s"]); card(ka,.52,.50,.47,.38,title,value); card(ka,0,.05,.47,.38,"Steady-State RPM",f'{m["steady_state_rpm"]:.0f}'); card(ka,.52,.05,.47,.38,"Overshoot",f'{m["overshoot_pct"]:.1f}%')
    ax=fig.add_subplot(gs[2,:]); ps=max(a.start_s or 0,step["t0"]-a.plot_pre_s); pe=step["response_end_s"]+a.plot_post_s; r=[(t,v) for t,v,*_ in rows if ps<=t<=pe]
    line,=ax.plot([x[0] for x in r],[x[1] for x in r],linewidth=1.8,label="RPM"); ax.set(xlabel="Time (s)",ylabel="RPM"); ax.grid(True,alpha=.25); ax.axvline(m["t0"],linestyle="--",linewidth=1); ax.text(m["t0"],ax.get_ylim()[1]*.96,"T0",ha="center",va="top")
    for n in ("10%","63.2% (tau)","90%","95%"):
        q=m["milestones"][n]
        if q["time"] is not None: ax.scatter([q["time"]],[q["rpm"]],s=24); ax.annotate(n,(q["time"],q["rpm"]),xytext=(4,5),textcoords="offset points",fontsize=8)
    if a.target_rpm is not None:
        ax.axhline(a.target_rpm,linestyle="--",linewidth=1)
        if m["target_cross_time_s"] is not None: ax.axvline(m["target_cross_time_s"],linestyle=":",linewidth=1.1); ax.text(m["target_cross_time_s"],ax.get_ylim()[1]*.83,"Ttarget",ha="center")
    ax2=ax.twinx(); tx=[]; ty=[]
    for q in seg:
        if q["end_s"]<ps or q["start_s"]>pe: continue
        tx += [max(q["start_s"],ps),min(q["end_s"],pe)]; ty += [q["command_pct"],q["command_pct"]]
    tline,=ax2.step(tx,ty,where="post",linestyle="--",linewidth=1.3,label="Throttle"); ax2.set_ylabel("Throttle (%)"); ax2.set_ylim(min(0,min(ty)-5),max(100,max(ty)+5)); ax.legend([line,tline],["RPM","Throttle"],loc="lower right")
    fig.text(.01,.012,f"Selected step: {step['before_pct']:.1f}% -> {step['after_pct']:.1f}% at T0={step['t0']:.6f}s. RPM = 60 / (edge interval x PPR); PPR = selected edge events per mechanical revolution.",fontsize=7.8); fig.tight_layout(rect=[0,.035,1,1]); fig.savefig(out,dpi=a.dpi,bbox_inches="tight"); plt.close(fig)


def save(prefix,seg,rows,payload):
    with open(str(prefix)+"_throttle_segments.csv","w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["segment","start_s","end_s","pulse_count","median_us","command_pct"])
        for i,q in enumerate(seg): w.writerow([i,q["start_s"],q["end_s"],q["pulses"],q["median_us"],q["command_pct"]])
    with open(str(prefix)+"_rpm.csv","w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["time_s","rpm","dt_s","edge_frequency_hz"]); w.writerows(rows)
    Path(str(prefix)+"_metrics.json").write_text(json.dumps(payload,indent=2),encoding="utf-8")


def parser():
    p=argparse.ArgumentParser(description="ESC step-response report from DSLogic .dsl"); p.add_argument("dsl"); p.add_argument("--version",action="version",version=f"%(prog)s {VERSION}")
    p.add_argument("--throttle-channel",required=True); p.add_argument("--rpm-channel",required=True); p.add_argument("--rpm-edge",choices=["rising","falling","both"],default="falling"); p.add_argument("--ppr",type=float,required=True,help="selected edge events per mechanical revolution")
    p.add_argument("--pwm-low-us",type=float,default=1000); p.add_argument("--pwm-high-us",type=float,default=1900); p.add_argument("--throttle-max-pct",type=float,default=90); p.add_argument("--pwm-min-us",type=float,default=500); p.add_argument("--pwm-max-us",type=float,default=2500); p.add_argument("--segment-tolerance-us",type=float,default=5); p.add_argument("--segment-min-pulses",type=int,default=3); p.add_argument("--step-index",type=int,default=0); p.add_argument("--step-direction",choices=["any","rise","fall"],default="any")
    p.add_argument("--target-rpm",type=float,default=8800); p.add_argument("--target-hold-ms",type=float,default=100); p.add_argument("--target-min-samples",type=int,default=3); p.add_argument("--min-edge-spacing-ms",type=float,default=0); p.add_argument("--rpm-sanity-max",type=float,default=0); p.add_argument("--rpm-median-window",type=int,default=5)
    p.add_argument("--baseline-window-s",type=float,default=.5); p.add_argument("--final-window-s",type=float,default=.4); p.add_argument("--first-response-sigma",type=float,default=3); p.add_argument("--first-response-abs-rpm",type=float,default=100); p.add_argument("--settling-band-pct",type=float,default=2); p.add_argument("--settling-band-abs-rpm",type=float,default=50); p.add_argument("--settling-hold-ms",type=float,default=300); p.add_argument("--min-metric-samples",type=int,default=3); p.add_argument("--min-response-amplitude-rpm",type=float,default=200)
    p.add_argument("--start-s",type=float); p.add_argument("--end-s",type=float); p.add_argument("--plot-pre-s",type=float,default=1); p.add_argument("--plot-post-s",type=float,default=0); p.add_argument("--title"); p.add_argument("--test-condition"); p.add_argument("-o","--output",default="esc_response_report.png"); p.add_argument("--output-prefix"); p.add_argument("--dpi",type=int,default=180); return p


def main():
    a=parser().parse_args()
    if a.pwm_high_us==a.pwm_low_us: print("ERROR: PWM endpoints must differ",file=sys.stderr); return 2
    try:
        with DSL(a.dsl) as s:
            th,seg,step=throttle(s,a.throttle_channel,a); rp,rows=rpm_data(s,a.rpm_channel,a); m=metrics(rows,step,a); out=Path(a.output); prefix=Path(a.output_prefix) if a.output_prefix else out.with_suffix(""); payload=dict(version=VERSION,capture=str(Path(a.dsl)),sample_rate_hz=s.hz,throttle=dict(channel=th[0],name=th[1],selected_step=step,segments=seg),rpm=dict(channel=rp[0],name=rp[1],edge=a.rpm_edge,ppr=a.ppr),metrics=m); save(prefix,seg,rows,payload); report(out,Path(a.dsl).name,th,rp,rows,seg,step,m,a)
        print(f"Report: {out}\nMetrics: {prefix}_metrics.json\nRPM: {prefix}_rpm.csv\nThrottle: {prefix}_throttle_segments.csv"); print(f"Step: {step['before_pct']:.2f}% -> {step['after_pct']:.2f}% @ {step['t0']:.6f}s"); print(f"10-90% rise: {ftime(m['rise_time_10_90_s'])}; settle: {ftime(m['settling_time_s'])}"); return 0
    except (DSLError,OSError,ValueError,json.JSONDecodeError) as e: print(f"ERROR: {e}",file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())
