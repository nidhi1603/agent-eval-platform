import sys, json, collections
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
import bench
from bench import pins
from loguru import logger; logger.remove()
from tau2.runner.helpers import get_tasks
dev = pins.load_split()["dev"]
tasks = get_tasks("banking_knowledge", task_ids=dev)
names = collections.Counter()
rows=[]
for t in tasks:
    acts = t.evaluation_criteria.actions or []
    ns = [(a.requestor, a.name, (a.arguments or {}).get("agent_tool_name") or (a.arguments or {}).get("discoverable_tool_name")) for a in acts]
    for n in ns: names[(n[0],n[1])]+=1
    rows.append(dict(id=t.id, ndocs=len(t.required_documents or []), nacts=len(acts),
        agent_disc=any(a.name in ("call_discoverable_agent_tool","unlock_discoverable_agent_tool") for a in acts),
        user_disc=any(a.name in ("give_discoverable_user_tool","call_discoverable_user_tool") for a in acts),
        transfer=any("transfer" in a.name for a in acts),
        logv=any(a.name=="log_verification" for a in acts),
        basis=[str(b.value) for b in t.evaluation_criteria.reward_basis],
        seq=[f"{r[0][0]}:{r[1]}{'('+r[2]+')' if r[2] else ''}" for r in ns]))
for r in rows: print(r["id"], r["ndocs"], r["nacts"], r["agent_disc"], r["user_disc"], r["transfer"], r["logv"], r["basis"], r["seq"])
print(names)
import statistics as st
def dist(k): v=[r[k] for r in rows]; return dict(min=min(v), median=st.median(v), mean=round(st.mean(v),2), max=max(v), hist=dict(sorted(collections.Counter(v).items())))
print("ndocs", dist("ndocs")); print("nacts", dist("nacts"))
for k in ["agent_disc","user_disc","transfer","logv"]: print(k, sum(r[k] for r in rows), "/", len(rows))
print("any disc", sum(r["agent_disc"] or r["user_disc"] for r in rows))
print("basis", collections.Counter(tuple(r["basis"]) for r in rows))
json.dump(rows, open("taskstats.json","w"), indent=1)
