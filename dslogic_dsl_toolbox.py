#!/usr/bin/env python3
"""Read-only toolbox for ZIP-based, non-RLE DSView/DSLogic .dsl captures."""
import argparse, configparser, csv, heapq, json, re, statistics, sys, zipfile
from pathlib import Path

VERSION = "1.0.0"

class DSLError(RuntimeError): pass

def rate(s):
    s=str(s).strip()
    try: return float(s)
    except ValueError: pass
    m=re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([kKmMgG]?)\s*(?:Hz|hz)?",s)
    if not m: raise DSLError(f"Cannot parse sample rate: {s!r}")
    return float(m.group(1))*{"":1,"k":1e3,"m":1e6,"g":1e9}[m.group(2).lower()]

def tstr(x): return f"{x:.12f}".rstrip("0").rstrip(".") or "0"

class DSL:
    def __init__(self,path):
        self.path=Path(path)
        if not self.path.is_file() or not zipfile.is_zipfile(self.path): raise DSLError(f"Invalid .dsl file: {path}")
        self.z=zipfile.ZipFile(self.path)
        names=set(self.z.namelist())
        if not {"header","session"}<=names: raise DSLError("Missing header/session")
        cp=configparser.ConfigParser(); cp.optionxform=str.lower
        cp.read_string(self.z.read("header").decode("utf-8","replace")); h=cp["header"]
        try: self.ver=int(cp.get("version","version",fallback="-1"))
        except ValueError: self.ver=-1
        self.driver=h.get("driver","unknown"); self.samples=int(h.get("total samples","0")); self.probes=int(h.get("total probes","0")); self.blocks=int(h.get("total blocks","0")); self.hz=rate(h.get("samplerate","0"))
        self.session=json.loads(self.z.read("session").decode("utf-8","replace"))
        if bool(int(self.session.get("Enable RLE Compress",0) or 0)): raise DSLError("RLE-compressed captures are not supported yet")
        meta={}
        for x in self.session.get("channel",[]) or []:
            try: meta[int(x.get("index"))]=x
            except Exception: pass
        ids=sorted({int(m.group(1)) for n in names if (m:=re.fullmatch(r"L-(\d+)/(\d+)",n))}) or list(range(self.probes))
        self.ch=[(i,str(meta.get(i,{}).get("name",i))) for i in ids]; self.cache={}
        if self.samples<=0 or self.hz<=0: raise DSLError("Invalid sample count/rate")
    def close(self): self.z.close()
    def __enter__(self): return self
    def __exit__(self,*_): self.close()
    @property
    def duration(self): return self.samples/self.hz
    def resolve(self,x):
        s=str(x).strip(); u=s.upper(); idx=int(u[2:]) if u.startswith("CH") and u[2:].isdigit() else int(s) if s.isdigit() else None
        if idx is None:
            hit=[p for p in self.ch if p[1]==s]
            if len(hit)==1: return hit[0]
        else:
            for p in self.ch:
                if p[0]==idx: return p
        raise DSLError(f"Unknown channel {x!r}")
    def data(self,idx):
        if idx not in self.cache:
            a=[]
            for n in self.z.namelist():
                m=re.fullmatch(rf"L-{idx}/(\d+)",n)
                if m: a.append((int(m.group(1)),n))
            if not a: raise DSLError(f"No data for CH{idx}")
            self.cache[idx]=b"".join(self.z.read(n) for _,n in sorted(a))
        return self.cache[idx]
    def bit(self,idx,n):
        d=self.data(idx); return (d[n>>3]>>(n&7))&1
    def transitions(self,idx,start=1,end=None):
        end=self.samples if end is None else min(end,self.samples); start=max(1,start)
        if start>=end: return
        d=self.data(idx); fb=start>>3; lb=(end-1)>>3; base=fb<<3; prev=self.bit(idx,base-1) if base else d[0]&1
        for bi in range(fb,lb+1):
            b=d[bi]; mask=b^((b<<1)&255)^(1 if prev else 0); bb=bi<<3
            if bb==0: mask&=254
            lo=max(start-bb,0); hi=min(end-bb,8)
            if lo: mask&=(255<<lo)&255
            if hi<8: mask&=(1<<hi)-1
            while mask:
                q=mask&-mask; yield bb+q.bit_length()-1; mask^=q
            prev=(b>>7)&1
    def rows(self,idx,start=1,end=None):
        cur=self.bit(idx,max(0,start-1))
        for n in self.transitions(idx,start,end): cur^=1; yield n,cur

