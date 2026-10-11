from .models import SUMMARIZER_MODEL
from google.adk.agents import Agent, ParallelAgent, SequentialAgent
from .troubleshooter import k8s_troubleshooter
from .monitoring import monitoring_agent
from .remediation import remediation_agent

parallel_gather = ParallelAgent(
    name="parallel_gather",
    description="Runs the troubleshooter and monitoring agents at the same time.",
    sub_agents=[k8s_troubleshooter, monitoring_agent],
)

rca_summarizer = Agent(
    name="rca_summarizer",
    model=SUMMARIZER_MODEL,
    description="Combines specialist findings into one root-cause report.",
    instruction="""You write the incident report. Use only the findings below.

Troubleshooter findings:
{troubleshooter_findings}

Monitoring findings:
{monitoring_findings}

Produce:
1. Summary (2-3 sentences)
2. Per workload: status, root cause, evidence, suggested fix
3. Resource saturation issues that are not crashes
Do not add facts or causal links that are not in the findings (for example, do not blame an alert on a workload unless the findings say so). If the two sources disagree,
say so. Suggest kubectl commands but never claim to have run them.""",
    output_key="rca_report",
)

root_agent = SequentialAgent(
    name="incident_investigator",
    description="Investigates a namespace, summarizes, then queues fix proposals.",
    sub_agents=[parallel_gather, rca_summarizer, remediation_agent],
)
