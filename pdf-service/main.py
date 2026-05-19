from fastapi import FastAPI
from routers import merger

app = FastAPI(
    title="LcitaFácil PDF Service",
    description="Microserviço focado no processamento, extração e compressão de PDFs.",
    version="0.1.0"
)

app.include_router(merger.router)

@app.get("/")
async def root():
    return {"message": "PDF Service está online e operacional!"}