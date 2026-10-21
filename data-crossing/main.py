import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import conluio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="LicitaFácil Data Crossing",
    description="Microserviço de análise documental e cruzamento de dados de processos licitatórios.",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Relatorio-SHA256"],
)

app.include_router(conluio.router)

@app.get("/")
async def root():
    return {"message": "Data Crossing Service está online e operacional!"}
