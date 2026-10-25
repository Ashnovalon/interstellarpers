FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 curl && rm -rf /var/lib/apt/lists/*
COPY real_records/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY real_records/constraints.txt /app/constraints.txt
RUN pip install --no-cache-dir -r constraints.txt
COPY real_records /app/real_records
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
CMD ["uvicorn", "real_records.api:app", "--host", "0.0.0.0", "--port", "8000"]
