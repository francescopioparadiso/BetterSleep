FROM python:3.13-slim

WORKDIR /app

# Install required packages
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy the entire project structure
COPY . /app

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Set working directory to Simulation
WORKDIR /app/testing

# Run the test cycle
CMD ["python", "test_cycle.py"]