def span(s,a,b):
    a=0 if a is None else a; b=s.duration if b is None else b
    if a<0 or b<=a or a>=s.duration: raise DSLError(f"Invalid range {a}..{b}s")
    return int(a*s.hz),min(s.samples,int(b*s.hz+0.999999999))

def chans(s,x): return s.ch if not x else [s.resolve(v) for v in x]

def info(a):
    with DSL(a.dsl) as s:
        print(f"File: {s.path}\nDriver: {s.driver}\nDSL format: {s.ver}\nSample rate: {s.hz:g} Hz\nSamples: {s.samples:,}\nDuration: {s.duration:.9f} s\nChannels: {len(s.ch)}\nBlocks: {s.blocks}\nRLE: disabled")
        for i,n in s.ch: print(f"  CH{i}: {n}")

def check(a):
    with DSL(a.dsl) as s:
        need=(s.samples+7)//8; ok=True
        for i,n in s.ch:
            size=len(s.data(i)); good=size>=need; ok&=good; print(f"CH{i}: bytes={size:,} expected>={need:,} {'OK' if good else 'SHORT'}")
        if not ok: raise DSLError("Capture data is incomplete")
        print("Capture structure: OK")

def stats(a):
    with DSL(a.dsl) as s:
        st,en=span(s,a.start_s,a.end_s); print("Channel  Transitions  Rising  Falling")
        for i,n in chans(s,a.channels):
            cur=s.bit(i,st); total=up=dn=0
            for _,new in s.rows(i,max(1,st+1),en):
                total+=1; up+=cur==0 and new==1; dn+=cur==1 and new==0; cur=new
            print(f"CH{i:<5} {total:>11,} {up:>7,} {dn:>8,}")

def export_csv(a):
    with DSL(a.dsl) as s,open(a.output,"w",newline="",encoding="utf-8") as f:
        cs=chans(s,a.channels); st,en=span(s,a.start_s,a.end_s); base=st if a.relative_time else 0; state={i:s.bit(i,st) for i,_ in cs}; w=csv.writer(f); w.writerow(["Time(s)"]+[str(i) for i,_ in cs]); w.writerow([tstr((st-base)/s.hz)]+[state[i] for i,_ in cs])
        heap=[]; its={}
        for i,_ in cs:
            it=iter(s.rows(i,max(1,st+1),en)); its[i]=it
            try: n,v=next(it); heapq.heappush(heap,(n,i,v))
            except StopIteration: pass
        count=1
        while heap:
            n=heap[0][0]; changed=[]
            while heap and heap[0][0]==n:
                _,i,v=heapq.heappop(heap); state[i]=v; changed.append(i)
            w.writerow([tstr((n-base)/s.hz)]+[state[i] for i,_ in cs]); count+=1
            for i in changed:
                try: nn,v=next(its[i]); heapq.heappush(heap,(nn,i,v))
                except StopIteration: pass
        print(f"Wrote {count:,} rows: {a.output}")

