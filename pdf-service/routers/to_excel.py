from fastapi import APIRouter, UploadFile, File, HTTPException, status
from fastapi.responses import StreamingResponse
import pdfplumber
import io
import pandas as pd
import logging
from typing import List

logger = logging.getLogger("pdf_service.to_excel")

router = APIRouter(
    prefix="/excel",
    tags=["PDF to Excel Converter"]
)

@router.post("/convert")
async def convert_pdf_to_excel(
    file: UploadFile = File(...)
):
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O arquivo enviado não é um PDF válido."
        )

    try:
        pdf_bytes = await file.read()
        all_rows = []
        is_first = True

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                tables = page.extract_tables()
                for table in tables:
                    if not table:
                        continue
                    if is_first:
                        all_rows.extend(table)
                        is_first = False
                    else:
                        all_rows.extend(table[1:])

        if not all_rows:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nenhuma tabela pôde ser extraída do PDF enviado."
            )

        standard_cols = 7
        cleaned_rows = []
        for row in all_rows:
            if not row:
                continue
            padded_row = [str(cell).strip() if cell is not None else "" for cell in row]
            if len(padded_row) < standard_cols:
                padded_row.extend([""] * (standard_cols - len(padded_row)))
            elif len(padded_row) > standard_cols:
                padded_row = padded_row[:standard_cols]
            cleaned_rows.append(padded_row)

        combined_df = pd.DataFrame(cleaned_rows)

        combined_df = combined_df.iloc[1:, 1:]
        combined_df.columns = list(range(len(combined_df.columns)))

        combined_df.iloc[:, 0] = combined_df.iloc[:, 1]

        combined_df.iloc[:, 1] = ""
        combined_df.iloc[:, 1] = combined_df.iloc[:, 4].astype(str).str[:250]

        combined_df["Coluna9"] = combined_df.iloc[:, 4]
        combined_df["Coluna10"] = combined_df.iloc[:, 3]
        combined_df["Coluna11"] = combined_df.iloc[:, 2]

        combined_df.iloc[:, 2] = combined_df["Coluna9"]
        combined_df.iloc[:, 4] = combined_df["Coluna10"]
        combined_df.iloc[:, 3] = combined_df["Coluna11"]

        combined_df.drop(columns=["Coluna9", "Coluna10", "Coluna11"], inplace=True)

        headers = [
            "Código",
            "Nome",
            "Descrição",
            "Quantidade",
            "Unidade De Medida",
        ]

        if len(combined_df.columns) >= len(headers):
            combined_df = combined_df.iloc[:, : len(headers)]
            combined_df.columns = headers
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Número de colunas insuficiente no PDF estruturado."
            )

        output_buffer = io.BytesIO()
        with pd.ExcelWriter(output_buffer, engine='openpyxl') as writer:
            combined_df.to_excel(writer, index=False, sheet_name="Itens de Licitação")
            
            worksheet = writer.sheets["Itens de Licitação"]
            
            column_width_caps = {
                "Código": 20,
                "Nome": 40,
                "Descrição": 60,
                "Quantidade": 15,
                "Unidade De Medida": 15
            }
            
            for col in worksheet.columns:
                header_value = str(col[0].value or '')
                max_len = max(len(str(cell.value or '')) for cell in col)
                col_letter = col[0].column_letter
                
                base_width = max(max_len + 3, 12)
                cap = column_width_caps.get(header_value)
                
                final_width = min(base_width, cap) if cap is not None else base_width
                worksheet.column_dimensions[col_letter].width = final_width

        output_buffer.seek(0)
        excel_bytes = output_buffer.getvalue()

        original_name = file.filename or "licitacao.pdf"
        base_name = original_name.rsplit('.', 1)[0]
        output_filename = f"{base_name}.xlsx"

        return StreamingResponse(
            io.BytesIO(excel_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={output_filename}"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao processar PDF para Excel: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno ao converter PDF: {str(e)}"
        )
