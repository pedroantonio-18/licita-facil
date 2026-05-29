import sqlite3

def get_connection():
    return sqlite3.connect('sad-jf.db')

def create_tables():
    conn = get_connection()
    cursor = conn.cursor()

    # tabela principal — uma linha por empresa
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS empresas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cnpj TEXT,
            nome TEXT,
            arquivo TEXT
        )
    ''')

    # campos extraídos — CPF, CEP, telefone etc
    # empresa_id liga cada campo à sua empresa
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS campos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER,
            tipo TEXT,
            valor TEXT,
            FOREIGN KEY (empresa_id) REFERENCES empresas(id)
        )
    ''')

    # pessoas com função — sócio, contador, procurador etc
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pessoas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER,
            funcao TEXT,
            nome TEXT,
            FOREIGN KEY (empresa_id) REFERENCES empresas(id)
        )
    ''')

    conn.commit()
    conn.close()

def salvar_empresa(cnpj: str, nome: str, arquivo: str) -> int:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        'INSERT INTO empresas (cnpj, nome, arquivo) VALUES (?, ?, ?)',
        (cnpj, nome, arquivo)
    )

    empresa_id = cursor.lastrowid  # pega o id gerado automaticamente
    conn.commit()
    conn.close()
    return empresa_id

def salvar_campos(empresa_id: int, extracted: dict):
    conn = get_connection()
    cursor = conn.cursor()

    # salva cada CPF
    for cpf in extracted["cpfs"]:
        cursor.execute(
            'INSERT INTO campos (empresa_id, tipo, valor) VALUES (?, ?, ?)',
            (empresa_id, 'cpf', cpf)
        )

    # salva cada telefone
    for phone in extracted["phones"]:
        cursor.execute(
            'INSERT INTO campos (empresa_id, tipo, valor) VALUES (?, ?, ?)',
            (empresa_id, 'telefone', phone)
        )

    # salva cada CEP
    for cep in extracted["ceps"]:
        cursor.execute(
            'INSERT INTO campos (empresa_id, tipo, valor) VALUES (?, ?, ?)',
            (empresa_id, 'cep', cep)
        )

    # salva cada pessoa
    for pessoa in extracted["people"]:
        cursor.execute(
            'INSERT INTO pessoas (empresa_id, funcao, nome) VALUES (?, ?, ?)',
            (empresa_id, pessoa["funcao"], pessoa["nome"])
        )

    conn.commit()
    conn.close()