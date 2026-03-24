FROM python:3.13-slim

WORKDIR /service

# Install required packages
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first and install dependencies
COPY simulation/requirements.txt /service/requirements.txt
RUN pip install --no-cache-dir -r /service/requirements.txt

# Copy the project structure
COPY simulation /service
COPY common /service/common
COPY device_connector /service/device_connector
COPY time_series /service/time_series

# Run the simulation
CMD ["python", "night_simulation.py"]
