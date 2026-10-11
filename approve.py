#!/usr/bin/env python3
"""Human approval CLI for queued remediation proposals, with post-fix verification.

  python approve.py list
  python approve.py approve <id> [--no-verify]
  python approve.py reject <id>
  python approve.py verify <id>      # re-check an applied proposal later

Uses YOUR kubeconfig (a human identity). The agent never runs this.
After applying a fix, plain code (not an LLM) watches the rollout and reports
whether the workload recovered. Every decision and outcome is appended to
remediation/audit.jsonl.
"""
import json
import os
import sys
import time

from kubernetes import client, config

from k8s_agents.remediation_tools import QUEUE_DIR, _load, _save, validate

AUDIT = f"{QUEUE_DIR}/audit.jsonl"
VERIFY_TIMEOUT = 180   # give up after this many seconds
STABLE_SECONDS = 30    # must stay healthy this long to count as recovered
POLL_SECONDS = 5


def audit(entry: dict) -> None:
    os.makedirs(QUEUE_DIR, exist_ok=True)
    entry["time"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(AUDIT, "a") as f:
        f.write(json.dumps(entry) + "\n")


def clients():
    config.load_kube_config()
    return client.AppsV1Api(), client.CoreV1Api()


# ---------- applying a fix ----------

def apply(p: dict, apps) -> str:
    ns, name, action, value = p["namespace"], p["deployment"], p["action"], p["value"]
    if action in ("set_image", "set_memory_limit"):
        dep = apps.read_namespaced_deployment(name, ns)
        c = dep.spec.template.spec.containers[0].name
        if action == "set_image":
            container = {"name": c, "image": value}
        else:
            container = {"name": c, "resources": {"limits": {"memory": value}}}
        body = {"spec": {"template": {"spec": {"containers": [container]}}}}
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


# ---------- verifying the result ----------

def _current_pods(apps, core, ns, name):
    """Return (deployment, pods of the deployment's newest ReplicaSet)."""
    dep = apps.read_namespaced_deployment(name, ns)
    sel = ",".join(f"{k}={v}" for k, v in dep.spec.selector.match_labels.items())
    rss = apps.list_namespaced_replica_set(ns, label_selector=sel).items
    mine = [r for r in rss
            if any(o.uid == dep.metadata.uid for o in (r.metadata.owner_references or []))]
    if not mine:
        return dep, []
    newest = max(mine, key=lambda r: int(
        (r.metadata.annotations or {}).get("deployment.kubernetes.io/revision", "0")))
    pod_hash = (newest.metadata.labels or {}).get("pod-template-hash")
    if not pod_hash:
        return dep, []
    pods = core.list_namespaced_pod(ns, label_selector=f"{sel},pod-template-hash={pod_hash}").items
    return dep, [p for p in pods if not p.metadata.deletion_timestamp]


def _pod_state(p) -> dict:
    statuses = p.status.container_statuses or []
    state = {"pod": p.metadata.name, "ready": bool(statuses) and all(cs.ready for cs in statuses),
             "restarts": 0, "waiting": None, "last_kill": None}
    for cs in statuses:
        state["restarts"] += cs.restart_count or 0
        if cs.state and cs.state.waiting:
            state["waiting"] = cs.state.waiting.reason
        if cs.last_state and cs.last_state.terminated:
            state["last_kill"] = cs.last_state.terminated.reason
    return state


def snapshot(apps, core, ns, name) -> dict:
    """Restart counts per pod before the change, so only NEW restarts count as failures."""
    try:
        _, pods = _current_pods(apps, core, ns, name)
        return {s["pod"]: s["restarts"] for s in map(_pod_state, pods)}
    except client.ApiException:
        return {}


def _describe(states) -> str:
    if not states:
        return "no pods"
    return "; ".join(f"{s['pod']}: ready={s['ready']} restarts={s['restarts']} "
                     f"waiting={s['waiting']} last_kill={s['last_kill']}" for s in states)


def verify(apps, core, ns, name, baseline=None, timeout=None, stable=None,
           poll=None, quiet=False) -> dict:
    """Watch the rollout. Returns {'outcome': 'recovered'|'not_recovered', 'detail': str}."""
    timeout = VERIFY_TIMEOUT if timeout is None else timeout
    stable = STABLE_SECONDS if stable is None else stable
    poll = POLL_SECONDS if poll is None else poll
    baseline = baseline or {}
    start = time.time()
    stable_since = None
    last_print = 0.0
    states = []
    if not quiet:
        print(f"Verifying (up to {timeout}s; must stay healthy for {stable}s)...")
    while time.time() - start < timeout:
        try:
            dep, pods = _current_pods(apps, core, ns, name)
        except client.ApiException as e:
            return {"outcome": "not_recovered", "detail": f"could not read deployment: {e.status} {e.reason}"}
        states = [_pod_state(p) for p in pods]
        desired = dep.spec.replicas or 0

        crashed = [s for s in states
                   if s["restarts"] > baseline.get(s["pod"], 0) or s["waiting"] == "CrashLoopBackOff"]
        if crashed:
            return {"outcome": "not_recovered", "detail": _describe(crashed)}

        gen_ok = (dep.status.observed_generation or 0) >= dep.metadata.generation
        if desired == 0:
            healthy = gen_ok and not states
        else:
            ready = [s for s in states if s["ready"]]
            healthy = gen_ok and len(ready) >= desired and len(ready) == len(states)

        now = time.time()
        if healthy:
            stable_since = stable_since or now
            if now - stable_since >= stable:
                return {"outcome": "recovered", "detail": _describe(states)}
        else:
            stable_since = None
        if not quiet and now - last_print >= 15:
            print(f"  {int(now - start):>3}s  {_describe(states)}")
            last_print = now
        time.sleep(poll)
    return {"outcome": "not_recovered",
            "detail": f"not stable within {timeout}s: {_describe(states)}"}


def report(v: dict) -> None:
    label = "RECOVERED" if v["outcome"] == "recovered" else "NOT RECOVERED"
    print(f"Verification: {label}\n  {v['detail']}")


# ---------- CLI ----------

def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args or args[0] not in {"list", "approve", "reject", "verify"}:
        sys.exit(__doc__)
    items = _load()
    cmd = args[0]

    if cmd == "list":
        for p in items:
            v = p.get("verification")
            tail = f"  -> {v['outcome']}" if v else ""
            print(f"{p['id']}  [{p['status']}]  {p['namespace']}/{p['deployment']}  "
                  f"{p['action']} {p['value']}{tail}\n    reason: {p['reason']}")
        return

    if len(args) < 2:
        sys.exit("proposal id required")
    p = next((x for x in items if x["id"] == args[1]), None)

    if cmd == "verify":
        if not p or p["status"] != "applied":
            sys.exit("no applied proposal with that id")
        apps, core = clients()
        v = verify(apps, core, p["namespace"], p["deployment"])
        p["verification"] = v
        _save(items)
        audit({"id": p["id"], "decision": "verified", "verification": v})
        report(v)
        return

    if not p or p["status"] != "pending":
        sys.exit("no pending proposal with that id")
    if cmd == "reject":
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

    apps, core = clients()
    baseline = snapshot(apps, core, p["namespace"], p["deployment"])
    try:
        result = apply(p, apps)
        p["status"] = "applied"
    except Exception as e:  # report and keep the proposal for inspection
        result = f"failed: {e}"
        p["status"] = "failed"
    _save(items)
    print(result)

    entry = {"id": p["id"], "decision": "approved", "result": result}
    if p["status"] == "applied" and "--no-verify" not in flags:
        try:
            v = verify(apps, core, p["namespace"], p["deployment"], baseline)
        except KeyboardInterrupt:
            v = {"outcome": "not_recovered", "detail": "verification interrupted"}
        p["verification"] = v
        _save(items)
        entry["verification"] = v
        report(v)
    audit(entry)


if __name__ == "__main__":
    main()
