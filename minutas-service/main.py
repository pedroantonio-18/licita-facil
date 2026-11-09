import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import minutas

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="LicitaFácil Minutas",
    description="Aviso de dispensa e edital de pregão a partir dos modelos da AGU, prontos para o SEI.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(minutas.router)


@app.get("/")
async def root():
    return {"message": "Minutas está online e operacional!"}
