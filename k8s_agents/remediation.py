from .models import REMEDIATION_MODEL
from google.adk.agents import Agent
from .remediation_tools import propose_remediation

remediation_agent = Agent(
    name="remediation_agent",
    model=REMEDIATION_MODEL,
    description="Turns an RCA report into queued, human-approved fix proposals.",
    instruction="""You propose fixes based ONLY on this incident report:

{rca_report}

For each workload with a clear, fixable root cause, call propose_remediation once:
- ImagePullBackOff from a missing tag: action=set_image with a valid image.
- OOMKilled: action=set_memory_limit. If the report says how much memory the
  app needs, set the limit about 25% above it. If not, quadruple the current
  limit and say in the reason that the value is a guess.
- CPU saturation: do not guess; recommend investigation, queue nothing.
- Application errors such as a database failure: queue nothing, because the fix
  is in configuration or an external dependency.
Use the Deployment name (the pod name without its two hash suffixes).
You cannot execute anything. Finish with a short list of what you queued
(with proposal IDs) and what you deliberately did not queue and why.
Tell the user to review with: python approve.py list""",
    tools=[propose_remediation],
)
