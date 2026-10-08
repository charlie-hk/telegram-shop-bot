FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 DB_PATH=/data/shop.db
WORKDIR /app
COPY shopbot ./shopbot
VOLUME /data
CMD ["python", "-m", "shopbot"]
