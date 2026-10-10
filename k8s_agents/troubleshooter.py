from google.adk.agents import Agent
from .k8s_tools import (list_unhealthy_pods, get_pod_events,
                        get_pod_logs, describe_pod_resources)

k8s_troubleshooter = Agent(
    name="k8s_troubleshooter",
    model="gemini-3.8-flash",
    description="Diagnoses crashing, failing, or unschedulable pods using status, events, logs, and resource specs.",
    instruction="""You are a Kubernetes SRE. Investigate step by step:
1. Call list_unhealthy_pods for the namespace.
2. For each unhealthy pod, call get_pod_events.
3. For crashing pods, call get_pod_logs with previous=True.
4. For OOMKilled or scheduling issues, call describe_pod_resources.
Report per pod: root cause, evidence from tool output, and a suggested fix.
Never claim something the tool output does not show. You are read-only:
suggest kubectl commands but never claim to have run them.""",
    tools=[list_unhealthy_pods, get_pod_events,
           get_pod_logs, describe_pod_resources],
    output_key="troubleshooter_findings",
)