from kubernetes import client, config

try:
    config.load_incluster_config()
except config.ConfigException:
    config.load_kube_config()

v1 = client.CoreV1Api()
MAX_LOG_CHARS = 3000


def list_unhealthy_pods(namespace: str) -> dict:
    """List pods in a namespace that are unhealthy, with the reason for each.

    Args:
        namespace: Kubernetes namespace to inspect.
    """
    result = []
    for p in v1.list_namespaced_pod(namespace).items:
        for cs in (p.status.container_statuses or []):
            reason, detail = None, None
            if cs.state.waiting:
                reason = cs.state.waiting.reason
                detail = cs.state.waiting.message
            elif cs.state.terminated and cs.state.terminated.exit_code != 0:
                reason = cs.state.terminated.reason
            elif not cs.ready and p.status.phase == "Running":
                reason = "NotReady"
            if reason:
                last = cs.last_state.terminated if cs.last_state else None
                result.append({
                    "pod": p.metadata.name,
                    "container": cs.name,
                    "reason": reason,
                    "message": (detail or "")[:300],
                    "restarts": cs.restart_count,
                    "last_termination_reason": last.reason if last else None,
                    "last_exit_code": last.exit_code if last else None,
                })
    return {"namespace": namespace, "unhealthy": result}


def get_pod_events(namespace: str, pod: str) -> dict:
    """Get the most recent events for a pod.

    Args:
        namespace: Kubernetes namespace.
        pod: Pod name.
    """
    events = v1.list_namespaced_event(
        namespace, field_selector=f"involvedObject.name={pod}").items
    events.sort(key=lambda e: e.last_timestamp or e.event_time or e.metadata.creation_timestamp)
    return {"pod": pod,
            "events": [f"{e.type} {e.reason}: {e.message}"[:300] for e in events[-10:]]}


def get_pod_logs(namespace: str, pod: str, previous: bool = False) -> dict:
    """Get the last lines of a pod's logs. Use previous=True for a crashed container.

    Args:
        namespace: Kubernetes namespace.
        pod: Pod name.
        previous: If True, fetch logs from the previously terminated container.
    """
    try:
        logs = v1.read_namespaced_pod_log(
            pod, namespace, tail_lines=50, previous=previous)
        return {"pod": pod, "previous": previous, "logs": logs[-MAX_LOG_CHARS:]}
    except client.ApiException as e:
        return {"pod": pod, "error": f"{e.status}: {e.reason}"}


def describe_pod_resources(namespace: str, pod: str) -> dict:
    """Get image, resource requests/limits, and node for a pod.

    Args:
        namespace: Kubernetes namespace.
        pod: Pod name.
    """
    p = v1.read_namespaced_pod(pod, namespace)
    return {
        "node": p.spec.node_name,
        "containers": [{
            "name": c.name,
            "image": c.image,
            "limits": c.resources.limits,
            "requests": c.resources.requests,
        } for c in p.spec.containers],
    }