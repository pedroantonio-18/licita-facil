/**
 * conluio.js
 * Análise de conluio em processos licitatórios.
 *
 * Fluxo:
 * 1. Servidor seleciona os PDFs de cada empresa participante
 * 2. Com chave do Gemini: o navegador (que tem internet) envia os PDFs ao Gemini
 *    e importa o JSON no data-crossing (/conluio/importar).
 *    Sem chave: os PDFs vão direto ao data-crossing (/conluio/processar),
 *    que extrai localmente, sem internet.
 * 3. data-crossing cruza os dados (regras R01–R08, determinísticas)
 * 4. Opcional, com chave: o data-crossing monta o prompt do parecer, o navegador
 *    o envia ao Gemini e devolve a resposta para validação (padrão de relé)
 * 5. data-crossing gera o relatório PDF, que fica em "Arquivos recentes"
 */

import { saveFile } from './db.js';
import { renderRecentFiles } from './recentFiles.js';

const DATA_CROSSING = 'http://localhost:8001';

// Modelos tentados em ordem. Se um estiver sobrecarregado (503), no limite de uso
// (429) ou indisponível para a chave (404), passa ao próximo em vez de insistir.
// Referência: https://ai.google.dev/gemini-api/docs/deprecations
const GEMINI_MODELOS = ['gemini-3.5-flash-lite', 'gemini-3.8-flash', 'gemini-3.1-flash-lite'];
const GEMINI_TENTATIVAS_POR_MODELO = 2;
// Último modelo que respondeu: as chamadas seguintes começam por ele
let modeloQueRespondeu = null;
const geminiUrl = modelo => `https://generativelanguage.googleapis.com/v1beta/models/${modelo}:generateContent`;

// Mesma chave usada pelo Playground Gemini
const CHAVE_STORAGE = 'GEMINI_API_KEY';

const PROMPT_EXTRACAO = `
Você é um extrator especializado em documentos jurídicos brasileiros de habilitação licitatória.
Analise TODOS os documentos anexados. Para páginas digitalizadas ou imagens (CNH, OAB, certidões),
faça OCR e transcreva. Não economize tokens. Extraia absolutamente todos os dados.

Não inclua como pessoa da empresa o usuário consultante que aparece no cabeçalho das
consultas SICAF (formato "NOME 000.000.000-00 - Governo (Uasg: ...)"); se quiser registrá-lo,
use a função "usuário consultante SICAF".

Retorne APENAS o JSON abaixo, sem texto adicional, sem markdown:

{
  "empresa_razao_social": "razão social da empresa principal do documento",
  "empresa_cnpj_principal": "CNPJ da empresa principal, só dígitos",
  "cnpjs": [{"valor": "só dígitos", "valor_formatado": "com pontuação", "trecho": "contexto"}],
  "cpfs":  [{"valor": "só dígitos", "valor_formatado": "com pontuação", "trecho": "contexto"}],
  "ceps":  [{"valor": "só dígitos", "valor_formatado": "com pontuação", "trecho": "contexto"}],
  "telefones": [{"valor": "dígitos com DDD", "valor_formatado": "(XX) XXXXX-XXXX", "trecho": "contexto"}],
  "enderecos": [{"valor": "endereço completo com número, quadra, lote, sala, bairro, cidade-UF", "trecho": "de quem é (sede, filial, cartório, contador...)"}],
  "pessoas": [{
    "nome": "nome completo",
    "cpf": "xxx.xxx.xxx-xx ou null",
    "rg": "número ou null",
    "nascimento": "dd/mm/aaaa ou null",
    "naturalidade": "cidade-UF ou null",
    "estado_civil": "casado/solteiro/etc ou null",
    "profissao": "profissão ou null",
    "endereco": "endereço residencial completo ou null",
    "filiacao_pai": "nome do pai ou null",
    "filiacao_mae": "nome da mãe ou null",
    "conjuge": "nome do cônjuge ou null",
    "regime_bens": "comunhão parcial/separação absoluta/etc ou null",
    "funcao": "administrador/sócio/procurador/etc ou null"
  }]
}`;

