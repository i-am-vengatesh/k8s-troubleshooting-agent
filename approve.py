#!/usr/bin/env python3
"""Human approval CLI for queued remediation proposals.

  python approve.py list
  python approve.py approve <id>
  python approve.py reject <id>

Uses YOUR kubeconfig (a human identity). The agent never runs this.
Every decision is appended to remediation/audit.jsonl.
"""
import json
import sys
import time

from kubernetes import client, config

from k8s_agents.remediation_tools import QUEUE_DIR, _load, _save, validate

AUDIT = f"{QUEUE_DIR}/audit.jsonl"


def audit(entry: dict) -> None:
    entry["time"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(AUDIT, "a") as f:
        f.write(json.dumps(entry) + "\n")


def apply(p: dict) -> str:
    config.load_kube_config()
    apps = client.AppsV1Api()
    ns, name, action, value = p["namespace"], p["deployment"], p["action"], p["value"]
    if action == "set_image":
        dep = apps.read_namespaced_deployment(name, ns)
        c = dep.spec.template.spec.containers[0].name
        body = {"spec": {"template": {"spec": {"containers": [{"name": c, "image": value}]}}}}
    elif action == "set_memory_limit":
        dep = apps.read_namespaced_deployment(name, ns)
        c = dep.spec.template.spec.containers[0].name
        body = {"spec": {"template": {"spec": {"containers": [
            {"name": c, "resources": {"limits": {"memory": value}}}]}}}}
    elif action == "scale":
        apps.patch_namespaced_deployment_scale(name, ns, {"spec": {"replicas": int(value)}})
        return f"scaled {name} to {value}"
    elif action == "restart":
        body = {"spec": {"template": {"metadata": {"annotations": {
            "kubectl.kubernetes.io/restartedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}}}}}
    else:
        raise ValueError(f"unknown action {action}")
    apps.patch_namespaced_deployment(name, ns, body)
    return f"{action} applied to {name}"


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"list", "approve", "reject"}:
        sys.exit(__doc__)
    items = _load()
    if sys.argv[1] == "list":
        for p in items:
            print(f"{p['id']}  [{p['status']}]  {p['namespace']}/{p['deployment']}  "
                  f"{p['action']} {p['value']}\n    reason: {p['reason']}")
        return
    if len(sys.argv) < 3:
        sys.exit("proposal id required")
    p = next((x for x in items if x["id"] == sys.argv[2]), None)
    if not p or p["status"] != "pending":
        sys.exit("no pending proposal with that id")
    if sys.argv[1] == "reject":
        p["status"] = "rejected"
        _save(items)
        audit({"id": p["id"], "decision": "rejected"})
        return
    err = validate(p["namespace"], p["action"], p["value"])  # re-check at execution time
    if err:
        sys.exit(f"refusing to apply: {err}")
    print(f"About to apply: {p['action']} {p['value']} on {p['namespace']}/{p['deployment']}")
    answer = input("Type 'yes' to confirm: ")
    if answer.strip().lower() != "yes":
        sys.exit(f"cancelled (received {answer!r})")
    try:
        result = apply(p)
        p["status"] = "applied"
    except Exception as e:  # report and keep the proposal for inspection
        result = f"failed: {e}"
        p["status"] = "failed"
    _save(items)
    audit({"id": p["id"], "decision": "approved", "result": result})
    print(result)


if __name__ == "__main__":
    main()
