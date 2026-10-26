FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all services
COPY services/ ./services/

# Copy pytest configuration
COPY pytest.ini ./

# Expose all ports (will be overridden in docker-compose)
EXPOSE 8050 8060 8070 8080

# Default command (will be overridden in docker-compose)
CMD ["uvicorn", "services.gateway_service.main:app", "--host", "0.0.0.0", "--port", "8080"]

