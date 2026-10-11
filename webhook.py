"""Alertmanager webhook -> ADK investigation -> Slack.

Run locally:  uvicorn webhook:app --port 8080
"""
import asyncio
import json
import os
import time
import urllib.request

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from k8s_agents.agent import root_agent

APP_NAME = "k8s_agents"
SLACK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
TOKEN = os.environ.get("WEBHOOK_TOKEN", "")
COOLDOWN_SECONDS = int(os.environ.get("ALERT_COOLDOWN_SECONDS", "900"))

app = FastAPI()
sessions = InMemorySessionService()
runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=sessions)
_lock = asyncio.Lock()          # one investigation at a time (protects API quota)
_last_seen: dict[str, float] = {}  # alert fingerprint -> last investigation time


def post_slack(text: str) -> None:
    if not SLACK_URL:
        print("[slack disabled]\n" + text)
        return
    req = urllib.request.Request(
        SLACK_URL, data=json.dumps({"text": text[:3500]}).encode(),
        headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)


async def investigate(namespace: str, alert_summary: str) -> None:
    prompt = (f"An alert fired: {alert_summary}\n"
              f"Investigate what is wrong in the {namespace} namespace.")
    async with _lock:
        session = await sessions.create_session(app_name=APP_NAME, user_id="alertmanager")
        msg = types.Content(role="user", parts=[types.Part(text=prompt)])
        texts: dict[str, str] = {}
        try:
            async for ev in runner.run_async(user_id="alertmanager",
                                             session_id=session.id, new_message=msg):
                if ev.is_final_response() and ev.content and ev.content.parts:
                    texts[ev.author] = ev.content.parts[0].text or ""
        except Exception as e:
            post_slack(f":warning: Investigation failed: {e}")
            return
    report = texts.get("rca_summarizer", "(no report produced)")
    fixes = texts.get("remediation_agent", "")
    post_slack(f":mag: *Alert:* {alert_summary}\n\n{report}\n\n*Fix proposals:*\n{fixes}")


@app.post("/alert")
async def alert(request: Request, background: BackgroundTasks,
                x_webhook_token: str = Header(default="")):
    if TOKEN and x_webhook_token != TOKEN:
        raise HTTPException(status_code=401, detail="bad token")
    payload = await request.json()
    started = 0
    for a in payload.get("alerts", []):
        if a.get("status") != "firing":
            continue
        fp = a.get("fingerprint") or json.dumps(a.get("labels", {}), sort_keys=True)
        if time.time() - _last_seen.get(fp, 0) < COOLDOWN_SECONDS:
            continue  # same alert investigated recently
        _last_seen[fp] = time.time()
        labels, ann = a.get("labels", {}), a.get("annotations", {})
        summary = f"{labels.get('alertname', 'unknown')} - {ann.get('summary', '')}".strip(" -")
        ns = labels.get("namespace", "agent-test")
        background.add_task(investigate, ns, summary)
        started += 1
    return {"investigations_started": started}


@app.get("/healthz")
def healthz():
    return {"ok": True}
