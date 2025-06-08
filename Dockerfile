# Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY . /app

RUN pip install .

# Default command can be overridden in compose
CMD ["python"]