import sys, json, re, glob, os
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
import bench
from loguru import logger; logger.remove()
from bench.diagnostics import live_traces
from bench.continuation import agent_visible
from tau2.runner.helpers import get_tasks
from bench import pins
DEV=set(pins.load_split()["dev"])
DOCDIR=os.environ["TAU2_DATA_DIR"]+"/tau2/domains/banking_knowledge/documents"
docs={}
for f in glob.glob(DOCDIR+"/*.json"):
    d=json.load(open(f)); docs[os.path.basename(f)[:-5]]=json.dumps(d)
DOCID=re.compile(r"ID:\s*(doc_\S+)")

def parse(x):
    if isinstance(x,str):
        try: return json.loads(x)
        except Exception: return {"_raw":x}
    return dict(x or {})

def norm(requestor,name,args):
    """(requestor, underlying name, args) for comparisons"""
    args=args or {}
    if name=="call_discoverable_agent_tool": return (requestor,"CALL:"+str(args.get("agent_tool_name")),parse(args.get("arguments")))
    if name=="unlock_discoverable_agent_tool": return (requestor,"UNLOCK:"+str(args.get("agent_tool_name")),{})
    if name=="give_discoverable_user_tool": return (requestor,"GIVE:"+str(args.get("discoverable_tool_name")),{})
    if name=="call_discoverable_user_tool": return (requestor,"UCALL:"+str(args.get("discoverable_tool_name")),parse(args.get("arguments")))
    return (requestor,name,dict(args))

def discname(name,args):
    args=args or {}
    return args.get("agent_tool_name") or args.get("discoverable_tool_name")

out=[]
for p in live_traces():
    t=json.loads(p.read_text()); tid=t["task"]["id"]; assert tid in DEV
    task=get_tasks("banking_knowledge",task_ids=[tid])[0]
    var=((t.get("config") or {}).get("agent") or {}).get("variant",{}).get("name","baseline")
    msgs=t["messages"]; n=len(msgs)
    callname={}
    calls=[]
    for m in msgs:
        for c in m.get("tool_calls") or []:
            callname[c["id"]]=c["name"]
            req="user" if m["role"]=="user" else "assistant"
            calls.append((m["i"],norm(req,c["name"],c.get("arguments")),c))
    results={m["tool_call_id"]:m for m in msgs if m["role"]=="tool"}
    # retrieval
    req=list(task.required_documents or [])
    seen={}; kb_calls=0; retrieved_all=[]
    for m in msgs:
        if m["role"]=="tool" and m.get("requestor")=="assistant" and callname.get(m["tool_call_id"])=="KB_search":
            kb_calls+=1
            for d in DOCID.findall(m.get("content") or ""):
                seen.setdefault(d,m["i"]); retrieved_all.append(d)
    hit=[d for d in req if d in seen]
    first_req=min([seen[d] for d in hit],default=None)
    # agent-visible text for tool-name mentions
    vis=agent_visible(msgs,n)
    vis_tool_text=[(m["i"],m.get("content") or "") for m in vis if m["role"]=="tool"]
    def first_seen_name(nm):
        for i,txt in vis_tool_text:
            if nm and re.search(r"\b"+re.escape(nm)+r"\b",txt): return i
        return None
    # reference actions
    acts=[]
    for a in task.evaluation_criteria.actions or []:
        r=norm(a.requestor,a.name,a.arguments)
        same=[(i,x,c) for i,x,c in calls if x[0]==r[0] and x[1]==r[1]]
        cmpk=a.compare_args
        def eq(x):
            if cmpk is None: return x[2]==r[2] if r[1] not in ("log_verification",) else all(x[2].get(k)==v for k,v in r[2].items())
            return all(x[2].get(k)==r[2].get(k) for k in cmpk)
        matched=[i for i,x,c in same if (eq(x) if r[2] else True)]
        if matched: st="MATCH"; where=matched[0]; diff=None
        elif same:
            st="WRONG_ARGS"; where=same[0][0]
            x=same[0][1][2]; diff={k:(x.get(k),v) for k,v in r[2].items() if x.get(k)!=v}
        else: st="MISSING"; where=None; diff=None
        dn=discname(a.name,a.arguments)
        # docs mentioning this discoverable tool
        mention_docs=[d for d,txt in docs.items() if dn and dn in txt] if dn else []
        acts.append(dict(id=a.action_id,req=a.requestor,name=r[1],args=r[2],status=st,at=where,diff=diff,disc=dn,
                         name_seen_at=first_seen_name(dn) if dn else None,
                         docs_with_name=mention_docs, docs_with_name_required=[d for d in mention_docs if d in req],
                         docs_with_name_retrieved=[d for d in mention_docs if d in seen]))
    firstdiv=next((a for a in acts if a["status"]!="MATCH"),None)
    transfer=[i for i,x,c in calls if x[1]=="transfer_to_human_agents"]
    out.append(dict(trace=str(p.parent.name),task=tid,arm=var,reward=t["evaluation"]["reward"],
        db=t["evaluation"].get("db_check"),term=t["termination_reason"],n=n,
        req_docs=req,recall=f"{len(hit)}/{len(req)}",first_req_doc_at=first_req,hit=hit,kb_calls=kb_calls,
        n_unique_retrieved=len(set(retrieved_all)),
        acts=acts,first_div=firstdiv["id"] if firstdiv else None,
        transfer_at=transfer,ref_transfer=any(a["name"]=="transfer_to_human_agents" for a in acts),
        official_matches=[c["action_match"] for c in t["evaluation"].get("action_checks") or []]))
json.dump(out,open(os.path.dirname(__file__)+"/analysis.json","w"),indent=1,default=str)
for o in out:
    print(f"\n=== {o['trace']} {o['arm']} r={o['reward']} term={o['term']} n={o['n']} recall={o['recall']} firstreq@{o['first_req_doc_at']} kb={o['kb_calls']} xfer@{o['transfer_at']} refxfer={o['ref_transfer']}")
    print("   official:", "".join("1" if x else "0" for x in o["official_matches"]))
    print("   missing docs:", [d for d in o["req_docs"] if d not in o["hit"]])
    for a in o["acts"]:
        print(f"   {a['id']} {a['req'][0]} {a['name']:<55} {a['status']:<10} at={a['at']} seen@{a['name_seen_at']} docs_req={a['docs_with_name_required']} docs_retr={a['docs_with_name_retrieved']}" + (f" diff={a['diff']}" if a['diff'] else ""))
