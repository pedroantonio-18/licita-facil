from detector import detect
from extractor import extract
from ocr import pdf_to_text
from database import create_tables, salvar_empresa, salvar_campos
import sys

if len(sys.argv) < 2:
    print("Usage: python3 main.py file.pdf")
    sys.exit(1)

# cria as tabelas se ainda não existirem
create_tables()

doc = sys.argv[1]
result = detect(doc)

if result["type"] == "searchable":
    text = result["text"]
else:
    result = pdf_to_text(doc)
    text = result["text"]

extracted = extract(text)

# pega o nome do arquivo sem o caminho
nome_arquivo = doc.split('/')[-1]

# tenta pegar o primeiro CNPJ extraído, senão pede pro usuário
if extracted["cnpjs"]:
    cnpj = extracted["cnpjs"][0]
else:
    cnpj = input("CNPJ não encontrado no documento. Digite manualmente: ")

empresa_id = salvar_empresa(cnpj, "desconhecido", nome_arquivo)
salvar_campos(empresa_id, extracted)

print(f'\n--- RESULTADO ---')
print(f'Arquivo: {nome_arquivo}')
print(f'Tipo: {result["type"]}')
print(f'Empresa salva com id: {empresa_id}')
print(f'CPFs: {extracted["cpfs"]}')
print(f'CNPJs: {extracted["cnpjs"]}')
print(f'CEPs: {extracted["ceps"]}')
print(f'Phones: {extracted["phones"]}')
print(f'Pessoas: {extracted["people"]}')