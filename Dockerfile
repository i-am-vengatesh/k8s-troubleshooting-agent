FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY k8s_agents ./k8s_agents
COPY webhook.py .
RUN useradd -m app && chown -R app /app
USER app
EXPOSE 8080
CMD ["uvicorn", "webhook:app", "--host", "0.0.0.0", "--port", "8080"]