def edges(a):
    with DSL(a.dsl) as s,open(a.output,"w",newline="",encoding="utf-8") as f:
        i,_=s.resolve(a.channel); st,en=span(s,a.start_s,a.end_s); base=st if a.relative_time else 0; cur=s.bit(i,st); last=None; count=0; w=csv.writer(f); w.writerow(["sample","time_s","edge","new_level","dt_s"])
        for n,new in s.rows(i,max(1,st+1),en):
            typ="rising" if cur==0 and new==1 else "falling"; cur=new
            if a.edge!="both" and a.edge!=typ: continue
            w.writerow([n,tstr((n-base)/s.hz),typ,new,"" if last is None else tstr((n-last)/s.hz)]); last=n; count+=1
        print(f"Wrote {count:,} edges: {a.output}")

def pulse_iter(s,i,st,en,min_us,max_us):
    cur=s.bit(i,st); rise=prev=None
    for n,new in s.rows(i,max(1,st+1),en):
        if cur==0 and new==1: rise=n
        elif cur==1 and new==0 and rise is not None:
            width=(n-rise)*1e6/s.hz; period=None if prev is None else (rise-prev)*1e6/s.hz; prev=rise
            if (min_us is None or width>=min_us) and (max_us is None or width<=max_us): yield rise,n,width,period
            rise=None
        cur=new

def pct(w,lo,hi,mx):
    if lo is None or hi is None: return None
    if hi==lo: raise DSLError("PWM map endpoints must differ")
    return (w-lo)*mx/(hi-lo)

def pwm(a):
    with DSL(a.dsl) as s:
        i,name=s.resolve(a.channel); st,en=span(s,a.start_s,a.end_s); ps=list(pulse_iter(s,i,st,en,a.min_us,a.max_us))
        if not ps: raise DSLError("No matching PWM pulses")
        ws=[x[2] for x in ps]; periods=[x[3] for x in ps if x[3] is not None]
        print(f"Channel: CH{i} ({name})\nPulse count: {len(ps):,}\nHIGH width median: {statistics.median(ws):.6f} us\nHIGH width min/max: {min(ws):.6f} / {max(ws):.6f} us")
        if periods:
            m=statistics.median(periods); print(f"Period median: {m:.6f} us\nFrequency median: {1e6/m:.6f} Hz")
        if a.map_low_us is not None and a.map_high_us is not None: print(f"Command median: {statistics.median(pct(w,a.map_low_us,a.map_high_us,a.map_max_pct) for w in ws):.3f} %")
        if a.show_segments:
            seg=[]; first=0; ref=ws[0]
            for k in range(1,len(ws)):
                if abs(ws[k]-ref)>a.segment_tolerance_us:
                    if k-first>=a.segment_min_pulses: seg.append((first,k))
                    first=k; ref=ws[k]
            if len(ws)-first>=a.segment_min_pulses: seg.append((first,len(ws)))
            print("\nStart(s)     End(s)       Pulses   Median(us)   Command(%)")
            for lo,hi in seg:
                med=statistics.median(ws[lo:hi]); q=pct(med,a.map_low_us,a.map_high_us,a.map_max_pct); print(f"{ps[lo][0]/s.hz:10.6f}  {ps[hi-1][1]/s.hz:10.6f}  {hi-lo:7d}  {med:11.3f}  {('-' if q is None else f'{q:.2f}'):>10}")
        if a.output:
            with open(a.output,"w",newline="",encoding="utf-8") as f:
                w=csv.writer(f); w.writerow(["rise_time_s","fall_time_s","high_us","period_us","frequency_hz","duty_pct","command_pct"])
                for r,fa,wi,pe in ps:
                    q=pct(wi,a.map_low_us,a.map_high_us,a.map_max_pct); w.writerow([tstr(r/s.hz),tstr(fa/s.hz),f"{wi:.6f}","" if pe is None else f"{pe:.6f}","" if pe is None else 1e6/pe,"" if pe is None else 100*wi/pe,"" if q is None else q])
            print(f"Wrote: {a.output}")

