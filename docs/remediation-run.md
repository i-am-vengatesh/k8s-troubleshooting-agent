# Remediation Run: OOM Fix, Before and After

How the remediation agent's proposals were reviewed, approved, and verified against a real fault (`oom-app`).

## Setup

- Pipeline: `parallel_gather` (troubleshooter + monitoring) -> `rca_summarizer` -> `remediation_agent`
- The remediation agent can only queue proposals (`propose_remediation`). It cannot change the cluster.
- A human reviews with `python approve.py list` and applies with `python approve.py approve <id>`.
- Scenario: `oom-app` runs `stress --vm 1 --vm-bytes 200M` with a 50Mi memory limit.

## Attempt 1: proposal without enough evidence

| Item | Value |
|---|---|
| Proposal | `set_memory_limit 100Mi` (id `03ecd0ec`) |
| Reason given | Pod was OOMKilled with a 50Mi memory limit |
| Why it was weak | The tool output did not include the container's command or args, so the agent could not see the app needs about 200M. It doubled the limit. |
| Outcome (verified) | Pod `oom-app-7dff9cddb9-f7w8j`: limit 100Mi, last termination `OOMKilled`, 2 restarts, `CrashLoopBackOff` |

The approval step meant this was found on a test workload, and the decision is in the audit log.

## Fix applied to the agent

1. `describe_pod_resources` now also returns each container's `command` and `args`.
2. The troubleshooter instruction now says to state how much memory the app tries to use when the command, args, or logs show it.
3. The remediation instruction now sizes OOM fixes from that evidence (about 25% above the stated need). If the need is unknown, it quadruples the limit and says the value is a guess.

## Attempt 2: proposal from evidence

| Item | Value |
|---|---|
| Proposal | `set_memory_limit 250Mi` (id `fd1b9050`) |
| Reason given | OOMKilled because the 50Mi limit is too low for the 200MB the application requires |
| Approval | Reviewed, then `python approve.py approve fd1b9050` and typed `yes` |

### Verification

| Check | Result |
|---|---|
| Pod | `oom-app-57b5fc8959-5qqr7`, `1/1 Running`, 0 restarts (observed at about 32s of age) |
| Limit | 250Mi |
| Last termination | none |
| `kubectl top` | 235m CPU, 200Mi memory (about 80% of the limit) |

Re-checked after 18 minutes: same pod, 1/1 Running, 0 restarts.

## Other proposals in the same run

| Workload | Proposal | Note |
|---|---|---|
| `imagepull-app` | `set_image nginx:stable` (id `8483ff1a`) | Reason cites the missing tag `nginx:this-tag-does-not-exist` |
| `crashloop-app` | none queued | Cause is an application/dependency error, not a safe automatic fix |
| `cpu-hog-app` | none queued | CPU saturation needs investigation, not a guess |

An earlier, separate run queued `nginx:latest` for `imagepull-app` (id `4c72867c`). After approval, the new pod reached `1/1 Running`.

## Safety checks verified

- Re-approving an applied proposal is refused: `no pending proposal with that id`.
- A proposal outside the allowlist is rejected and never queued: `namespace 'kube-system' is not allowed`.
- Values are validated when queued and again at approval.
- Every decision is appended to `remediation/audit.jsonl`.

## Lessons

- A plausible fix is not necessarily a working one. The first OOM proposal looked reasonable and still failed.
- The agent can only size a fix from evidence it can see. Exposing container args to the tools fixed the sizing.
- Human approval is what turned a wrong proposal into a harmless experiment.
- Approval prompts read from the terminal input buffer. Run `approve.py` as a single command on its own line, because extra pasted lines can be consumed as the answer and cancel the approval.

## Limitations

- One run per scenario, reviewed by hand.
- The 250Mi result is a snapshot soon after the approval. Re-check after 18 minutes before calling it permanent.
- Free-tier model quotas (for example 20 requests per day per model) limit how often a full investigation can run.
