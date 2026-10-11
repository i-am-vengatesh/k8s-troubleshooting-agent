"""Proposal-only remediation tool.

The agent can WRITE A PROPOSAL to a local queue file. It cannot change the
cluster. A human runs approve.py to review and apply a proposal.
"""
import json
import os
import re
import time
import uuid

QUEUE_DIR = os.environ.get("REMEDIATION_DIR", "./remediation")
QUEUE_FILE = os.path.join(QUEUE_DIR, "pending.json")
ALLOWED_NAMESPACES = set(os.environ.get("ALLOWED_NAMESPACES", "agent-test").split(","))
ALLOWED_ACTIONS = {"set_image", "set_memory_limit", "scale", "restart"}

_MEM = re.compile(r"^\d{1,5}(Mi|Gi)$")
_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9._-]+)?$")


def _load() -> list:
    try:
        with open(QUEUE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(items: list) -> None:
    os.makedirs(QUEUE_DIR, exist_ok=True)
    with open(QUEUE_FILE, "w") as f:
        json.dump(items, f, indent=2)


def validate(namespace: str, action: str, value: str) -> str | None:
    """Return an error string, or None if the request is acceptable."""
    if namespace not in ALLOWED_NAMESPACES:
        return f"namespace '{namespace}' is not allowed"
    if action not in ALLOWED_ACTIONS:
        return f"action must be one of {sorted(ALLOWED_ACTIONS)}"
    if action == "set_memory_limit" and not _MEM.match(value):
        return "value must look like 256Mi or 1Gi"
    if action == "set_image" and not _IMAGE.match(value):
        return "value must be a valid image reference like nginx:1.27"
    if action == "scale" and not (value.isdigit() and 0 <= int(value) <= 5):
        return "value must be an integer from 0 to 5"
    return None


def propose_remediation(namespace: str, deployment: str, action: str,
                        value: str = "", reason: str = "") -> dict:
    """Queue a remediation proposal for human approval. This does NOT change the cluster.

    Args:
        namespace: Namespace of the deployment.
        deployment: Deployment name (not the pod name).
        action: One of set_image, set_memory_limit, scale, restart.
        value: New image (set_image), memory like 256Mi (set_memory_limit),
            replica count 0-5 (scale). Leave empty for restart.
        reason: One sentence of evidence for why this fix is proposed.
    """
    err = validate(namespace, action, value)
    if err:
        return {"status": "rejected", "error": err}
    items = _load()
    proposal = {
        "id": uuid.uuid4().hex[:8],
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "namespace": namespace,
        "deployment": deployment,
        "action": action,
        "value": value,
        "reason": reason[:300],
        "status": "pending",
    }
    items.append(proposal)
    _save(items)
    return {"status": "queued", "id": proposal["id"],
            "note": "Awaiting human approval via approve.py. Nothing was executed."}
