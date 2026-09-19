FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py fleet.py sources.py ./

ENV PORT=8080
EXPOSE 8080
RUN useradd --create-home fleet
USER fleet

# TIGER_DATABASE_URL: read from the database. Unset, or FLEET_FAKE=1: generated data for 3 machines.
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
