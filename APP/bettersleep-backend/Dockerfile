# Use an official, lightweight Python image
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file first (to leverage Docker caching)
COPY requirements.txt .

# Install dependencies directly into the container
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# We don't set a CMD here because docker-compose will dictate 
# whether this container runs the simulator or the subscriber.