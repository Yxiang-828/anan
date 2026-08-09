FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY core/ core/
COPY adapter/ adapter/
COPY web/ web/
COPY server.py .
COPY config.default.json .
ENV PYTHONUNBUFFERED=1
CMD ["python", "server.py"]
