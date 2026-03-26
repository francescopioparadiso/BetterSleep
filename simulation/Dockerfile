FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY simulation/requirements.txt ./
RUN pip install -r requirements.txt

COPY simulation /app/simulation
COPY common /app/common
COPY device_connector /app/device_connector
COPY time_series /app/time_series

ENV PYTHONPATH=/app
WORKDIR /app/simulation

CMD ["python", "night_simulation.py"]