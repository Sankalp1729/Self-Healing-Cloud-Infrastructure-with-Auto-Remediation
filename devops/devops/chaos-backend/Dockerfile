FROM python:3.11-slim

WORKDIR /app

# Install dependencies
# We use --no-cache-dir to keep the image small
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app ./app

# Expose port 8000
EXPOSE 8000

# Use array syntax for CMD to ensure signals are passed correctly to the process
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
