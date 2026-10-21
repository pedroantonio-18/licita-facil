FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Servidor de produção: 4 CPUs, sem GPU
ENV LLM_THREADS=4
ENV DATA_CROSSING_DB=/app/data/licita_facil.db

# libgl1/libglib2.0-0: dependências do OpenCV usado pelo docTR
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libgl1 \
       libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/

# Índice de PyTorch só para CPU: o servidor não tem GPU, e o pacote padrão
# para x86 traz vários GB de bibliotecas CUDA.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
       --extra-index-url https://download.pytorch.org/whl/cpu

# O servidor de produção não tem internet: os pesos do docTR são baixados
# aqui, no build, e ficam no cache da imagem (~/.cache/doctr).
RUN python -c "from doctr.models import ocr_predictor; ocr_predictor(pretrained=True)"

COPY . /app/

VOLUME ["/app/data"]

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
