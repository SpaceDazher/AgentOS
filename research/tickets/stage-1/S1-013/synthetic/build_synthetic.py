"""Generate explicit synthetic fixtures and the browser contract from canonical JSON."""
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
TICKET=HERE.parent
spec=importlib.util.spec_from_file_location("s1013_contract",TICKET/"contract.py")
contract=importlib.util.module_from_spec(spec);spec.loader.exec_module(contract)

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+"\n",encoding="utf-8",newline="\n")

def main():
    protocol=contract.load("pilot-protocol.json")
    scenarios=contract.load("scenario-manifest.json")
    rubric=contract.load("rubric.json")
    manifest=[]
    def add(name,sid,pid,role,tasks=(),block=None,prompt_ids=(),slow=False,consent=True,private=False,fatigue=0):
        sess={"session_id":sid,"participant_id":pid,"role":role,"protocol_version":protocol["protocol_version"],
            "contract_sha256":contract.digest(protocol),"cohort":"synthetic","synthetic":True,
            "started_at":"2026-09-04T00:00:00Z","completed_at":None,"excluded":None,
            "consent":{"given":consent,"version":protocol["consent_version"]}}
        if private: sess["contact"]="synthetic-person@example.test"
        events=[]; responses=[]; clock=0
        def ev(kind,**kw):
            nonlocal clock
            event={"seq":len(events),"t_ms":clock,"type":kind}
            event.update(kw);events.append(event);clock+=1000
        for m,correct in tasks:
            scenario=m+"-S1"
            ev("prompt_displayed",prompt_id=scenario)
            if correct is None: continue
            ev("answer",prompt_id=scenario)
            oracle=rubric["synthetic_answer_oracle"][m]
            value=oracle["value"] if correct else "the banner says everyone may read"
            explanation=oracle["explanation"] if correct else "repeat of banner"
            responses.append({"measure":m,"scenario_id":scenario,
                "primary":{"value":value,"explanation":explanation,"latency_ms":1000},
                "rater2":{"value":value,"agree":True},"adjudicated":"correct" if correct else "incorrect"})
        if name in ("happy-owner","happy-reviewer","probe-d"):
            ev("prompt_displayed",prompt_id="C5-S1")
            if slow: clock+=60000
            ev("stop_requested")
            if slow: ev("stop_failed",acknowledged=False)
            else: ev("stop_confirmed",acknowledged=True,acknowledgements=[{"agent_id":a,"state":"stopped"} for a in protocol["mock_agents"]])
        if block:
            ev("block_started",block_id=block)
            b=next(b for b in scenarios["approval_blocks"] if b["block"]==block)
            for pid2 in prompt_ids:
                p=next(p for p in b["prompts"] if p["prompt_id"]==pid2)
                ev("prompt_displayed",prompt_id=pid2,actor_shown=p["actor"],action_shown=p["action"],scope_shown=p["scope"],expiry_shown=p["expiry"] is not None)
                ev("decision",prompt_id=pid2,decision=p["oracle"])
            ev("block_ended",block_id=block)
        for _ in range(fatigue): ev("fatigue_report",fatigue="ok")
        answers={"session_id":sid,"responses":responses}
        edoc={"session_id":sid,"events":events}
        for suffix,doc in (("session",sess),("events",edoc),("answers",answers)):
            write(HERE/"sessions"/f"{name}.{suffix}.json",doc)
        status="quarantined" if private else "rejected" if not consent or name in ("probe-c-dup","probe-c-extra") else "ok"
        manifest.append({"session":name,"session_id":sid,"expect":{"import":status}})
    add("happy-owner","S-HO","P-AAAAAA","owner",(("C1",True),("C3",True),("C4",True)),"A",("AP-01","AP-02"))
    add("happy-reviewer","S-HR","P-BBBBBB","reviewer",(("C2",True),),"A",("AP-03",))
    add("probe-a","S-PA","P-CCCCCC","owner",(("C2",False),("C4",False)))
    add("probe-b","S-PB","P-DDDDDD","reviewer",block="IMPOSSIBLE",prompt_ids=("PX-001",))
    add("probe-c-dup","S-PC1","P-AAAAAA","reviewer",(("C1",None),))
    add("probe-c-extra","S-PC3","BOT-1","owner",(("C1",None),))
    add("probe-c-noconsent","S-PC2","P-EEEEEE","owner",(("C1",None),),consent=False)
    add("probe-d","S-PD","P-GGGGGG","owner",slow=True)
    add("probe-e","S-PE","P-HHHHHH","reviewer",fatigue=300)
    add("probe-g","S-PG","P-IIIIII","owner",block="A",prompt_ids=("AP-02",))
    add("probe-h","S-PH","P-JJJJJJ","reviewer",private=True)
    write(HERE/"synthetic-manifest.json",{"schema":"agentos.s1-013.synthetic-manifest/v1","synthetic":True,"sessions":manifest,
        "note":"Synthetic tooling controls only. No human observations or human graders."})
    write(TICKET/"prototype/browser-contract.json",{"protocol":protocol,"contract_sha256":contract.digest(protocol),
        "scenarios":scenarios,"schemas":{n:contract.load("schemas/"+n+".schema.json") for n in ("session","events","answers")},
        "export_schema":"agentos.s1-013.export/v1"})
    print("generated",len(manifest),"synthetic sessions and canonical browser contract")
    return 0

if __name__=="__main__": raise SystemExit(main())
