from kubernetes import client, config

try:
    config.load_incluster_config()
except config.ConfigException:
    config.load_kube_config()

core = client.CoreV1Api()
custom = client.CustomObjectsApi()


def _cpu_millicores(q: str) -> float:
    if q.endswith("n"):
        return float(q[:-1]) / 1_000_000
    if q.endswith("u"):
        return float(q[:-1]) / 1_000
    if q.endswith("m"):
        return float(q[:-1])
    return float(q) * 1000


def _mem_mib(q: str) -> float:
    units = {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024}
    for suffix, factor in units.items():
        if q.endswith(suffix):
            return float(q[:-2]) * factor
    return float(q) / (1024 * 1024)  # plain bytes


def get_node_usage() -> dict:
    """Get current CPU and memory usage for each node (from metrics-server)."""
    try:
        data = custom.list_cluster_custom_object("metrics.k8s.io", "v1beta1", "nodes")
        return {"nodes": [{
            "node": n["metadata"]["name"],
            "cpu_millicores": round(_cpu_millicores(n["usage"]["cpu"])),
            "memory_mib": round(_mem_mib(n["usage"]["memory"])),
        } for n in data["items"]]}
    except client.ApiException as e:
        return {"error": f"{e.status}: {e.reason}. Is metrics-server installed?"}


def get_pod_usage(namespace: str) -> dict:
    """Get current CPU/memory usage per container compared with its limits.

    Args:
        namespace: Kubernetes namespace to inspect.
    """
    try:
        metrics = custom.list_namespaced_custom_object(
            "metrics.k8s.io", "v1beta1", namespace, "pods")
    except client.ApiException as e:
        return {"error": f"{e.status}: {e.reason}. Is metrics-server installed?"}

    limits = {}
    for p in core.list_namespaced_pod(namespace).items:
        for c in p.spec.containers:
            lim = (c.resources.limits or {})
            limits[(p.metadata.name, c.name)] = lim

    out = []
    for item in metrics["items"]:
        for c in item["containers"]:
            cpu = _cpu_millicores(c["usage"]["cpu"])
            mem = _mem_mib(c["usage"]["memory"])
            lim = limits.get((item["metadata"]["name"], c["name"]), {})
            row = {"pod": item["metadata"]["name"], "container": c["name"],
                   "cpu_millicores": round(cpu), "memory_mib": round(mem)}
            if "cpu" in lim:
                row["cpu_limit_millicores"] = round(_cpu_millicores(lim["cpu"]))
                row["cpu_pct_of_limit"] = round(100 * cpu / _cpu_millicores(lim["cpu"]))
            if "memory" in lim:
                row["memory_limit_mib"] = round(_mem_mib(lim["memory"]))
                row["memory_pct_of_limit"] = round(100 * mem / _mem_mib(lim["memory"]))
            out.append(row)
    return {"namespace": namespace, "usage": out}