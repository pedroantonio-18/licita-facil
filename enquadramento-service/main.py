import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import enquadramento

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="LicitaFácil Enquadramento",
    description="Estimativa e enquadramento da despesa (dispensa ou pregão) e a Informação pronta para o SEI.",
    version="0.1.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(enquadramento.router)


@app.get("/")
async def root():
    return {"message": "Enquadramento está online e operacional!"}
