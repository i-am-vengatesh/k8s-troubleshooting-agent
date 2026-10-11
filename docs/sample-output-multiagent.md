# Sample Output: Multi-Agent Incident Investigation

**Prompt:** `What's wrong in the agent-test namespace?`
**Root agent:** `incident_investigator` (SequentialAgent)
**Flow:** `parallel_gather` (troubleshooter + monitoring) -> `rca_summarizer`
**Cluster:** kind (single node) on WSL2, with metrics-server installed

![ADK multi-agent trace](images/adk-multiagent-trace.png)

## Monitoring agent findings

- **Pod:** `cpu-hog-app-799d4dcc64-wcvp4`, container `app`
- **CPU:** 200m / 200m limit (100% of limit). Flagged as saturated, with throttling risk.
- **Memory:** 0 MiB / 128 MiB limit (0% of limit)
- **Node `kind-control-plane`:** 422m CPU, 801 MiB memory, no node pressure reported

## Final report from the RCA summarizer

### 1. Summary

The agent-test namespace is currently experiencing failures across three workloads due to an unreachable database, an invalid image tag, and memory limits being exceeded. Additionally, one running workload is experiencing 100% CPU utilization, putting it at risk of CPU throttling. The two data sources (troubleshooter and monitoring) are consistent and report no cluster-level node resource pressure.

### 2. Workload findings

**`crashloop-app-59475ffc6-bcmc8`**

- **Status:** CrashLoopBackOff (16 restarts, last exit code 1, termination reason Error)
- **Root cause:** Application startup failure caused by an unreachable or misconfigured database. The application logs an error and exits with code 1.
- **Evidence:**
  - Warning event: `Back-off restarting failed container app`
  - Previous container logs:

    ```none
    Application starting...
    ERROR: Database connection failed
    Application exiting...
    ```

- **Suggested fix:** Verify the database connection string, credentials, and network reachability by checking the relevant ConfigMap, Secret, and NetworkPolicy resources. Inspect the deployment environment variables:

  ```bash
  kubectl describe pod crashloop-app-59475ffc6-bcmc8 -n agent-test
  ```

**`imagepull-app-5bf78878bc-7zkpw`**

- **Status:** ImagePullBackOff (0 restarts)
- **Root cause:** The container image cannot be pulled because the specified image tag does not exist.
- **Evidence:** Pod message `Back-off pulling image "nginx:this-tag-does-not-exist"`, plus `Failed` and `BackOff` events.
- **Suggested fix:**

  ```bash
  kubectl set image deployment/imagepull-app app=nginx:latest -n agent-test
  ```

**`oom-app-968bf669-w6tn4`**

- **Status:** CrashLoopBackOff (16 restarts, last exit code 137, termination reason OOMKilled)
- **Root cause:** Out of memory. The container exceeded its configured memory limit of 50Mi.
- **Evidence:** `limits.memory: 50Mi`, `requests.memory: 50Mi`, termination reason `OOMKilled` with exit code 137, and previous logs showing `polinux/stress` dispatching memory hogs.
- **Suggested fix:**

  ```bash
  kubectl set resources deployment/oom-app -n agent-test --limits=memory=256Mi --requests=memory=128Mi
  ```

### 3. Resource saturation issues (non-crashing)

- **Pod:** `cpu-hog-app-799d4dcc64-wcvp4`, container `app`
- **Issue:** CPU saturation and throttling risk
- **Metrics:** 200m / 200m limit (100% of limit), at or above the 80% flag threshold. Memory 0 MiB / 128 MiB (0%).

## Evaluation

| Scenario | Expected root cause | Diagnosed correctly |
|---|---|---|
| `crashloop-app` | Startup error from previous-container logs | Yes |
| `imagepull-app` | Image tag not found | Yes |
| `oom-app` | OOMKilled against the 50Mi limit | Yes |
| `cpu-hog-app` | CPU at its limit (saturation) | Yes |

**4 of 4 scenarios diagnosed correctly** (single run, manual review).

## Reviewer notes

- `cpu-hog-app` looks healthy (Running, 0 restarts), so only the monitoring agent can catch it.
- This run predates the remediation agent. See [remediation-run.md](remediation-run.md) for fix proposals and verification.
- The OOM suggestion in this older run was a generic value. The later run sized it from the app's actual memory demand (250Mi).
- The crashloop root cause comes from the test app's log text. In real incidents, logs can mislead and need cross-checking.
