FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Limites da dispensa por exercício: opcional, arquivo JSON montado no container quando sair
# o decreto do ano (formato em app/regras.py, LIMITES_PADRAO)
# ENV ENQUADRAMENTO_LIMITES=/app/config/limites.json

COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . /app/

# PCAs carregados pela tela (um JSON por exercício)
ENV ENQUADRAMENTO_DADOS=/app/data
VOLUME ["/app/data"]

EXPOSE 8004

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]
