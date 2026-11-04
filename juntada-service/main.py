import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import juntada

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="LicitaFácil Juntada de Documentos",
    description="Conferência e organização das certidões de habilitação para juntada no SEI.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(juntada.router)


@app.get("/")
async def root():
    return {"message": "Juntada de Documentos está online e operacional!"}
