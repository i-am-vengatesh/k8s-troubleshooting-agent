from google.adk.agents import Agent
from .monitoring_tools import get_node_usage, get_pod_usage

monitoring_agent = Agent(
    name="monitoring_agent",
    model="gemini-3.8-flash",
    description="Analyzes CPU and memory usage of nodes and pods to find saturation, throttling risk, and resource pressure.",
    instruction="""You are a monitoring specialist for Kubernetes.
Call get_node_usage and get_pod_usage for the namespace.
Flag anything at or above 80% of its CPU or memory limit, and any node under pressure.
Report numbers from the tool output only. If a tool returns an error, say so
instead of guessing. You are read-only.""",
    tools=[get_node_usage, get_pod_usage],
    output_key="monitoring_findings",
)