const PDF_ICON_SVG = `<svg class="file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>`;

const DOWNLOAD_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>`;

const TRASH_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path><path d="M10 11v6"></path><path d="M14 11v6"></path><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path></svg>`;

const ROTULO_PRIORIDADE = { alta: 'Alta', media: 'Média', baixa: 'Baixa' };

// ---------------------------------------------------------------------------
// Helpers de UI
// ---------------------------------------------------------------------------

/** Falha da API do Gemini, com mensagem curta e legível para o servidor. */
class ErroGemini extends Error {
    constructor(status, corpo) {
        let detalhe = corpo;
        try { detalhe = JSON.parse(corpo).error?.message || corpo; } catch { /* corpo não é JSON */ }
        const resumo = {
            0: 'sem conexão',
            200: 'resposta inválida',
            400: 'requisição recusada (arquivo grande demais ou inválido?)',
            403: 'chave sem permissão',
            404: 'modelo não encontrado',
            429: 'limite de uso da chave atingido',
            503: 'sobrecarregado',
        }[status] || `erro ${status}`;
        super(`Gemini: ${resumo}${detalhe ? ` — ${String(detalhe).slice(0, 160)}` : ''}`);
        this.status = status;
    }
}

function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function downloadBlob(blob, name) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
}

function esc(texto) {
    const div = document.createElement('div');
    div.textContent = texto ?? '';
    return div.innerHTML;
}

function chaveInicial() {
    try {
        return import.meta.env?.VITE_GEMINI_API_KEY || localStorage.getItem(CHAVE_STORAGE) || '';
    } catch {
        return '';
    }
}

// ---------------------------------------------------------------------------
// Inicialização
// ---------------------------------------------------------------------------

