# Análise de Conluio — Licita Fácil

Acesse: **[LINK DE PRODUÇÃO — preencher após publicar no servidor]**

Ferramenta de apoio à análise de possível conluio entre empresas licitantes. Ela lê
os documentos de habilitação de cada empresa, cruza os dados entre elas e gera um
relatório em PDF para anexar ao processo no SEI.

> O sistema **aponta coincidências**; ele não conclui que houve conluio. A análise e
> a decisão são sempre do servidor responsável.

## Como usar

1. No menu lateral, abra **Análise de Conluio**.
2. Preencha o **identificador do processo** (ex.: número do processo SEI).
3. **Chave de API do Gemini** (opcional):
   - **com chave:** a leitura dos documentos é mais completa — inclui páginas
     digitalizadas, nomes, cônjuges, filiação e endereços — e permite o parecer
     preliminar de IA;
   - **sem chave:** a leitura é feita no servidor e identifica apenas CNPJ, CPF, CEP e
     telefone em páginas com texto. O relatório avisa essas limitações.
4. Clique em **+ Adicionar empresa** para cada licitante e arraste os PDFs dela
   (contrato social, SICAF, procurações…). Razão social e CNPJ são sugeridos a partir
   dos PDFs — **confira** antes de seguir.
5. Se quiser, marque **Incluir parecer preliminar de IA**.
6. Clique em **Analisar coincidências**. O relatório é baixado e também fica em
   **Arquivos recentes**.

## O que o relatório traz

1. **Dados extraídos por empresa** — CNPJs, CPFs, CEPs, telefones, endereços e pessoas,
   numerados (E1, E1.P1…) para conferência.
2. **Achados** — cada coincidência entre duas empresas, com a regra, o valor, onde foi
   encontrado e uma nota de contexto.
3. **Triagem por prioridade** — ordem sugerida de verificação.
4. **Parecer preliminar de IA** (se solicitado) — avaliação geral em escala fechada
   ("sem indícios", "coincidências a verificar" ou "indícios relevantes") e comentários.
   Só são mantidas afirmações que citam dados do próprio relatório e não usam linguagem
   conclusiva; as descartadas aparecem com o motivo.
5. **Anexo** — dados desconsiderados e avisos de leitura.

| Regra | O que indica | Prioridade |
|---|---|---|
| R01 | mesmo CNPJ de terceiro nos documentos de duas empresas (contador, holding…) | média |
| R02 | mesmo CPF | alta |
| R03 | mesmo telefone | média |
| R04 | mesmo CEP | baixa |
| R05 | nome de pessoa muito parecido | média |
| R06 | mesma pessoa na mesma função (ex.: mesmo procurador) | alta |
| R07 | vínculo familiar entre pessoas das empresas (cônjuge, pai/mãe, irmãos) | alta |
| R08 | mesmo endereço | média |

## Como ler os resultados

- **Coincidência não é irregularidade.** Telefone de cartório, escritório de
  contabilidade em comum ou edifício comercial podem ter explicação lícita — a nota de
  cada achado ajuda a avaliar.
- **Vínculos dentro da mesma empresa** (família de sócios, holding própria) não viram
  achado: só relações entre licitantes diferentes.
- **Ficam fora do cruzamento**, e são listados no anexo: o usuário consultante do
  cabeçalho do SICAF, órgãos e agentes de registro (Junta Comercial, cartórios) e
  números com dígito verificador inválido (erro de leitura do documento).
- **Zero achados** significa que não houve coincidência nos dados lidos — não exclui
  vínculos que não constem dos documentos. Confira na seção 1 se os dados de cada
  empresa foram lidos corretamente.
- O relatório tem um **código SHA-256** registrado na emissão, para conferir depois que
  a cópia anexada ao SEI é a mesma que o sistema gerou.
