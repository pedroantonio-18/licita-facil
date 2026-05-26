import re

FUNCOES = [
    "sócio administrador", "sócio", "titular", "administrador",
    "procurador", "representante", "preposto", "contador",
    "advogado", "diretor", "responsável"
]

def extract_people(text: str) -> list:
    pessoas = []
    
    for funcao in FUNCOES:
        padrao = rf'(?i){funcao}:?\s+([A-ZÀÁÂÃÉÊÍÓÔÕÚÇ][a-zàáâãéêíóôõúç]+(?:\s+[A-ZÀÁÂÃÉÊÍÓÔÕÚÇ][a-zàáâãéêíóôõúç]+)+)'
        matches = re.findall(padrao, text)
        for nome in matches:
            pessoas.append({
                "funcao": funcao,
                "nome": nome.strip()
            })
    
    return pessoas

def extract(text: str) -> dict:
    cnpjs = list(set(re.findall(r'\d{2}\.\d{3}\.\d{3}\/\d{4}-\d{2}', text)))
    cpfs = list(set(re.findall(r'\d{3}\.\d{3}\.\d{3}-\d{2}', text)))
    ceps = list(set(re.findall(r'CEP:?\s?\d{2}\.?\d{3}-?\d{3}', text)))

    clean_text = text
    clean_text = re.sub(r'\d{2}\.\d{3}\.\d{3}\/\d{4}-\d{2}', '', clean_text)
    clean_text = re.sub(r'\d{3}\.\d{3}\.\d{3}-\d{2}', '', clean_text)
    clean_text = re.sub(r'CEP:?\s?\d{2}\.?\d{3}-?\d{3}', '', clean_text)

    phones = list(set(re.findall(r'(?:\(\d{2}\)\s?)?\d{4,5}-?\d{4}', clean_text)))

    ceps = [cep.replace('CEP', '').replace(':', '').strip() for cep in ceps]

    people = extract_people(text)

    return {
        "cnpjs": cnpjs,
        "cpfs": cpfs,
        "ceps": ceps,
        "phones": phones,
        "people": people
    }