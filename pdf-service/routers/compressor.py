from fastapi import APIRouter, UploadFile, File, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pypdf import PdfReader, PdfWriter
from PIL import Image
from enum import Enum
import subprocess
import tempfile
import io
import os
import logging

logger = logging.getLogger("pdf_service.compressor")

router = APIRouter(
    prefix="/compressor",
    tags=["PDF Compressor"]
)


class CompressionLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"

def _compress_pillow_helper(pdf_bytes: bytes, image_quality: int, max_dimension: int) -> io.BytesIO:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    for page in writer.pages:
        page.compress_content_streams()
        if "/Resources" not in page or "/XObject" not in page["/Resources"]:
            continue

        x_objects = page["/Resources"]["/XObject"].get_object()

        for obj_name in x_objects:
            x_obj = x_objects[obj_name].get_object()

            if x_obj.get("/Subtype") != "/Image":
                continue

            try:
                width = int(x_obj["/Width"])
                height = int(x_obj["/Height"])
                color_space = x_obj.get("/ColorSpace", "/DeviceRGB")

                if color_space == "/DeviceGray":
                    mode = "L"
                else:
                    mode = "RGB"

                data = x_obj.get_data()

                try:
                    img = Image.frombytes(mode, (width, height), data)
                except Exception:
                    try:
                        img = Image.open(io.BytesIO(data))
                        img = img.convert(mode)
                    except Exception:
                        continue

                if width > max_dimension or height > max_dimension:
                    ratio = min(max_dimension / width, max_dimension / height)
                    new_size = (int(width * ratio), int(height * ratio))
                    img = img.resize(new_size, Image.LANCZOS)

                img_buf = io.BytesIO()
                img.save(img_buf, format="JPEG", quality=image_quality, optimize=True)
                img_buf.seek(0)

                x_obj._data = img_buf.read()
                x_obj["/Filter"] = "/DCTDecode"
                x_obj["/Width"] = img.width
                x_obj["/Height"] = img.height
                x_obj["/ColorSpace"] = "/DeviceGray" if mode == "L" else "/DeviceRGB"
                x_obj["/BitsPerComponent"] = 8

            except Exception as img_err:
                logger.warning(f"Falha ao recomprimir imagem {obj_name}: {img_err}")
                continue

    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    writer.close()
    return buf

def _compress_low(pdf_bytes: bytes) -> io.BytesIO:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    for page in writer.pages:
        page.compress_content_streams()

    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    writer.close()
    return buf


def _compress_medium(pdf_bytes: bytes) -> io.BytesIO:
    return _compress_pillow_helper(pdf_bytes, image_quality=45, max_dimension=1200)


def _compress_high(pdf_bytes: bytes) -> io.BytesIO:
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = os.path.join(tmp_dir, "input.pdf")
            output_path = os.path.join(tmp_dir, "output.pdf")

            with open(input_path, "wb") as f:
                f.write(pdf_bytes)

            gs_command = [
                "gs",
                "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.4",
                "-dPDFSETTINGS=/screen",
                "-dNOPAUSE",
                "-dQUIET",
                "-dBATCH",
                "-dAutoRotatePages=/None",
                "-dColorImageDownsampleType=/Bicubic",
                "-dColorImageResolution=72",
                "-dGrayImageDownsampleType=/Bicubic",
                "-dGrayImageResolution=72",
                "-dMonoImageDownsampleType=/Bicubic",
                "-dMonoImageResolution=72",
                f"-sOutputFile={output_path}",
                input_path,
            ]

            result = subprocess.run(
                gs_command,
                capture_output=True,
                timeout=120,
            )

            if result.returncode == 0:
                with open(output_path, "rb") as f:
                    buf = io.BytesIO(f.read())
                    buf.seek(0)
                    return buf
            else:
                stderr_msg = result.stderr.decode(errors="replace")
                logger.error(f"Ghostscript falhou com código {result.returncode}: {stderr_msg}")
    except FileNotFoundError:
        logger.warning("Ghostscript ('gs') não está disponível no sistema. Executando fallback em Python puro.")
    except Exception as e:
        logger.error(f"Erro inesperado ao tentar executar Ghostscript: {e}")

    return _compress_pillow_helper(pdf_bytes, image_quality=20, max_dimension=600)

_STRATEGIES = {
    CompressionLevel.low: _compress_low,
    CompressionLevel.medium: _compress_medium,
    CompressionLevel.high: _compress_high,
}

@router.post("/compress")
async def compress_pdf(
    file: UploadFile = File(...),
    level: CompressionLevel = Query(
        CompressionLevel.medium,
        description=(
            "Nível de compressão: "
            "'low' (rápido, pouca redução), "
            "'medium' (equilíbrio entre tamanho e qualidade), "
            "'high' (máxima redução, qualidade mais baixa)."
        ),
    ),
):
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O arquivo enviado não é um PDF válido.",
        )

    try:
        pdf_bytes = await file.read()
        strategy = _STRATEGIES[level]
        output_buffer = strategy(pdf_bytes)

        filename = f"compressed_{file.filename}" if file.filename else "compressed.pdf"
        return StreamingResponse(
            output_buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao tentar comprimir o PDF: {str(e)}",
        )