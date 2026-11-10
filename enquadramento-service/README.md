# Enquadramento de Despesas — Licita Fácil

Acesse: **[LINK DE PRODUÇÃO — preencher após publicar no servidor]**

Gera a **Informação de estimativa e enquadramento** da despesa, pronta para colar no SEI:
calcula se é dispensa ou pregão, confere o fracionamento com o PCA, aplica a regra de
ME/EPP e escreve o valor por extenso.

> O sistema calcula e aponta; a decisão e a assinatura são do servidor responsável.

## Como usar

1. No menu lateral, abra **Enquadramento**.
2. Em **Objeto e enquadramento**, escolha a natureza (bens, serviço, serviço de engenharia,
   manutenção de veículos, obra) e o exercício. O limite da dispensa aparece logo abaixo.
3. Em **Itens e valor estimado**, informe cada item com o valor total da pesquisa de preços.
4. Em **Pesquisa de preços**, informe o nº SEI do Relatório do Banco de Preços (ou da planilha
   da SEENG), a metodologia e os incisos do art. 5º da IN 65/2021 usados.
5. Em **PCA e contratações do exercício**:
   - carregue uma vez por ano o **PDF do PCA** publicado no portal da SJGO (Plano Anual de
     Contratações). Se a tabela do PCA estiver em imagem, use **Importar a lista com a sua IA**;
   - clique em **Procurar demandas semelhantes no PCA**: o sistema lista as demandas com
     descrição parecida com o objeto. Confira se são da mesma natureza (mesmo PDM para
     materiais; mesma descrição para serviços) e clique em **Somar** nas que entram na soma;
   - inclua à mão o que já foi contratado no exercício.
   Se a própria demanda dos autos aparece no PCA, marque "É esta própria demanda": ela
   aparece na tabela, mas não é somada duas vezes.
6. Clique em **Gerar Informação**. Depois disso, o texto se atualiza enquanto você digita.
7. Clique em **Copiar para o SEI** e cole com **Ctrl+V** no documento "Informação".

## Regras aplicadas

| Regra | Como funciona |
|---|---|
| Dispensa ou pregão | soma do valor estimado + demandas semelhantes do PCA + já contratado no exercício, comparada com o limite do art. 75 (inciso I para engenharia e manutenção de veículos; inciso II para o resto) |
| Fracionamento | se a soma passa do limite, a licitação é obrigatória (art. 4º da IN SEGES/ME nº 67/2021) e o texto explica |
| ME/EPP | dispensa por valor: exclusiva para ME/EPP. Licitação, item a item: até R$ 80.000,00 exclusivo; acima e **divisível**, cota reservada de até 25% (percentual definido pelo setor requisitante); acima e indivisível, ampla participação; acima de R$ 4,8 milhões, sem tratamento favorecido. Em **grupo único** vale o valor do grupo |
| Seguridade | na dispensa, 20% do valor para o caso de contratação de pessoa física (IN SEGES/ME nº 116/2021) |
| Registro de preços | na dispensa, não utilizado (art. 82, § 6º, da Lei 14.133/2021) |

O que faltar informar sai entre colchetes, **em amarelo**, na Informação.

## Limites da dispensa

Os limites de 2026 já vêm cadastrados (Decreto nº 12.807/2025): R$ 130.984,20 no inciso I
(engenharia e manutenção de veículos) e R$ 65.492,11 no inciso II.
Enquanto o decreto do ano seguinte não sai, o sistema usa o último limite publicado e avisa.
Quando sair o novo decreto, a TI atualiza o arquivo de limites do serviço
(`ENQUADRAMENTO_LIMITES`, formato em `app/regras.py`).