export function initConluio() {
    const section = document.getElementById('conluio');
    if (!section) return;

    // Estado. Cada empresa é um objeto estável: remover uma não afeta as outras.
    // dadosGemini guarda a última extração, para não chamar o Gemini duas vezes.
    let empresas = [];   // [{nome, cnpj, arquivos: [File], dadosGemini: null|object, elemento}]
    let processoId = '';
    let apiKey = chaveInicial();

    // Referências da UI
    const apiKeyInput      = section.querySelector('#conluio-api-key');
    const processoInput    = section.querySelector('#conluio-processo-id');
    const parecerCheck     = section.querySelector('#conluio-parecer');
    const modoInfo         = section.querySelector('.conluio-modo');
    const empresasList     = section.querySelector('#conluio-empresas-lista');
    const addBtn           = section.querySelector('#conluio-add-empresa');
    const analisarBtn      = section.querySelector('#conluio-analisar');
    const statusMsg        = section.querySelector('.conluio-status');
    const resultsContainer = section.querySelector('.conluio-results');

    apiKeyInput.value = apiKey;
    atualizarModo();

    apiKeyInput.addEventListener('input', e => {
        apiKey = e.target.value.trim();
        try {
            if (apiKey) localStorage.setItem(CHAVE_STORAGE, apiKey);
            else localStorage.removeItem(CHAVE_STORAGE);
        } catch { /* armazenamento indisponível: a chave vale só nesta página */ }
        atualizarModo();
        atualizarBotao();
    });

    processoInput.addEventListener('input', e => {
        processoId = e.target.value.trim();
        atualizarBotao();
    });

    addBtn.addEventListener('click', () => adicionarEmpresa());
    analisarBtn.addEventListener('click', () => iniciarAnalise());

    function temChave() {
        return apiKey.length > 10;
    }

    function atualizarModo() {
        parecerCheck.disabled = !temChave();
        if (!temChave()) parecerCheck.checked = false;
        modoInfo.textContent = temChave()
            ? 'Extração pelo Gemini (via navegador). O parecer de IA é opcional.'
            : 'Sem chave: extração local no servidor, sem internet. O relatório sai completo, sem a seção de parecer de IA.';
    }

    // ---------------------------------------------------------------------------
    // Gerenciamento de empresas
    // ---------------------------------------------------------------------------

    function adicionarEmpresa() {
        const empresa = { nome: '', cnpj: '', arquivos: [], dadosGemini: null, elemento: null };
        empresas.push(empresa);

        const hint = empresasList.querySelector('.conluio-hint');
        if (hint) hint.remove();

        const bloco = document.createElement('div');
        bloco.className = 'conluio-empresa-bloco';
        bloco.innerHTML = `
            <div class="empresa-bloco-header">
                <span class="empresa-bloco-titulo"></span>
                <button type="button" class="empresa-remover" title="Remover empresa">
                    ${TRASH_SVG}
                </button>
            </div>
            <input type="text" class="conluio-input conluio-empresa-nome"
                placeholder="Razão social da empresa" />
            <input type="text" class="conluio-input conluio-empresa-cnpj"
                placeholder="CNPJ (apenas dígitos)" />
            <div class="empresa-dropzone">
                <input type="file" class="conluio-file-input" accept=".pdf,application/pdf" multiple hidden />
                <p class="dropzone-text">Arraste os PDFs aqui ou
                    <span class="dropzone-link">clique para selecionar</span>
                </p>
                <span class="dropzone-hint">Suporta múltiplos arquivos .pdf</span>
            </div>
            <ul class="empresa-arquivos-lista"></ul>
            <p class="empresa-status"></p>
        `;
        empresa.elemento = bloco;
        empresasList.appendChild(bloco);
        numerarEmpresas();

        const nomeInput    = bloco.querySelector('.conluio-empresa-nome');
        const cnpjInput    = bloco.querySelector('.conluio-empresa-cnpj');
        const dropzone     = bloco.querySelector('.empresa-dropzone');
        const fileInput    = bloco.querySelector('.conluio-file-input');
        const removeBtn    = bloco.querySelector('.empresa-remover');

        nomeInput.addEventListener('input', e => {
            empresa.nome = e.target.value.trim();
            atualizarBotao();
        });

        cnpjInput.addEventListener('input', e => {
            empresa.cnpj = e.target.value.replace(/\D/g, '');
            atualizarBotao();
        });

        dropzone.addEventListener('click', () => fileInput.click());
        dropzone.addEventListener('dragover', e => {
            e.preventDefault();
            dropzone.classList.add('drag-over');
        });
        dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag-over'));
        dropzone.addEventListener('drop', e => {
            e.preventDefault();
            dropzone.classList.remove('drag-over');
            adicionarArquivos(empresa, Array.from(e.dataTransfer.files));
        });
        fileInput.addEventListener('change', () => {
            adicionarArquivos(empresa, Array.from(fileInput.files));
            fileInput.value = '';
        });

        removeBtn.addEventListener('click', () => {
            empresas = empresas.filter(e => e !== empresa);
            bloco.remove();
            if (empresas.length === 0) {
                empresasList.innerHTML = '<p class="conluio-hint">Nenhuma empresa adicionada ainda.</p>';
            }
            numerarEmpresas();
            atualizarBotao();
        });
    }

    function numerarEmpresas() {
        empresas.forEach((e, i) => {
            e.elemento.querySelector('.empresa-bloco-titulo').textContent = `Empresa ${i + 1}`;
        });
    }

    function adicionarArquivos(empresa, files) {
        const pdfs = files.filter(f => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'));
        if (pdfs.length === 0) return;

        empresa.arquivos.push(...pdfs);
        empresa.dadosGemini = null;
        renderArquivos(empresa);
        atualizarBotao();

        if (!empresa.nome || !empresa.cnpj) identificarEmpresa(empresa);
    }

    // Sugere razão social e CNPJ lendo o texto dos PDFs no próprio servidor:
    // instantâneo, sem internet e sem gastar cota do Gemini.
    async function identificarEmpresa(empresa) {
        const nomeInput = empresa.elemento.querySelector('.conluio-empresa-nome');
        const cnpjInput = empresa.elemento.querySelector('.conluio-empresa-cnpj');
        const form = new FormData();
        empresa.arquivos.forEach(f => form.append('arquivos', f, f.name));

        setStatusEmpresa(empresa, 'Lendo os PDFs para sugerir razão social e CNPJ...', 'loading');
        try {
            const r = await jsonOuErro(
                fetch(`${DATA_CROSSING}/conluio/identificar`, { method: 'POST', body: form }),
                'Identificação'
            );
            const preenchidos = [];
            if (r.razao_social && !empresa.nome) {
                empresa.nome = r.razao_social;
                nomeInput.value = r.razao_social;
                preenchidos.push('razão social');
            }
            if (r.cnpj && !empresa.cnpj) {
                empresa.cnpj = r.cnpj;
                cnpjInput.value = r.cnpj;
                preenchidos.push('CNPJ');
            }
            if (preenchidos.length) {
                setStatusEmpresa(empresa, `Sugerido a partir dos PDFs: ${preenchidos.join(' e ')}. Confira antes de analisar.`, 'success');
            } else if (!r.cnpj) {
                setStatusEmpresa(empresa, 'Não encontrei CNPJ no texto dos PDFs (podem ser digitalizados). Preencha manualmente.', 'error');
            } else {
                setStatusEmpresa(empresa, '');
            }
        } catch (erro) {
            setStatusEmpresa(empresa, `Não foi possível sugerir os dados: ${erro.message}. Preencha manualmente.`, 'error');
        }
        atualizarBotao();
    }

    function setStatusEmpresa(empresa, texto, tipo = '') {
        const el = empresa.elemento.querySelector('.empresa-status');
        el.textContent = texto;
        el.className = `empresa-status ${tipo}`;
    }

    function renderArquivos(empresa) {
        const lista = empresa.elemento.querySelector('.empresa-arquivos-lista');
        lista.innerHTML = '';
        empresa.arquivos.forEach(f => {
            const li = document.createElement('li');
            li.className = 'conluio-arquivo-item';
            li.innerHTML = `
                <div class="file-icon-wrapper pdf-icon">${PDF_ICON_SVG}</div>
                <div class="file-details">
                    <span class="file-name" title="${esc(f.name)}">${esc(f.name)}</span>
                    <span class="file-meta">${formatSize(f.size)}</span>
                </div>
                <button type="button" class="file-action-btn" title="Remover arquivo">${TRASH_SVG}</button>
            `;
            li.querySelector('.file-action-btn').addEventListener('click', () => {
                empresa.arquivos = empresa.arquivos.filter(a => a !== f);
                empresa.dadosGemini = null;
                renderArquivos(empresa);
                atualizarBotao();
            });
            lista.appendChild(li);
        });
    }

    // ---------------------------------------------------------------------------
    // Controle do botão Analisar
    // ---------------------------------------------------------------------------

    function atualizarBotao() {
        const pronto = (
            processoId.length > 0 &&
            empresas.length >= 2 &&
            empresas.every(e => e.nome && e.cnpj.length === 14 && e.arquivos.length > 0)
        );
        analisarBtn.disabled = !pronto;
    }

    // ---------------------------------------------------------------------------
    // Fluxo principal
    // ---------------------------------------------------------------------------

    async function iniciarAnalise() {
        analisarBtn.disabled = true;
        resultsContainer.innerHTML = '';
        const usarGemini = temChave();
        const querParecer = usarGemini && parecerCheck.checked;
        const ocorrencias = [];   // fatos do fluxo que o servidor precisa saber (ex.: fallback)

        try {
            setStatus('Iniciando análise...', 'loading');
            await fetch(
                `${DATA_CROSSING}/conluio/sessao/${encodeURIComponent(processoId)}`,
                { method: 'DELETE' }
            ).catch(() => {});

            for (let i = 0; i < empresas.length; i++) {
                const empresa = empresas[i];
                const prefixo = `[${i + 1}/${empresas.length}] "${empresa.nome}"`;

                if (usarGemini) {
                    try {
                        if (!empresa.dadosGemini) {
                            setStatus(`${prefixo}: extraindo dados com o Gemini...`, 'loading');
                            empresa.dadosGemini = await extrairComGemini(
                                empresa.arquivos,
                                msg => setStatus(`${prefixo}: ${msg}`, 'loading')
                            );
                        }
                        setStatus(`${prefixo}: importando dados...`, 'loading');
                        await importarNoCrossing(empresa, empresa.dadosGemini);
                    } catch (erro) {
                        if (!(erro instanceof ErroGemini)) throw erro;
                        // Gemini indisponível: segue com a extração local para esta empresa.
                        // O relatório registra a origem dos dados de cada empresa.
                        ocorrencias.push(`"${empresa.nome}": ${erro.message} — usada a extração local.`);
                        setStatus(`${prefixo}: Gemini indisponível, extraindo localmente...`, 'loading');
                        await processarLocalmente(empresa);
                    }
                } else {
                    setStatus(`${prefixo}: extraindo dados localmente...`, 'loading');
                    await processarLocalmente(empresa);
                }
            }

            setStatus('Cruzando dados entre empresas...', 'loading');
            const resultado = await cruzarDados();

            let parecer = null;
            // Vale também sem achados: a avaliação geral se apoia nos dados extraídos
            if (querParecer) {
                setStatus('Solicitando parecer preliminar ao Gemini...', 'loading');
                try {
                    parecer = await gerarParecer(msg => setStatus(`Parecer: ${msg}`, 'loading'));
                } catch (erro) {
                    if (!(erro instanceof ErroGemini)) throw erro;
                    ocorrencias.push(`Parecer de IA não gerado: ${erro.message}. O relatório saiu sem essa seção.`);
                }
            }

            setStatus('Gerando relatório...', 'loading');
            const { blob, sha256 } = await baixarRelatorio();
            const nomeArquivo = `relatorio_conluio_${processoId.replace(/[^\w.-]/g, '_')}.pdf`;

            await saveFile({
                name: nomeArquivo,
                blob,
                mimeType: 'application/pdf',
                size: blob.size,
                source: 'conluio',
            });
            renderRecentFiles();
            downloadBlob(blob, nomeArquivo);

            resultado.avisos = [...ocorrencias, ...(resultado.avisos || [])];
            renderResultado(resultado, parecer, nomeArquivo, blob, sha256);
            setStatus(
                `Relatório gerado: ${resultado.total_achados} achado(s) entre ${resultado.empresas_analisadas} empresas.`,
                'success'
            );
        } catch (erro) {
            setStatus(`Erro: ${erro.message}`, 'error');
            console.error('[Conluio]', erro);
        } finally {
            atualizarBotao();
        }
    }

    // ---------------------------------------------------------------------------
    // Resultado na tela
    // ---------------------------------------------------------------------------

    function renderResultado(resultado, parecer, nomeArquivo, blob, sha256) {
        const achados = resultado.achados || [];
        const desconsiderados = resultado.desconsiderados || [];
        const avisos = [...new Set(resultado.avisos || [])];

        const linhasAchados = achados.map(a => `
            <tr>
                <td><span class="prioridade prioridade-${esc(a.prioridade)}">${ROTULO_PRIORIDADE[a.prioridade] || '—'}</span></td>
                <td>${esc(a.id)}</td>
                <td>${esc(a.regra_codigo)}</td>
                <td>${esc(a.empresa_a)} × ${esc(a.empresa_b)}</td>
                <td>${esc(a.valor)}</td>
            </tr>`).join('');

        resultsContainer.innerHTML = `
            <h3 class="session-results-title">Resultado da análise</h3>
            <ul class="session-results-list"></ul>
            <div class="conluio-resumo">
                ${achados.length
                    ? `<table class="conluio-achados">
                           <thead><tr><th>Prioridade</th><th>Achado</th><th>Regra</th><th>Empresas</th><th>Valor</th></tr></thead>
                           <tbody>${linhasAchados}</tbody>
                       </table>`
                    : '<p class="conluio-hint">Nenhuma coincidência localizada entre as empresas pelas regras R01–R08.</p>'}
                ${desconsiderados.length
                    ? `<p class="conluio-nota">${desconsiderados.length} valor(es) desconsiderado(s) do cruzamento (ex.: consultante SICAF, Junta Comercial). Lista completa no anexo do relatório.</p>`
                    : ''}
                ${parecer?.avaliacao_geral
                    ? `<div class="conluio-avaliacao">
                           <span class="conluio-avaliacao-rotulo">Avaliação geral da IA (preliminar, não vinculante)</span>
                           <p>${esc(parecer.avaliacao_geral.conclusao)}</p>
                       </div>`
                    : ''}
                ${parecer
                    ? `<p class="conluio-nota">Parecer de IA: ${parecer.avaliacao_geral ? 'avaliação geral aceita' : 'avaliação geral descartada pela validação'}; ${parecer.aceitos.length} comentário(s) aceito(s), ${parecer.descartados.length} item(ns) descartado(s). Detalhes na seção 4 do relatório.</p>`
                    : ''}
                ${avisos.map(a => `<p class="conluio-aviso">${esc(a)}</p>`).join('')}
            </div>
        `;

        const li = document.createElement('li');
        li.className = 'session-result-item';
        li.innerHTML = `
            <div class="file-icon-wrapper pdf-icon">${PDF_ICON_SVG}</div>
            <div class="file-details">
                <span class="file-name">${esc(nomeArquivo)}</span>
                <span class="file-meta" title="SHA-256 registrado na emissão">SHA-256 ${esc(sha256.slice(0, 16))}…</span>
            </div>
            <button class="file-action-btn" title="Baixar relatório">${DOWNLOAD_SVG}</button>
        `;
        li.querySelector('.file-action-btn').addEventListener('click', () => downloadBlob(blob, nomeArquivo));
        resultsContainer.querySelector('.session-results-list').appendChild(li);
    }

    function setStatus(text, type = '') {
        statusMsg.textContent = text;
        statusMsg.className = `conluio-status ${type}`;
    }

    // ---------------------------------------------------------------------------
    // Gemini (chamado pelo navegador — o backend não tem internet)
    // ---------------------------------------------------------------------------

    function pdfParaBase64(arquivo) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload  = () => resolve(reader.result.split(',')[1]);
            reader.onerror = reject;
            reader.readAsDataURL(arquivo);
        });
    }

    function extrairObjetoJson(texto) {
        const inicio = texto.indexOf('{');
        if (inicio === -1) throw new ErroGemini(200, 'resposta não é JSON');

        // Encontra o fechamento correto contando chaves
        let profundidade = 0;
        for (let j = inicio; j < texto.length; j++) {
            if (texto[j] === '{') profundidade++;
            else if (texto[j] === '}') {
                profundidade--;
                if (profundidade === 0) return JSON.parse(texto.slice(inicio, j + 1));
            }
        }
        throw new ErroGemini(200, 'JSON incompleto na resposta');
    }

    /**
     * Envia a requisição ao Gemini percorrendo GEMINI_MODELOS.
     * Retorna {texto, modelo}: o modelo que respondeu fica registrado no relatório.
     */
    async function chamarGemini(partes, onStatus = () => {}) {
        const body = JSON.stringify({
            contents: [{ parts: partes }],
            generationConfig: {
                temperature: 0,
                responseMimeType: 'application/json',
            },
        });

        const ordem = modeloQueRespondeu
            ? [modeloQueRespondeu, ...GEMINI_MODELOS.filter(m => m !== modeloQueRespondeu)]
            : GEMINI_MODELOS;

        let ultimoErro = null;
        for (const [m, modelo] of ordem.entries()) {
            for (let i = 0; i < GEMINI_TENTATIVAS_POR_MODELO; i++) {
                let response;
                try {
                    response = await fetch(`${geminiUrl(modelo)}?key=${encodeURIComponent(apiKey)}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body,
                    });
                } catch {
                    throw new ErroGemini(0, 'sem conexão com a API do Gemini');
                }

                if (response.ok) {
                    const data = await response.json();
                    const texto = data.candidates?.[0]?.content?.parts?.[0]?.text;
                    if (!texto) throw new ErroGemini(200, 'resposta sem conteúdo');
                    modeloQueRespondeu = modelo;
                    return { texto, modelo };
                }

                ultimoErro = new ErroGemini(response.status, await response.text());

                // Erros que não mudam trocando de modelo: chave inválida, arquivo recusado etc.
                if (![404, 429, 503].includes(response.status)) throw ultimoErro;
                // 404: modelo indisponível para esta chave — não adianta repetir
                if (response.status === 404) break;

                if (i < GEMINI_TENTATIVAS_POR_MODELO - 1) {
                    const motivo = response.status === 429 ? 'no limite de uso' : 'sobrecarregado';
                    onStatus(`${modelo} ${motivo}, nova tentativa em 3s...`);
                    await new Promise(r => setTimeout(r, 3000));
                }
            }
            const proximo = ordem[m + 1];
            if (proximo) onStatus(`${modelo} indisponível agora, tentando ${proximo}...`);
        }
        throw ultimoErro;
    }

    async function extrairComGemini(arquivos, onStatus) {
        const partes = await Promise.all(
            arquivos.map(async f => ({
                inlineData: { mimeType: 'application/pdf', data: await pdfParaBase64(f) },
            }))
        );
        partes.push({ text: PROMPT_EXTRACAO });
        const { texto, modelo } = await chamarGemini(partes, onStatus);
        return { ...extrairObjetoJson(texto), _modelo: modelo };
    }

    async function gerarParecer(onStatus) {
        const pedido = await jsonOuErro(
            fetch(`${DATA_CROSSING}/conluio/parecer/${encodeURIComponent(processoId)}/prompt`),
            'Parecer'
        );
        if (!pedido.aplicavel) return null;

        // A resposta vai crua para o backend: a validação item a item é feita lá
        const { texto: resposta, modelo } = await chamarGemini([{ text: pedido.prompt }], onStatus);
        return jsonOuErro(
            fetch(`${DATA_CROSSING}/conluio/parecer/${encodeURIComponent(processoId)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ modelo, resposta }),
            }),
            'Parecer'
        );
    }

    // ---------------------------------------------------------------------------
    // data-crossing
    // ---------------------------------------------------------------------------

    async function jsonOuErro(promessa, etapa) {
        let response;
        try {
            response = await promessa;
        } catch {
            throw new Error(`${etapa}: serviço de cruzamento indisponível em ${DATA_CROSSING}`);
        }
        if (!response.ok) throw new Error(`${etapa}: ${await response.text()}`);
        return response.json();
    }

    function importarNoCrossing(empresa, dados) {
        return jsonOuErro(fetch(`${DATA_CROSSING}/conluio/importar`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                processo_id:   processoId,
                empresa_nome:  empresa.nome,
                empresa_cnpj:  empresa.cnpj,
                cnpjs:         dados.cnpjs     || [],
                cpfs:          dados.cpfs      || [],
                ceps:          dados.ceps      || [],
                telefones:     dados.telefones || [],
                pessoas:       dados.pessoas   || [],
                enderecos:     (dados.enderecos || []).filter(e => e && typeof e.valor === 'string'),
                modelo:        dados._modelo   || null,
            }),
        }), 'Importação');
    }

    function processarLocalmente(empresa) {
        const form = new FormData();
        form.append('processo_id', processoId);
        form.append('empresa_nome', empresa.nome);
        form.append('empresa_cnpj', empresa.cnpj);
        empresa.arquivos.forEach(f => form.append('arquivos', f, f.name));
        return jsonOuErro(
            fetch(`${DATA_CROSSING}/conluio/processar`, { method: 'POST', body: form }),
            'Extração local'
        );
    }

    function cruzarDados() {
        return jsonOuErro(
            fetch(`${DATA_CROSSING}/conluio/cruzar/${encodeURIComponent(processoId)}`, { method: 'POST' }),
            'Cruzamento'
        );
    }

    async function baixarRelatorio() {
        let response;
        try {
            response = await fetch(`${DATA_CROSSING}/conluio/relatorio/${encodeURIComponent(processoId)}`);
        } catch {
            throw new Error(`Relatório: serviço de cruzamento indisponível em ${DATA_CROSSING}`);
        }
        if (!response.ok) throw new Error(`Relatório: ${await response.text()}`);
        return {
            blob: await response.blob(),
            sha256: response.headers.get('X-Relatorio-SHA256') || '',
        };
    }
}
