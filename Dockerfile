FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY aviationstack-mcp ./aviationstack-mcp

RUN pip install --no-cache-dir ./aviationstack-mcp

COPY . .

EXPOSE 8501

CMD ["sh", "-c", "streamlit run frontend1.py --server.address=0.0.0.0 --server.port=${PORT:-8501}"]