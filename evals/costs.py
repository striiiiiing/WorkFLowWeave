"""Read exact AxonHub usage by response id; never infer cost from token count."""

import argparse
import json
import subprocess
from pathlib import Path

REMOTE = '''
import json,sqlite3
c=sqlite3.connect(database,uri=True);c.row_factory=sqlite3.Row
c.execute("PRAGMA query_only=ON")
result=[]
for record in records:
    matches=c.execute("SELECT id,model_id,reasoning_effort,status FROM requests WHERE external_id=?",
                      (record.get("response_id"),)).fetchall()
    if len(matches)!=1:
        result.append({"call_id":record["call_id"],"status":"ledger_request_missing"});continue
    request=dict(matches[0])
    usage=[dict(r) for r in c.execute("SELECT id,model_id,prompt_tokens,completion_tokens,total_tokens,prompt_cached_tokens,total_cost FROM usage_logs WHERE request_id=? ORDER BY id",(request["id"],))]
    result.append({"call_id":record["call_id"],"request":request,"usage":usage,
                   "status":"resolved" if usage else "ledger_usage_missing"})
print(json.dumps(result))
'''


def export(directory: Path, host: str, database: str) -> list[dict]:
    records = [json.loads(line) for line in (directory / "requests.jsonl").read_text().splitlines()]
    refs = [{"call_id": r["call_id"], "response_id": r.get("response_id")} for r in records]
    # stdin is Python source, not a shell command containing ids or credentials.
    script = "database=" + repr(database) + "\nrecords=json.loads(" + repr(json.dumps(refs)) + ")\n"
    process = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, "python3", "-"],
                             input="import json\n" + script + REMOTE, text=True, capture_output=True,
                             check=True, timeout=60)
    result = json.loads(process.stdout)
    (directory / "costs.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--host", default="myserver")
    parser.add_argument("--database", default="file:/home/user/opt/axonhub/data/axonhub.db?mode=ro")
    args = parser.parse_args()
    values = export(args.directory, args.host, args.database)
    print(json.dumps({"resolved": sum(r["status"] == "resolved" for r in values), "calls": len(values)}))
