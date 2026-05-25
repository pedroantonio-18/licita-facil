from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import merger, compressor, to_excel


app = FastAPI(
    title="LcitaFácil PDF Service",
    description="Microserviço focado no processamento, extração e compressão de PDFs.",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(merger.router)
app.include_router(compressor.router)
app.include_router(to_excel.router)

@app.get("/")
async def root():
    return {"message": "PDF Service está online e operacional!"}