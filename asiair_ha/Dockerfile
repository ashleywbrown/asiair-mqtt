FROM python:3.12-slim

WORKDIR /app

# Install system dependencies required for opencv
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Define the entrypoint
ENTRYPOINT ["python", "astro_mqtt.py"]

# Default arguments
CMD ["--config", "default.cfg"]