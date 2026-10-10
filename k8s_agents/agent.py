from google.adk.agents import Agent, ParallelAgent, SequentialAgent
from .troubleshooter import k8s_troubleshooter
from .monitoring import monitoring_agent

parallel_gather = ParallelAgent(
    name="parallel_gather",
    description="Runs the troubleshooter and monitoring agents at the same time.",
    sub_agents=[k8s_troubleshooter, monitoring_agent],
)

rca_summarizer = Agent(
    name="rca_summarizer",
    model="gemini-3.8-flash",
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
Do not add facts that are not in the findings. If the two sources disagree,
say so. Suggest kubectl commands but never claim to have run them.""",
)

root_agent = SequentialAgent(
    name="incident_investigator",
    description="Investigates a namespace with parallel specialists, then summarizes.",
    sub_agents=[parallel_gather, rca_summarizer],
)