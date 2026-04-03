FROM python:3.13-slim

WORKDIR /app

COPY simulation/requirements.txt ./
RUN pip install -r requirements.txt

COPY simulation /app/simulation
COPY common /app/common
COPY device_connector /app/device_connector

ENV PYTHONPATH=/app
WORKDIR /app/simulation

CMD ["python", "night_simulation.py"]