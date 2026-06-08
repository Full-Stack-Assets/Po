FROM python:3.12-slim AS base

RUN groupadd -r po && useradd -r -g po -d /app po
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY orchestrator_agent/ orchestrator_agent/

RUN chown -R po:po /app
USER po

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/v2/health')"

CMD ["gunicorn", "orchestrator_agent.server:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--timeout", "120", \
     "--access-logfile", "-"]
