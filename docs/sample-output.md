# Sample Output: K8s Troubleshooting Agent

**Prompt:** `What's wrong in the agent-test namespace?`
**Agent:** `k8s_troubleshooter` (Google ADK, model `gemini-3.8-flash`)
**Cluster:** kind (single node) on WSL2
**Date:** 10 Oct 2026

## Tool-call trajectory

The agent followed the order defined in its instruction:

1. `list_unhealthy_pods("agent-test")`
2. In parallel: `get_pod_events` (x3), `get_pod_logs` (x2), `describe_pod_resources`
3. Final answer

![ADK events trace](images/adk-events-trace.png)

## Final answer (verbatim from the agent)

In the `agent-test` namespace, three pods are currently unhealthy:

### 1. `crashloop-app-59475ffc6-bcmc8`

- **Status:** `CrashLoopBackOff` (Exit Code: 1, Reason: `Error`)
- **Root Cause:** The application crashes during startup because it cannot connect to the database.
- **Evidence:**
  - Pod Logs (`previous=True`):

    ```none
    Application starting...
    ERROR: Database connection failed
    Application exiting...
    ```

  - Events: Repeated `Normal Started` followed by `Warning BackOff: Back-off restarting failed container app`.
- **Suggested Fix:**
  - Check the application's configuration, environment variables, or ConfigMaps/Secrets for database connection settings (e.g., host, port, credentials).
  - Verify whether the target database is running and reachable from within the cluster.
  - To inspect or update configuration:

    ```bash
    kubectl describe pod crashloop-app-59475ffc6-bcmc8 -n agent-test
    kubectl edit deployment crashloop-app -n agent-test
    ```

### 2. `imagepull-app-5bf78878bc-7zkpw`

- **Status:** `ImagePullBackOff` / `ErrImagePull`
- **Root Cause:** The configured container image tag does not exist in the container registry.
- **Evidence:**
  - Events:

    ```none
    Warning Failed: Failed to pull image "nginx:this-tag-does-not-exist": rpc error: code = NotFound desc = failed to pull and unpack image "docker.io/library/nginx:this-tag-does-not-exist": failed to resolve reference "docker.io/library/nginx:this-tag-does-not-exist"
    Warning Failed: Error: ImagePullBackOff
    Normal BackOff: Back-off pulling image "nginx:this-tag-does-not-exist"
    ```

- **Suggested Fix:**
  - Update the pod's container image specification to reference a valid image and tag (e.g., `nginx:alpine` or `nginx:latest`):

    ```bash
    kubectl set image deployment/imagepull-app app=nginx:latest -n agent-test
    ```

### 3. `oom-app-968bf669-w6tn4`

- **Status:** `CrashLoopBackOff` / `OOMKilled` (Exit Code: 137, Reason: `OOMKilled`)
- **Root Cause:** The container exceeded its configured memory limit of `50Mi` and was terminated by the Linux OOM killer.
- **Evidence:**
  - Termination Reason: `OOMKilled` with exit code `137`.
  - Pod Resources: Container `app` has memory limits and requests set to `50Mi`:

    ```yaml
    limits:
      memory: 50Mi
    requests:
      memory: 50Mi
    ```

  - Pod Logs (`previous=True`): The container runs `polinux/stress` dispatching memory hogs:

    ```none
    stress: info: [1] dispatching hogs: 0 cpu, 0 io, 1 vm, 0 hdd
    ```

- **Suggested Fix:**
  - Increase the container's memory limit to accommodate the workload's memory requirements, or adjust the workload to stay within resource limits:

    ```bash
    kubectl set resources deployment/oom-app -n agent-test --limits=memory=256Mi --requests=memory=128Mi
    ```

## Evaluation

| Scenario | Expected root cause | Diagnosed correctly |
|---|---|---|
| `crashloop-app` | App exits with error at startup (from previous-container logs) | Yes |
| `imagepull-app` | Image tag `nginx:this-tag-does-not-exist` not found | Yes |
| `oom-app` | `OOMKilled`, exit 137, 50Mi limit | Yes |

**Result: 3 of 3 scenarios diagnosed correctly** (single run, manual review).

## Reviewer notes

- The crashloop root cause ("cannot connect to the database") comes from the **log text** of the test app. The agent reported it faithfully, but in real incidents logs can be misleading and should be cross-checked with config and dependencies.
- The OOM suggestion raises the limit to 256Mi. A good follow-up question is whether the workload *should* need that much memory.
- The agent only suggested `kubectl` commands. It did not run any, as its tools are read-only.
