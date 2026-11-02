FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./agent/

# DB disimpan di volume agar tidak hilang saat container restart
VOLUME ["/app/agent/data"]

CMD ["python", "-m", "agent.agent"]