def plot(a):
    try: import matplotlib.pyplot as plt
    except ImportError as e: raise DSLError("plot requires matplotlib: py -m pip install matplotlib") from e
    with DSL(a.dsl) as s:
        cs=chans(s,a.channels); st,en=span(s,a.start_s,a.end_s); fig,ax=plt.subplots(figsize=(12,max(3.5,1.2+0.8*len(cs)))); yt=[]; labels=[]
        for row,(i,name) in enumerate(cs):
            cur=s.bit(i,st); tr=list(s.rows(i,max(1,st+1),en))
            if len(tr)>a.max_transitions: raise DSLError(f"CH{i} has {len(tr):,} transitions; narrow the time window")
            xs=[st/s.hz]; ys=[row*2+cur]
            for n,new in tr: x=n/s.hz; xs.extend([x,x]); ys.extend([row*2+cur,row*2+new]); cur=new
            xs.append(en/s.hz); ys.append(row*2+cur); ax.plot(xs,ys,linewidth=1.0); yt.append(row*2+0.5); labels.append(f"CH{i} ({name})")
        ax.set_xlabel("Time (s)"); ax.set_yticks(yt,labels); ax.set_xlim(st/s.hz,en/s.hz); ax.grid(True,axis="x",alpha=0.25); fig.tight_layout(); fig.savefig(a.output,dpi=a.dpi); plt.close(fig); print(f"Wrote: {a.output}")

def parser():
    p=argparse.ArgumentParser(description="DSView/DSLogic .dsl toolbox (read-only, non-RLE)"); p.add_argument("--version",action="version",version=f"%(prog)s {VERSION}"); sub=p.add_subparsers(dest="cmd",required=True)
    q=sub.add_parser("info"); q.add_argument("dsl"); q.set_defaults(fn=info)
    q=sub.add_parser("check"); q.add_argument("dsl"); q.set_defaults(fn=check)
    q=sub.add_parser("stats"); q.add_argument("dsl"); q.add_argument("--channels",nargs="+"); q.add_argument("--start-s",type=float); q.add_argument("--end-s",type=float); q.set_defaults(fn=stats)
    q=sub.add_parser("export-csv"); q.add_argument("dsl"); q.add_argument("-o","--output",required=True); q.add_argument("--channels",nargs="+"); q.add_argument("--start-s",type=float); q.add_argument("--end-s",type=float); q.add_argument("--relative-time",action="store_true"); q.set_defaults(fn=export_csv)
    q=sub.add_parser("edges"); q.add_argument("dsl"); q.add_argument("--channel",required=True); q.add_argument("--edge",choices=["both","rising","falling"],default="both"); q.add_argument("-o","--output",required=True); q.add_argument("--start-s",type=float); q.add_argument("--end-s",type=float); q.add_argument("--relative-time",action="store_true"); q.set_defaults(fn=edges)
    q=sub.add_parser("pwm"); q.add_argument("dsl"); q.add_argument("--channel",required=True); q.add_argument("-o","--output"); q.add_argument("--start-s",type=float); q.add_argument("--end-s",type=float); q.add_argument("--min-us",type=float); q.add_argument("--max-us",type=float); q.add_argument("--map-low-us",type=float); q.add_argument("--map-high-us",type=float); q.add_argument("--map-max-pct",type=float,default=100); q.add_argument("--show-segments",action="store_true"); q.add_argument("--segment-tolerance-us",type=float,default=5); q.add_argument("--segment-min-pulses",type=int,default=3); q.set_defaults(fn=pwm)
    q=sub.add_parser("plot"); q.add_argument("dsl"); q.add_argument("--channels",nargs="+"); q.add_argument("--start-s",type=float,default=0); q.add_argument("--end-s",type=float,required=True); q.add_argument("-o","--output",required=True); q.add_argument("--max-transitions",type=int,default=200000); q.add_argument("--dpi",type=int,default=150); q.set_defaults(fn=plot)
    return p

def main():
    a=parser().parse_args()
    try: a.fn(a); return 0
    except (DSLError,OSError,ValueError,json.JSONDecodeError,zipfile.BadZipFile) as e: print(f"ERROR: {e}",file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())
