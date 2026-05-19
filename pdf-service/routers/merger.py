from fastapi import APIRouter, UploadFile, File, HTTPException, status
from fastapi.responses import StreamingResponse
from pypdf import PdfMerger
import io

router = APIRouter(
    prefix="/merger",
    tags=["PDF Merger"]
)

@router.post("/merge")
async def merge_pdfs(files: list[UploadFile] = File(...)):
    if len(files) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Você precisa enviar pelo menos 2 arquivos PDF para mesclar."
        )

    merger = PdfMerger()

    try:
        for file in files:
            if file.content_type != "application/pdf":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"O arquivo {file.filename} não é um PDF válido."
                )
            
            pdf_bytes = await file.read()
            merger.append(io.BytesIO(pdf_bytes))

        output_buffer = io.BytesIO()
        merger.write(output_buffer)
        output_buffer.seek(0)
        merger.close()

        return StreamingResponse(
            output_buffer,
            media_type="application/pdf",
            headers={
                "Content-Disposition": "attachment; filename=merged.pdf"
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao mesclar PDFs: {str(e)}"
        )
