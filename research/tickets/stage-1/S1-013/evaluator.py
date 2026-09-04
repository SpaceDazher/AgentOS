"""Recompute preparation metrics from validated observations, never producer grades."""
import argparse
import copy
import importlib.util
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("s1013_runner", HERE / "runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)
contract = runner.contract
canonical, sha = contract.canonical, runner.sha
MEASURES = ("C1", "C2", "C3", "C4", "C5")
TARGETS = {"C1": .9, "C2": .95, "C3": .85, "C4": .95, "C5": 30}

def load_json(path):
    return contract.loads(Path(path).read_text(encoding="utf-8"))

def wilson(hits, total, z=1.96):
    if total == 0: return None
    if type(hits) is not int or type(total) is not int or not 0 <= hits <= total:
        raise ValueError("invalid count")
    center=(hits+z*z/2)/(total+z*z)
    half=z*math.sqrt(hits*(total-hits)/total+z*z/4)/(total+z*z)
    return [round(max(0,center-half),6),round(min(1,center+half),6)]

def verified_observations(items):
    if not isinstance(items,list) or not items: raise ValueError("empty observations")
    seen=set()
    for item in items:
        if item.get("output_sha256") != contract.digest({k:v for k,v in item.items() if k!="output_sha256"}):
            raise ValueError("observation hash mismatch")
        if item.get("status")=="ok":
            doc=item.get("record")
            if not isinstance(doc,dict): raise ValueError("missing raw observations")
            check=runner.import_session(doc.get("session"),doc.get("events"),doc.get("answers"),seen)
            if check != {k:v for k,v in item.items() if k!="output_sha256"}:
                raise ValueError("observation revalidation failed")
        elif item.get("status") not in ("rejected","quarantined"):
            raise ValueError("unknown import status")
    return items

def records(observations, sessions_dir):
    cache={}
    # Compatibility for direct unit probes. CLI always uses bound embedded records.
    if any(o.get("status")=="ok" and "record" not in o for o in observations):
        for path in Path(sessions_dir).glob("*.session.json"):
            stem=path.name[:-len(".session.json")]
            sess=load_json(path)
            cache[sess["session_id"]]={"session":sess,
                "events":load_json(path.with_name(stem+".events.json")),
                "answers":load_json(path.with_name(stem+".answers.json"))}
    for obs in observations:
        if obs.get("status")=="ok":
            doc=obs.get("record") or cache.get(obs["session_id"])
            if doc is None: raise ValueError("missing session")
            yield obs,doc

def score_measures(observations,sessions_dir):
    tallies={m:{"n":0,"correct":0,"missing":0} for m in MEASURES}
    tallies["C5"].update(latencies_ms=[],max_ms=None)
    oracle=contract.load("rubric.json")["synthetic_answer_oracle"]
    expected_agents=set(contract.load("pilot-protocol.json")["mock_agents"])
    seen=set()
    for obs,doc in records(observations,sessions_dir):
        pid=obs.get("participant_id",doc["session"].get("participant_id",obs["session_id"]))
        if pid in seen: raise ValueError("duplicate participant")
        seen.add(pid)
        responses=doc["answers"]["responses"]
        if len({r["measure"] for r in responses})!=len(responses): raise ValueError("duplicate measure")
        responses={r["measure"]:r for r in responses}
        events=doc["events"]["events"]
        presented={}
        for event in events:
            p=event.get("prompt_id") or ""
            if event["type"]=="prompt_displayed" and p.split("-")[0] in MEASURES:
                m=p.split("-")[0]
                if m in presented: raise ValueError("duplicate measure presentation")
                presented[m]=event["t_ms"]
        # Direct historical unit probes contain sparse presentations; their
        # explicit answers still cannot turn into multiple participant counts.
        for m in set(responses) | set(presented):
            if m=="C5": continue
            tally=tallies[m]; tally["n"]+=1
            response=responses.get(m)
            if not response:
                tally["missing"]+=1; continue
            primary=response.get("primary") or {}
            rater=response.get("rater2") or {}
            if rater.get("agree") is not True or rater.get("value")!=primary.get("value"):
                tally["missing"]+=1; continue
            # Closed synthetic fixture oracle only. This never grades humans:
            # exact semantic control plus coding agreement, no adjudicated flag.
            if primary.get("value")==oracle[m]["value"] and primary.get("explanation")==oracle[m]["explanation"]:
                tally["correct"]+=1
        if "C5" in presented:
            tally=tallies["C5"]; tally["n"]+=1
            outcomes=[x for x in events if x["type"] in ("stop_confirmed","stop_failed")]
            if not outcomes:
                tally["missing"]+=1; continue
            outcome=outcomes[0]; latency=outcome["t_ms"]-presented["C5"]
            if latency<0: raise ValueError("backwards stop time")
            tally["latencies_ms"].append(latency)
            acks=outcome.get("acknowledgements") or []
            if outcome["type"]=="stop_confirmed" and outcome.get("acknowledged") is True and len(acks)==len(expected_agents) and {a["agent_id"] for a in acks}==expected_agents and all(a["state"]=="stopped" for a in acks) and latency<=30000:
                tally["correct"]+=1
    tallies["C5"]["latencies_ms"].sort()
    tallies["C5"]["max_ms"]=max(tallies["C5"]["latencies_ms"],default=None)
    return tallies

def score_approvals(observations,sessions_dir,scenarios):
    oracle={p["prompt_id"]:p["oracle"] for b in scenarios["approval_blocks"] if b["feasible"] for p in b["prompts"]}
    participants={}
    for obs,doc in records(observations,sessions_dir):
        events=doc["events"]["events"]
        shown={e["prompt_id"] for e in events if e["type"]=="prompt_displayed" and e.get("prompt_id") in oracle}
        decisions={e["prompt_id"]:e.get("decision") for e in events if e["type"]=="decision"}
        if shown:
            participants[obs["participant_id"]]={"n":len(shown),"correct":sum(decisions.get(p)==oracle[p] for p in shown),"missing":sum(p not in decisions for p in shown)}
    n=sum(p["n"] for p in participants.values()); correct=sum(p["correct"] for p in participants.values())
    return {"n":n,"correct":correct,"accuracy":correct/n if n else None,"participants":len(participants),"per_participant":participants}

def prompt_rate(observations,sessions_dir):
    blocks={b["block"]:b for b in contract.load("scenario-manifest.json")["approval_blocks"]}
    roles={}; load_probes=[]
    for obs,doc in records(observations,sessions_dir):
        active=None; since=None; times={}; prompts={}; fatigue=[]; incomplete=False
        for event in doc["events"]["events"]:
            kind=event["type"]; t=event["t_ms"]
            if kind=="block_started":
                active=event["block_id"]; since=t; times[active]=0; prompts[active]=set()
            elif kind=="block_paused":
                times[active]+=t-since; since=None
            elif kind=="block_resumed": since=t
            elif kind=="block_ended":
                if since is not None: times[active]+=t-since
                active=since=None
            elif kind=="prompt_displayed" and active is not None:
                prompts[active].add(event["prompt_id"])
            elif kind=="fatigue_report": fatigue.append(event["fatigue"])
        if active is not None:
            incomplete=True
            times.pop(active,None)
        role=roles.setdefault(obs["role"],{"participants":[]})
        count=ms=0
        for bid, duration in times.items():
            if not blocks[bid]["feasible"]:
                load_probes.append({"session_id":obs["session_id"],"block_id":bid,"reason":"frozen infeasible scenario"});continue
            count+=len(prompts[bid]); ms+=duration
        role["participants"].append({"participant_id":obs["participant_id"],"prompts":count,"active_ms":ms,
            "rate":count*3600000/ms if ms>0 else None,"incomplete":incomplete,"fatigue":fatigue})
    for role in roles.values():
        entries=role["participants"]; rates=[e["rate"] for e in entries if e["rate"] is not None]
        ms=sum(e["active_ms"] for e in entries); count=sum(e["prompts"] for e in entries)
        role.update(prompts=count,active_minutes=ms/60000,
            prompts_per_hour=count*3600000/ms if ms else None,
            participant_n=len(entries), rate_range=[min(rates),max(rates)] if rates else None,
            uncertainty="participant range only; insufficient human data for calibrated CI",
            note="measured active approval blocks, excludes rest/comprehension/infeasible; synthetic only")
    return {"load_probes":load_probes,"by_role":roles}

def evaluate(run_dir,ticket_dir):
    observations=verified_observations(load_json(Path(run_dir)/"observations.json")["observations"])
    sessions=Path(ticket_dir)/"synthetic/sessions"
    tallies=score_measures(observations,sessions); measures={}
    for m,t in tallies.items():
        n,c=t["n"],t["correct"]; rate=c/n if n else None
        target=1.0 if m=="C5" else TARGETS[m]
        measures[m]={**t,"rate":rate,"wilson":wilson(c,n),"disposition":"inconclusive" if not n else "target_met" if rate>=target else "not_met"}
    return {"schema":"agentos.s1-013.metrics/v1","synthetic":True,"human_n":0,
        "sessions":len(observations),"ok":sum(o["status"]=="ok" for o in observations),
        "rejected":sum(o["status"]=="rejected" for o in observations),
        "quarantined":sum(o["status"]=="quarantined" for o in observations),
        "effective_participants":len({o["participant_id"] for o in observations if o["status"]=="ok"}),
        "measures":measures,"approvals":score_approvals(observations,sessions,contract.load("scenario-manifest.json")),
        "prompt_rate_by_role":prompt_rate(observations,sessions),"protocol_problems":[],
        "note":"Synthetic fixture oracle only; free responses require human coding before human use."}

def probes(run_dir,ticket_dir):
    obs=verified_observations(load_json(Path(run_dir)/"observations.json")["observations"])
    by={o["session_id"]:o for o in obs}; src=Path(ticket_dir)/"synthetic/sessions"; results={}
    def record(k,v): results[k]={"passed":bool(v)}
    def selected(s): return [by[s]] if s in by else []
    a=score_measures(selected("S-PA"),src)
    record("A",a["C2"]["n"]==1 and a["C2"]["correct"]==0 and a["C4"]["correct"]==0)
    rate=prompt_rate(obs,src)
    record("B",any(x["session_id"]=="S-PB" for x in rate["load_probes"]))
    record("C",all(by.get(s,{}).get("status")=="rejected" for s in ("S-PC1","S-PC2","S-PC3")))
    d=score_measures(selected("S-PD"),src)["C5"]
    record("D",d["n"]==1 and d["correct"]==0)
    record("E",len(selected("S-PE"))==1 and by.get("S-PE",{}).get("participant_id")=="P-HHHHHH")
    bad=copy.deepcopy(obs); bad[0]["output_sha256"]="0"*64
    try: verified_observations(bad); refused=False
    except ValueError: refused=True
    record("F",refused)
    g=score_approvals(selected("S-PG"),src,contract.load("scenario-manifest.json"))
    record("G",g["n"]==1 and g["correct"]==1)
    record("H",by.get("S-PH",{}).get("status")=="quarantined")
    return {"schema":"agentos.s1-013.probes/v1","synthetic":True,"probes":results,"all_pass":all(x["passed"] for x in results.values())}

def main():
    p=argparse.ArgumentParser()
    for key in ("run","protocol","out","probes"): p.add_argument("--"+key,required=True)
    a=p.parse_args()
    try:
        metrics=evaluate(Path(a.run),Path(a.protocol)); pr=probes(Path(a.run),Path(a.protocol))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print("INVALID evaluation input:",type(exc).__name__);return 1
    for path,obj in ((a.out,metrics),(a.probes,pr)):
        Path(path).write_text(json.dumps(obj,indent=2)+"\n",encoding="utf-8",newline="\n")
    return 0 if pr["all_pass"] else 1

if __name__=="__main__": raise SystemExit(main())
