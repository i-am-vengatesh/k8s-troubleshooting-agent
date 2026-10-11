# Alert-Triggered Investigation (in-cluster, simulated alert)

An alert-shaped payload was sent to the agent running as a pod in the kind cluster. The pod ran the full multi-agent pipeline in the background and produced a report and fix proposals.

## Setup

- Agent running in-cluster as `k8s-agent` under the read-only `agent-reader` ServiceAccount
- Token-protected webhook (`X-Webhook-Token`), reached through `kubectl port-forward`
- **Simulated** Alertmanager-style payload (Alertmanager is not installed)
- Slack not configured, so the report prints to the pod logs (`[slack disabled]`)
- Scenario state: `crashloop-app`, `imagepull-app` and `oom-app` failing, `cpu-hog-app` running at its CPU limit

## Request

```bash
curl -X POST localhost:8080/alert \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: $TOKEN" \
  -d '{"alerts":[{"status":"firing","fingerprint":"t2",
       "labels":{"alertname":"PodCrashLooping","namespace":"agent-test"},
       "annotations":{"summary":"pods restarting"}}]}'
```

Response: `{"investigations_started":1}` (returned immediately; the investigation runs in the background).

## Report produced by the pod (verbatim, from `kubectl logs`)

```markdown
:mag: *Alert:* PodCrashLooping - pods restarting

### Summary
An investigation of the `agent-test` namespace reveals three unhealthy pods experiencing crash loops or image pull failures, alongside a separate CPU resource saturation issue. Each pod failure stems from a distinct root cause ranging from a simulated database error and an invalid image tag to an out-of-memory termination.

### Per Workload Analysis

#### 1. Pod: `crashloop-app-59475ffc6-bcmc8`
* **Status**: `CrashLoopBackOff` (last exit code: `1`, restarts: `118`)
* **Root Cause**: Application failure (simulated database connection error).
* **Evidence**:
  * Logs show: `ERROR: Database connection failed` and `Application exiting...`.
  * The pod runs a shell script command executing: `echo "ERROR: Database connection failed"; exit 1`.
* **Suggested Fix**: Check the application configuration or the health of the database it depends on. Ensure the entrypoint script is correctly configured.

#### 2. Pod: `imagepull-app-5bf78878bc-ss66w`
* **Status**: `ImagePullBackOff`
* **Root Cause**: Invalid container image tag.
* **Evidence**:
  * The pod is configured to use image `nginx:this-tag-does-not-exist`, which cannot be found in the registry.
* **Suggested Fix**: Update the deployment to use a valid image tag.
  kubectl set image deployment/imagepull-app app=nginx:latest -n agent-test

#### 3. Pod: `oom-app-968bf669-wnxcs`
* **Status**: `CrashLoopBackOff` (last termination reason: `OOMKilled`, exit code: `137`, restarts: `4`)
* **Root Cause**: Out Of Memory (OOM). The application attempted to use more memory than its resource limit allowed.
* **Evidence**:
  * The container has a memory limit of **50Mi**.
  * The arguments `stress --vm 1 --vm-bytes 200M` explicitly attempt to allocate **200MB** of memory.
  * Logs show: `stress: info: [1] dispatching hogs: ... 1 vm ...`
* **Suggested Fix**: Increase the memory limit to at least **200Mi** (plus buffer) or adjust the application's memory usage.

### Resource Saturation Issues (Non-Crashes)
* **Pod**: `cpu-hog-app-759c7665d7-pnml9` (Container: `app`)
  * **Issue**: Utilizing **100%** of its CPU limit (199 millicores out of a 200 millicores limit).
  * **Impact**: Extreme CPU throttling or resource starvation, identified as the likely cause of the `PodCrashLooping` alert.

*Fix proposals:*
* Proposal ID: 51dddfef (`imagepull-app`): use `nginx:latest`
* Proposal ID: fa3e3613 (`oom-app`): increase the memory limit to `256Mi`

Deliberately skipped:
* `crashloop-app`: application-level or configuration issue, not fixable by restart or scaling
* `cpu-hog-app`: hitting its CPU limit; needs investigation, no limit change proposed
```

## Proposals queued inside the pod (`/tmp/remediation/pending.json`)

| ID | Deployment | Action | Value | Reason recorded |
|---|---|---|---|---|
| `51dddfef` | `imagepull-app` | `set_image` | `nginx:latest` | Current tag is invalid, causing ImagePullBackOff |
| `fa3e3613` | `oom-app` | `set_memory_limit` | `256Mi` | OOMKilled after attempting to allocate 200Mi with a 50Mi limit |

Nothing was applied. Both proposals are `pending`.

## What this verifies

- Alert payload -> background investigation -> report -> queued proposals works inside the cluster, using the read-only ServiceAccount.
- The remediation agent queued only the two clear cases and declined the application error and the CPU saturation case, with reasons.
- The OOM proposal (256Mi) was sized from the app's `--vm-bytes 200M` argument.

## Problems observed in this run

- **Unsupported claim in the report.** It says CPU saturation was "identified as the likely cause of the `PodCrashLooping` alert". Nothing in the findings supports that link, and CPU throttling does not make a pod crash-loop. The alert text was passed to the agents as part of the prompt, and the summarizer (a lite model) drew a causal link on its own. Mitigation: tell the summarizer not to infer causal links the findings do not state.
- **Minor unit slip.** The OOM proposal's reason says "200Mi", while the app allocates 200M (about 191Mi). The 256Mi limit is still sensible.
- **Misleading hand-off line.** The remediation agent tells the user to run `python approve.py list`, but in-cluster proposals live in the pod and `approve.py` on a laptop cannot see them.

## Limitations

- One run, with a simulated alert and a single manual review.
- Slack reporting was not tested (the report printed to the pod logs).
- The queue lives in the pod's filesystem, so proposals are lost if the pod restarts, and they cannot be approved from outside the pod yet.
- A full run uses many model requests, which are tightly limited on a free tier.
