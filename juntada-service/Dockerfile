FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV JUNTADA_DIR=/app/data/sessoes
# Produção sem internet: consulta automática ao TCU desligada (fase 2, depende da TI)
ENV JUNTADA_CONSULTA_TCU=0

COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . /app/

VOLUME ["/app/data"]

EXPOSE 8002

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
