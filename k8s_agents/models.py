import os

_DEFAULT = os.environ.get("AGENT_MODEL", "gemini-3.5-flash-lite")
TROUBLESHOOTER_MODEL = os.environ.get("TROUBLESHOOTER_MODEL", "gemini-3-flash-preview")
MONITORING_MODEL = os.environ.get("MONITORING_MODEL", "gemini-3.1-flash-lite")
SUMMARIZER_MODEL = os.environ.get("SUMMARIZER_MODEL", _DEFAULT)
REMEDIATION_MODEL = os.environ.get("REMEDIATION_MODEL", "gemini-3-flash-preview")
