/**
 * minutas.js
 * Aviso de dispensa e edital de pregão a partir dos modelos da AGU.
 *
 * Fluxo:
 * 1. Servidor escolhe o modelo (a versão da AGU vem do rodapé do arquivo)
 * 2. Preenche os dados do processo; os dados fixos da JF já vêm preenchidos
 * 3. Marca os temas da AGU que se aplicam (registro de preços, engenharia…);
 *    os demais saem e a numeração e as referências entre itens são refeitas
 * 4. O minutas-service monta a minuta: o texto não decidido é copiado
 *    literalmente do modelo, e cada diferença fica listada com o motivo
 * 5. O servidor resolve as pendências (campos, cláusulas opcionais,
 *    alternativas "OU") e copia a minuta para o editor do SEI — numeração
 *    escrita no texto e Times 12, formato confirmado em teste de colagem no
 *    SEI do TRF1; o que estiver pendente vai com fundo amarelo
 */

const MINUTAS = 'http://localhost:8003';
const CHAVE_UNIDADE = 'minutas.unidade';

// Gemini pelo navegador (o servidor não tem internet): mesma chave e mesma ordem de modelos
// da Análise de Conluio. Se um modelo estiver sobrecarregado (503), no limite (429) ou
// indisponível para a chave (404), passa ao próximo.
const GEMINI_MODELOS = ['gemini-3.5-flash-lite', 'gemini-3.8-flash', 'gemini-3.1-flash-lite'];
const GEMINI_TENTATIVAS_POR_MODELO = 2;
const CHAVE_GEMINI = 'GEMINI_API_KEY';
const geminiUrl = modelo => `https://generativelanguage.googleapis.com/v1beta/models/${modelo}:generateContent`;
let modeloQueRespondeu = null;

function chaveGemini() {
    try { return import.meta.env?.VITE_GEMINI_API_KEY || localStorage.getItem(CHAVE_GEMINI) || ''; } catch { return ''; }
}

async function chamarGemini(prompt, onStatus = () => {}) {
    const chave = chaveGemini();
    const body = JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: { temperature: 0, responseMimeType: 'application/json' },
    });
    const ordem = modeloQueRespondeu
        ? [modeloQueRespondeu, ...GEMINI_MODELOS.filter(m => m !== modeloQueRespondeu)] : GEMINI_MODELOS;
    let ultimo = 'Gemini indisponível';
    for (const [i, modelo] of ordem.entries()) {
        for (let t = 0; t < GEMINI_TENTATIVAS_POR_MODELO; t++) {
            let r;
            try {
                r = await fetch(`${geminiUrl(modelo)}?key=${encodeURIComponent(chave)}`,
                    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body });
            } catch {
                throw new Error('Gemini: sem conexão');
            }
            if (r.ok) {
                const texto = (await r.json()).candidates?.[0]?.content?.parts?.[0]?.text;
                if (!texto) throw new Error('Gemini: resposta sem conteúdo');
                modeloQueRespondeu = modelo;
                return { texto, modelo };
            }
            ultimo = `Gemini: erro ${r.status}${r.status === 429 ? ' (limite de uso da chave)' : r.status === 403 ? ' (chave sem permissão)' : ''}`;
            if (![404, 429, 503].includes(r.status)) throw new Error(ultimo);
            if (r.status === 404) break;
            if (t < GEMINI_TENTATIVAS_POR_MODELO - 1) {
                onStatus(`${modelo} ${r.status === 429 ? 'no limite de uso' : 'sobrecarregado'}, nova tentativa em 3s…`);
                await new Promise(res => setTimeout(res, 3000));
            }
        }
        if (ordem[i + 1]) onStatus(`${modelo} indisponível agora, tentando ${ordem[i + 1]}…`);
    }
    throw new Error(ultimo);
}

const CRITERIOS = ['menor preço global', 'menor preço por item', 'menor preço por grupo',
    'maior desconto global', 'maior desconto por item', 'maior desconto por grupo'];

// Campos do formulário por tipo de minuta. [chave, rótulo, tipo, opções/placeholder]
const CAMPOS = {
    comum: [
        ['processo', 'Número do processo SEI', 'text', '0000000-00.2026.4.01.8006'],
        ['numero', 'Número da minuta', 'text', '1/2026'],
        ['objeto', 'Objeto (como deve aparecer na minuta)', 'textarea', 'empresa especializada para ...'],
        ['valor_total', 'Valor total estimado (R$)', 'text', '10.000,00'],
        ['data_sessao', 'Data da sessão pública', 'date', ''],
        ['criterio', 'Critério de julgamento', 'select', CRITERIOS],
        ['me_epp', 'Tratamento favorecido ME/EPP (capa)', 'text', 'SIM  —  ou SIM, porém sem exclusividade..., ou NÃO'],
        ['margem_preferencia', 'Margem de preferência para algum item', 'select', ['NÃO', 'SIM']],
    ],
    aviso_dispensa: [
        ['horario_lances', 'Horário da fase de lances', 'text', 'Das 08h até 14h'],
        ['inciso', 'Hipótese do art. 75 da Lei 14.133', 'select', [
            ['', '—'], ['I', 'Inciso I — obras e serviços de engenharia ou manutenção de veículos'],
            ['II', 'Inciso II — demais compras e serviços']]],
    ],
    edital_pregao: [
        ['hora_sessao', 'Horário da sessão', 'text', '14h'],
        ['modo_disputa', 'Modo de disputa', 'select', ['aberto', 'aberto e fechado', 'fechado e aberto']],
    ],
};

const CAMPOS_UNIDADE = [
    ['setor', 'Setor responsável', 'text', ''],
    ['email', 'E-mail do setor', 'text', ''],
    ['endereco', 'Endereço', 'text', ''],
    ['signatario', 'Nome de quem assina', 'text', ''],
    ['cargo', 'Cargo de quem assina', 'text', 'Supervisor(a) da Seção'],
];

const ROTULO_ORIGEM = { formulario: 'formulário', servidor: 'servidor', ia: 'IA', misto: 'formulário/IA', questionario: 'questionário' };

// Campo vermelho que é lacuna a preencher (o resto é trecho opcional: manter ou retirar)
// (inclui valor sugerido pela AGU, ex. "60 (sessenta)" — vem preenchido para confirmar ou trocar)
const LACUNA = /\[|\bX{2,}\b|\bx{2,}\b|\.{3,}|\d|valor por extenso|inserir|indicar/i;
const COM_MARCADOR = /\[|\]|\b[Xx]{2,}\b|\.{3,}|valor por extenso|inserir|indicar/i;
const MANTER_CAMPO = '__manter__';   // igual ao minutas-service (app/montagem.py)

function esc(texto) {
    const div = document.createElement('div');
    div.textContent = texto ?? '';
    return div.innerHTML;
}

function dataBR(iso) {
    if (!iso) return '';
    const [a, m, d] = iso.split('-');
    return `${d}/${m}/${a}`;
}

function lerUnidade() {
    try { return JSON.parse(localStorage.getItem(CHAVE_UNIDADE) || '{}'); } catch { return {}; }
}

function salvarUnidade(dados) {
    try { localStorage.setItem(CHAVE_UNIDADE, JSON.stringify(dados)); } catch { /* sem armazenamento */ }
}

function decisoesVazias() {
    return { remover: {}, textos: {}, campos: {}, manter: [], motivos: {}, origem: {} };
}

async function copiarTexto(texto) {
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(texto);
            return true;
        }
    } catch { /* cai no método antigo */ }
    const area = document.createElement('textarea');
    area.value = texto;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    area.remove();
    return ok;
}

export function initMinutas() {
    const section = document.getElementById('minutas');
    if (!section) return;

    const modeloSelect = section.querySelector('#minutas-modelo');
    const modeloInfo = section.querySelector('.minutas-modelo-info');
    const camposDiv = section.querySelector('.minutas-campos');
    const camposJfDiv = section.querySelector('.minutas-campos-jf');
    const temasDiv = section.querySelector('.minutas-temas');
    const questionarioDiv = section.querySelector('.minutas-questionario');
    const montarBtn = section.querySelector('#minutas-montar');
    const statusEl = section.querySelector('.minutas-status');
    const resultadoDiv = section.querySelector('.minutas-resultado');
    const trInput = section.querySelector('.minutas-tr-input');
    const trLista = section.querySelector('.minutas-tr-lista');

    let config = null;
    let decisoes = decisoesVazias();
    let ultimo = null;          // última resposta do /montar
    let montando = false;
    let textoTR = '';           // texto do TR e anexos, extraído pelo minutas-service
    let iaInfo = null;          // última rodada da IA: {aplicadas, descartes, sem_informacao, modelo}
    // Modo "minha IA": o servidor leva o pedido à ferramenta que já usa e cola a resposta aqui
    let manualAberto = false;
    let respostaManual = '';
    let incluirTR = false;
    let pedidoManual = null;    // pedido já buscado: o botão copia na hora (o navegador exige o clique)
    let ferramenta = (() => { try { return localStorage.getItem('minutas.ferramenta') || 'ChatGPT'; } catch { return 'ChatGPT'; } })();

    function setStatus(msg, tipo = '') {
        statusEl.textContent = msg;
        statusEl.className = `conluio-status minutas-status ${tipo}`;
    }

    function modeloAtual() {
        return config?.modelos.find(m => m.id === modeloSelect.value) || null;
    }

    // ------------------------------------------------------------------
    // Formulário
    // ------------------------------------------------------------------

    function campoHtml([chave, rotulo, tipo, extra], valor = '') {
        const id = `minutas-campo-${chave}`;
        let controle;
        if (tipo === 'textarea') {
            controle = `<textarea id="${id}" data-campo="${chave}" class="conluio-input" rows="2" placeholder="${esc(extra)}">${esc(valor)}</textarea>`;
        } else if (tipo === 'select') {
            const opcoes = extra.map(o => Array.isArray(o) ? o : [o, o]);
            controle = `<select id="${id}" data-campo="${chave}" class="conluio-input">${opcoes.map(([v, r]) =>
                `<option value="${esc(v)}"${v === valor ? ' selected' : ''}>${esc(r)}</option>`).join('')}</select>`;
        } else {
            controle = `<input id="${id}" data-campo="${chave}" type="${tipo}" class="conluio-input" placeholder="${esc(extra)}" value="${esc(valor)}" />`;
        }
        return `<label class="minutas-campo${tipo === 'textarea' ? ' minutas-campo-largo' : ''}" for="${id}">
                    <span class="conluio-label">${esc(rotulo)}</span>${controle}</label>`;
    }

    function desenharFormulario() {
        const m = modeloAtual();
        if (!m) return;
        const anteriores = lerFormulario();
        camposDiv.innerHTML = [...CAMPOS.comum, ...(CAMPOS[m.tipo] || [])]
            .map(c => campoHtml(c, anteriores[c[0]] ?? '')).join('');
        temasDiv.innerHTML = Object.entries(config.temas)
            .filter(([t]) => m.temas.includes(t))
            .map(([t, nome]) => `<label class="conluio-check"><input type="checkbox" data-tema="${t}"> ${esc(nome)}</label>`)
            .join('') || '<p class="conluio-modo">Este modelo não tem temas opcionais.</p>';
        const respostasAntes = respostasQuestionario();
        questionarioDiv.innerHTML = (m.perguntas || []).map(p => `
            <label class="minutas-campo" for="minutas-q-${esc(p.id)}">
                <span class="conluio-label">${esc(p.texto)}</span>
                <select id="minutas-q-${esc(p.id)}" data-pergunta="${esc(p.id)}" class="conluio-input">
                    <option value="">— não responder —</option>
                    ${p.opcoes.map(([v, r]) => `<option value="${esc(v)}"${respostasAntes[p.id] === v ? ' selected' : ''}>${esc(r)}</option>`).join('')}
                </select>
                ${p.ajuda ? `<span class="conluio-modo">${esc(p.ajuda)}</span>` : ''}
            </label>`).join('');
        modeloInfo.textContent = `Modelo da AGU, versão ${m.versao || 'não informada'} (indicada no rodapé do arquivo).`;
    }

    function desenharUnidade() {
        const salvos = lerUnidade();
        const padrao = config.dados_jf;
        camposJfDiv.innerHTML = CAMPOS_UNIDADE.map(c =>
            campoHtml(c, salvos[c[0]] ?? padrao[c[0]] ?? '')).join('') +
            `<p class="conluio-modo">Órgão: ${esc(padrao.orgao)} — UASG ${esc(padrao.uasg)}. Estes dados ficam salvos neste navegador.</p>
             <p class="conluio-modo"><label class="minutas-link">Enviar nova versão do modelo da AGU (.docx)
                <input type="file" accept=".docx" class="minutas-upload" hidden></label></p>`;
        camposJfDiv.querySelector('.minutas-upload').addEventListener('change', enviarModelo);
    }

    function lerFormulario() {
        const dados = {};
        section.querySelectorAll('[data-campo]').forEach(el => {
            dados[el.dataset.campo] = el.type === 'date' ? dataBR(el.value) : el.value.trim();
            if (el.type === 'date') dados[`${el.dataset.campo}__iso`] = el.value;
        });
        return dados;
    }

    function dadosParaEnvio() {
        const dados = lerFormulario();
        const unidade = {};
        CAMPOS_UNIDADE.forEach(([k]) => { if (dados[k] !== undefined) unidade[k] = dados[k]; });
        salvarUnidade(unidade);
        Object.keys(dados).filter(k => k.endsWith('__iso')).forEach(k => delete dados[k]);
        Object.keys(dados).forEach(k => { if (dados[k] === '') delete dados[k]; });
        return dados;
    }

    function respostasQuestionario() {
        const r = {};
        section.querySelectorAll('[data-pergunta]').forEach(el => { if (el.value) r[el.dataset.pergunta] = el.value; });
        return r;
    }

    function temasMarcados() {
        return [...temasDiv.querySelectorAll('[data-tema]:checked')].map(el => el.dataset.tema);
    }

    // ------------------------------------------------------------------
    // Servidor
    // ------------------------------------------------------------------

    async function carregarConfig() {
        try {
            const r = await fetch(`${MINUTAS}/minutas/config`);
            if (!r.ok) throw new Error();
            config = await r.json();
        } catch {
            setStatus('Serviço de minutas indisponível. Verifique se o minutas-service está rodando (porta 8003).', 'error');
            return false;
        }
        const anterior = modeloSelect.value;
        modeloSelect.innerHTML = config.modelos.map(m =>
            `<option value="${esc(m.id)}">${esc(m.tipo_nome)} — AGU ${esc(m.versao || '')}</option>`).join('');
        if (anterior && config.modelos.some(m => m.id === anterior)) modeloSelect.value = anterior;
        montarBtn.disabled = !config.modelos.length;
        if (!config.modelos.length) setStatus('Nenhum modelo da AGU disponível no servidor.', 'error');
        return true;
    }

    async function enviarModelo(e) {
        const arquivo = e.target.files[0];
        if (!arquivo) return;
        const fd = new FormData();
        fd.append('arquivo', arquivo);
        setStatus('Enviando modelo…', 'loading');
        try {
            const r = await fetch(`${MINUTAS}/minutas/modelos`, { method: 'POST', body: fd });
            const corpo = await r.json();
            if (!r.ok) throw new Error(corpo.detail || 'Falha no envio');
            await carregarConfig();
            modeloSelect.value = corpo.id;
            desenharFormulario();
            setStatus(`Modelo ${corpo.tipo_nome} — versão ${corpo.versao} adicionado.`, 'success');
        } catch (err) {
            setStatus(err.message, 'error');
        }
        e.target.value = '';
    }

    async function lerTR() {
        textoTR = '';
        trLista.innerHTML = '';
        const arquivos = [...trInput.files];
        if (!arquivos.length) return;
        const fd = new FormData();
        arquivos.forEach(f => fd.append('arquivos', f));
        setStatus('Lendo o Termo de Referência…', 'loading');
        try {
            const r = await fetch(`${MINUTAS}/minutas/texto`, { method: 'POST', body: fd });
            const corpo = await r.json();
            if (!r.ok) throw new Error(corpo.detail || 'Falha ao ler os PDFs');
            textoTR = corpo.arquivos.map(a => `=== ${a.arquivo} ===\n${a.texto}`).join('\n\n');
            trLista.innerHTML = corpo.arquivos.map(a => `<li>${esc(a.arquivo)} — ${a.paginas} pág.${a.sem_texto
                ? ' <strong class="minutas-alerta-texto">sem texto (digitalizado): a IA não consegue ler</strong>'
                : `, ${a.caracteres.toLocaleString('pt-BR')} caracteres`}</li>`).join('');
            setStatus('Termo de Referência lido.', 'success');
            if (ultimo) desenharResultado();
        } catch (err) {
            setStatus(err.message === 'Failed to fetch' ? 'Serviço de minutas indisponível.' : err.message, 'error');
        }
    }

    async function postar(caminho, corpo) {
        const r = await fetch(`${MINUTAS}${caminho}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo),
        });
        const json = await r.json();
        if (!r.ok) throw new Error(json.detail || `Falha em ${caminho}`);
        return json;
    }

    async function sugerirComIA() {
        const m = modeloAtual();
        if (!m || !ultimo) return;
        const base = { modelo_id: m.id, dados: dadosParaEnvio(), temas: temasMarcados(), respostas: respostasQuestionario(),
                       decisoes, texto_tr: textoTR };
        const btn = resultadoDiv.querySelector('#minutas-ia');
        if (btn) btn.disabled = true;
        try {
            setStatus('Preparando as pendências para a IA…', 'loading');
            const pedido = await postar('/minutas/ia/prompt', base);
            if (!pedido.aplicavel) { setStatus('Não há pendências para a IA decidir.', 'success'); return; }
            setStatus(`Enviando ${pedido.pendencias} pendência(s) e o TR ao Gemini…`, 'loading');
            const { texto, modelo } = await chamarGemini(pedido.prompt, msg => setStatus(msg, 'loading'));
            await aplicarResposta(base, texto, modelo);
        } catch (err) {
            setStatus(err.message === 'Failed to fetch' ? 'Serviço de minutas indisponível.' : err.message, 'error');
            if (btn) btn.disabled = false;
        }
    }

    /** Confere a resposta da IA no minutas-service e aplica o que passou. */
    async function aplicarResposta(base, texto, modelo) {
        setStatus('Conferindo as sugestões da IA…', 'loading');
        const v = await postar('/minutas/ia/validar', { ...base, resposta: texto });
        // Decisões do servidor prevalecem: a IA só preenche o que ainda está em aberto
        for (const k of ['remover', 'textos', 'campos', 'motivos', 'origem']) {
            for (const [id, valor] of Object.entries(v.decisoes[k])) {
                if (decisoes.origem[id] !== 'servidor') decisoes[k][id] = valor;
            }
        }
        v.decisoes.manter.forEach(id => { if (!decisoes.manter.includes(id)) decisoes.manter.push(id); });
        iaInfo = { ...v, modelo };
        await montar();
        if (!v.aplicadas.length && v.descartes.length && !v.descartes[0].bloco) {
            setStatus(v.descartes[0].motivo, 'error');       // ex.: resposta fora do formato
        }
    }

    function basePedidoIA() {
        const m = modeloAtual();
        return { modelo_id: m.id, dados: dadosParaEnvio(), temas: temasMarcados(), respostas: respostasQuestionario(),
                 decisoes, texto_tr: textoTR };
    }

    async function atualizarPedidoManual() {
        pedidoManual = null;
        const area = resultadoDiv.querySelector('#minutas-pedido-texto');
        if (!manualAberto || textoTR.trim().length < 200) {
            if (area) area.value = 'Anexe o Termo de Referência acima: o sistema usa o texto dele para conferir a resposta da IA.';
            return;
        }
        try {
            const pedido = await postar('/minutas/ia/prompt', { ...basePedidoIA(), incluir_tr: incluirTR });
            pedidoManual = pedido.aplicavel ? pedido : { prompt: '', pendencias: 0 };
            if (area) area.value = pedidoManual.prompt || 'Não há pendências para a IA decidir.';
        } catch (err) {
            if (area) area.value = `Não foi possível preparar o pedido: ${err.message}`;
        }
    }

    async function copiarPedido() {
        if (!pedidoManual) await atualizarPedidoManual();
        if (!pedidoManual?.prompt) {
            setStatus(textoTR.trim().length < 200
                ? 'Anexe o Termo de Referência também aqui: o sistema usa o texto dele para conferir a resposta da IA.'
                : 'Não há pendências para a IA decidir.', textoTR.trim().length < 200 ? 'error' : 'success');
            return;
        }
        const ok = await copiarTexto(pedidoManual.prompt);
        setStatus(ok ? `Pedido copiado (${pedidoManual.pendencias} pendência(s)). Cole na sua IA${incluirTR ? '' : ' e anexe o PDF do TR'}.`
                     : 'Não foi possível copiar automaticamente: selecione o texto do pedido abaixo e use Ctrl+C.', ok ? 'success' : 'error');
    }

    async function aplicarRespostaManual() {
        const texto = respostaManual.trim();
        if (!texto) { setStatus('Cole a resposta da IA no campo antes de aplicar.', 'error'); return; }
        try {
            await aplicarResposta(basePedidoIA(), texto, `${ferramenta} (copiar e colar)`);
            respostaManual = '';
            if (ultimo) desenharResultado();
        } catch (err) {
            setStatus(err.message === 'Failed to fetch' ? 'Serviço de minutas indisponível.' : err.message, 'error');
        }
    }

    async function montar() {
        const m = modeloAtual();
        if (!m || montando) return;
        montando = true;
        montarBtn.disabled = true;
        setStatus('Montando minuta…', 'loading');
        try {
            const r = await fetch(`${MINUTAS}/minutas/montar`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ modelo_id: m.id, dados: dadosParaEnvio(), temas: temasMarcados(),
                                       respostas: respostasQuestionario(), decisoes }),
            });
            const corpo = await r.json();
            if (!r.ok) throw new Error(corpo.detail || 'Falha ao montar');
            ultimo = corpo;
            desenharResultado();
            const p = corpo.resumo.pendencias;
            const o = corpo.resumo.opcionais || 0;
            setStatus(p || o ? `Minuta montada. ${p} pendência(s) e ${o} cláusula(s) opcional(is) a confirmar.` : 'Minuta montada, sem pendências.', p || o ? '' : 'success');
        } catch (err) {
            setStatus(err.message === 'Failed to fetch' ? 'Serviço de minutas indisponível.' : err.message, 'error');
        } finally {
            montando = false;
            montarBtn.disabled = false;
        }
    }

    // ------------------------------------------------------------------
    // Decisões do servidor
    // ------------------------------------------------------------------

    function decidir(tipo, id, valor, motivo) {
        if (tipo === 'manter') {
            if (!decisoes.manter.includes(id)) decisoes.manter.push(id);
        } else {
            decisoes[tipo][id] = valor;
        }
        decisoes.origem[id] = 'servidor';
        if (motivo) decisoes.motivos[id] = motivo;
        montar();
    }

    function desfazer(id) {
        ['remover', 'textos', 'campos', 'motivos', 'origem'].forEach(k => {
            Object.keys(decisoes[k]).filter(c => c === id || c.startsWith(`${id}.`)).forEach(c => delete decisoes[k][c]);
        });
        decisoes.manter = decisoes.manter.filter(x => x !== id);
        montar();
    }

    // ------------------------------------------------------------------
    // Resultado
    // ------------------------------------------------------------------

    function blocoPorId(id) {
        return ultimo.blocos.find(b => b.id === id);
    }

    function notasHtml(bloco) {
        if (!bloco?.notas?.length) return '';
        return `<details class="minutas-nota"><summary>Nota explicativa da AGU</summary>
                    ${bloco.notas.map(n => `<p>${esc(n)}</p>`).join('')}</details>`;
    }

    function camposPendentes(bloco) {
        return (bloco.campos || []).filter(c => c.texto && bloco.texto.includes(c.texto));
    }

    function semInfoHtml(p) {
        const semInfo = iaInfo?.sem_informacao.find(x => x.bloco === p.bloco);
        const descartada = iaInfo?.descartes.find(x => x.bloco === p.bloco);
        return (semInfo ? `<span class="minutas-ia-dica">IA: ${esc(semInfo.motivo || 'o TR não permite decidir')}</span>` : '') +
               (descartada ? `<span class="minutas-ia-dica">IA descartada: ${esc(descartada.motivo)}</span>` : '');
    }

    function pendenciaHtml(p) {
        const b = blocoPorId(p.bloco);
        if (!b) return '';
        const ref = `<span class="minutas-num">${esc(p.numero || '—')}</span>`;
        let acoes = '';
        if (p.tipo === 'opcional') {
            return `<li class="minutas-opcional">
                    ${ref}<span class="minutas-opcional-texto">${esc(b.texto)}</span>
                    ${semInfoHtml(p)}
                    <span class="minutas-acoes">
                        <button type="button" class="conluio-btn-secondary" data-acao="manter" data-id="${b.id}">Manter</button>
                        <button type="button" class="conluio-btn-secondary" data-acao="remover" data-id="${b.id}">Remover</button>
                    </span>${notasHtml(b)}</li>`;
        }
        if (p.tipo === 'clausula') {
            acoes = `<button type="button" class="conluio-btn-secondary" data-acao="manter" data-id="${b.id}">Manter</button>
                     <button type="button" class="conluio-btn-secondary" data-acao="remover" data-id="${b.id}">Remover</button>`;
        } else if (p.tipo === 'alternativa') {
            const outro = blocoPorId(p.relacionado);
            acoes = `<div class="minutas-alternativa"><p class="conluio-modo">Outra redação:</p><p>${esc(outro?.texto || '')}</p></div>
                     <button type="button" class="conluio-btn-secondary" data-acao="ficar" data-id="${b.id}" data-outro="${esc(p.relacionado)}">Ficar com esta</button>
                     <button type="button" class="conluio-btn-secondary" data-acao="ficar" data-id="${esc(p.relacionado)}" data-outro="${b.id}">Ficar com a outra</button>`;
        } else if (p.tipo === 'campo' && camposPendentes(b).length) {
            const pendentes = camposPendentes(b);
            const lacunas = pendentes.filter(c => c.opcoes.length || LACUNA.test(c.texto));
            const trechos = pendentes.filter(c => !lacunas.includes(c));
            acoes = lacunas.map(c => c.opcoes.length
                ? `<label class="minutas-campo-inline"><span>${esc(c.texto)}</span>
                     <select class="conluio-input" data-preencher="${esc(c.id)}"><option value="">escolher…</option>
                     ${c.opcoes.map(o => `<option>${esc(o)}</option>`).join('')}</select></label>`
                : `<label class="minutas-campo-inline"><span>${esc(COM_MARCADOR.test(c.texto) ? c.texto : 'Valor sugerido pela AGU')}</span>
                     <input class="conluio-input" data-preencher="${esc(c.id)}" placeholder="preencher"
                        value="${COM_MARCADOR.test(c.texto) ? '' : esc(c.texto)}"></label>`).join('') +
                (lacunas.length ? `<button type="button" class="conluio-btn-secondary" data-acao="campos" data-id="${b.id}">Aplicar</button>` : '') +
                // Trecho vermelho sem lacuna ("Projeto Básico e Projeto Executivo"): adota-se ou não
                trechos.map(c => `<div class="minutas-trecho"><span>Trecho opcional: “${esc(c.texto)}”</span>
                     <button type="button" class="conluio-btn-secondary" data-acao="trecho" data-campo="${esc(c.id)}" data-manter="1">Manter trecho</button>
                     <button type="button" class="conluio-btn-secondary" data-acao="trecho" data-campo="${esc(c.id)}" data-manter="">Retirar trecho</button></div>`).join('') +
                `<button type="button" class="juntada-link-btn" data-acao="remover" data-id="${b.id}">Remover a cláusula</button>`;
        } else {
            acoes = `<textarea class="conluio-input" rows="3" data-texto="${b.id}">${esc(b.texto)}</textarea>
                     <button type="button" class="conluio-btn-secondary" data-acao="texto" data-id="${b.id}">Salvar texto</button>
                     <button type="button" class="juntada-link-btn" data-acao="remover" data-id="${b.id}">Remover a cláusula</button>`;
        }
        const semInfo = iaInfo?.sem_informacao.find(x => x.bloco === b.id || x.bloco === p.relacionado);
        const descartada = iaInfo?.descartes.find(x => x.bloco === b.id);
        return `<li class="minutas-pendencia">
                    <div class="minutas-pendencia-topo">${ref} <strong>${esc(p.descricao)}</strong></div>
                    ${semInfo ? `<p class="minutas-ia-dica">IA: ${esc(semInfo.motivo || 'o TR não permite decidir')}</p>` : ''}
                    ${descartada ? `<p class="minutas-ia-dica">Sugestão da IA descartada: ${esc(descartada.motivo)}</p>` : ''}
                    <p class="minutas-texto">${esc(b.texto)}</p>
                    ${notasHtml(b)}
                    <div class="minutas-acoes">${acoes}</div>
                </li>`;
    }

    function alteracoesHtml() {
        const alterados = ultimo.blocos.filter(b => b.situacao !== 'igual');
        const linhas = alterados.map(b => `
            <li class="minutas-alteracao${b.alterou_texto_fixo ? ' minutas-fixo' : ''}">
                <span class="minutas-num">${esc(b.numero || '—')}</span>
                <span class="juntada-situacao ${b.situacao === 'referencia' ? 'juntada-ok' : 'juntada-atencao'}">
                    ${b.situacao === 'referencia' ? 'Referência ajustada' : 'Alterado'}</span>
                ${b.origem ? `<span class="minutas-origem">${esc(ROTULO_ORIGEM[b.origem] || b.origem)}</span>` : ''}
                ${b.alterou_texto_fixo ? '<span class="juntada-situacao juntada-problema">Texto fixo da AGU alterado — justificar nos autos</span>' : ''}
                <div class="minutas-diff">
                    <p class="minutas-antes">${esc(b.texto_modelo)}</p>
                    <p class="minutas-depois">${esc(b.texto)}</p>
                </div>
                <p class="conluio-modo">${esc(b.referencias?.length ? `Numeração citada: ${b.referencias.join(', ')}` : b.motivo)}</p>
                ${['servidor', 'ia'].includes(b.origem) ? `<button type="button" class="juntada-link-btn" data-acao="desfazer" data-id="${b.id}">Desfazer</button>`
                  : b.origem === 'questionario' ? '<span class="conluio-modo">Para desfazer, mude a resposta no questionário.</span>' : ''}
            </li>`).join('');
        const removidos = ultimo.removidos.filter(r => r.texto.trim() && r.motivo !== 'Separador "OU" do modelo').map(r => `
            <li class="minutas-alteracao">
                <span class="minutas-num">${esc(r.numero_modelo ? `${r.numero_modelo} (modelo)` : '—')}</span>
                <span class="juntada-situacao juntada-faltando">Removido</span>
                <p class="minutas-antes">${esc(r.texto)}</p>
                <p class="conluio-modo">${esc(r.motivo)}</p>
                ${decisoes.remover[r.id] ? `<button type="button" class="juntada-link-btn" data-acao="desfazer" data-id="${r.id}">Desfazer</button>`
                  : r.motivo.startsWith('Questionário') ? `<button type="button" class="juntada-link-btn" data-acao="manter" data-id="${r.id}">Manter esta cláusula</button>` : ''}
            </li>`).join('');
        return { linhas, removidos, total: alterados.length };
    }

    function botaoIA() {
        const temChave = !!chaveGemini();
        const semTR = textoTR.trim().length < 200;
        const dica = semTR ? 'Anexe o Termo de Referência acima' : temChave ? 'O TR vai ao Gemini pela chave configurada' : '';
        return `<span class="minutas-ia-acao">
                ${temChave ? `<button type="button" class="conluio-btn-primary" id="minutas-ia" ${semTR ? 'disabled' : ''}>Sugerir com IA</button>` : ''}
                <button type="button" class="${temChave ? 'conluio-btn-secondary' : 'conluio-btn-primary'}" id="minutas-manual">
                    ${manualAberto ? 'Fechar “usar minha IA”' : 'Usar minha IA (copiar e colar)'}</button>
                ${dica ? `<span class="conluio-modo">${esc(dica)}</span>` : ''}</span>`;
    }

    function painelManualHtml() {
        if (!manualAberto) return '';
        const opcoes = ['ChatGPT', 'Claude', 'Gemini', 'Copilot', 'Outra'];
        return `<section class="minutas-secao minutas-manual">
            <h3>Usar a sua IA</h3>
            <p class="minutas-aviso-ia">Use apenas ferramentas de IA autorizadas pelo TRF1. Ferramentas gratuitas podem usar
               o conteúdo enviado para outros fins.</p>
            <ol>
                <li>Clique em <strong>Copiar pedido</strong>.</li>
                <li>Abra a IA que você usa, ${incluirTR ? '' : '<strong>anexe o PDF do Termo de Referência</strong> (e anexos) e '}cole o pedido.</li>
                <li>Copie a resposta inteira da IA e cole no campo abaixo. O sistema confere cada sugestão antes de aplicar.</li>
            </ol>
            <div class="minutas-manual-linha">
                <label class="minutas-campo-inline"><span>Ferramenta</span>
                    <select class="conluio-input" id="minutas-ferramenta">${opcoes.map(o =>
                        `<option${o === ferramenta ? ' selected' : ''}>${o}</option>`).join('')}</select></label>
                <label class="conluio-check"><input type="checkbox" id="minutas-incluir-tr"${incluirTR ? ' checked' : ''}>
                    Colar o texto do TR no pedido (para IA que não aceita anexo)</label>
                <button type="button" class="conluio-btn-secondary" id="minutas-copiar-pedido">Copiar pedido</button>
            </div>
            <details><summary>Ver o pedido</summary>
                <textarea class="conluio-input" id="minutas-pedido-texto" rows="6" readonly>Preparando o pedido…</textarea></details>
            <textarea class="conluio-input" id="minutas-resposta" rows="6"
                placeholder="Cole aqui a resposta da IA (pode colar tudo, inclusive o texto antes e depois do JSON)">${esc(respostaManual)}</textarea>
            <div class="conluio-actions">
                <button type="button" class="conluio-btn-primary" id="minutas-aplicar-resposta">Aplicar resposta</button>
            </div>
        </section>`;
    }

    function iaHtml() {
        if (!iaInfo) return '';
        const n = iaInfo.aplicadas.length;
        const semBase = iaInfo.descartes.filter(d => d.motivo.includes('fica para decisão do servidor'));
        const erros = iaInfo.descartes.filter(d => !semBase.includes(d));
        const ficaram = semBase.length + iaInfo.sem_informacao.length;
        const descartes = erros.map(d => `<li>${esc(d.numero || d.bloco || '—')}: ${esc(d.motivo)}</li>`).join('');
        return `<section class="minutas-secao minutas-ia">
            <h3>Sugestões da IA (${esc(iaInfo.modelo)})</h3>
            <p>${n} de ${iaInfo.pendencias_enviadas} pendência(s) resolvidas com base no TR — confira em
               “O que mudou” (origem IA, com o trecho do TR) e use Desfazer se discordar.
               ${ficaram ? `${ficaram} ficaram para você: o TR não traz trecho que permita decidir.` : ''}</p>
            ${descartes ? `<details><summary>${erros.length} sugestão(ões) recusada(s) na conferência</summary><ul>${descartes}</ul></details>` : ''}
            <p class="conluio-modo">A IA pode errar: a minuta continua sendo de responsabilidade de quem assina.</p>
        </section>`;
    }

    function desenharResultado() {
        const r = ultimo.resumo;
        const pend = ultimo.pendencias.filter(p => p.tipo !== 'opcional').map(pendenciaHtml).join('');
        const opcionais = ultimo.pendencias.filter(p => p.tipo === 'opcional');
        const alt = alteracoesHtml();
        resultadoDiv.innerHTML = `
            <div class="minutas-resumo">
                <span><strong>${r.iguais}</strong> blocos iguais ao modelo</span>
                <span><strong>${r.alterados}</strong> alterados</span>
                <span><strong>${r.referencias}</strong> referências ajustadas</span>
                <span><strong>${r.removidos}</strong> removidos</span>
                <span class="${r.pendencias ? 'minutas-alerta' : ''}"><strong>${r.pendencias}</strong> pendências</span>
                ${r.opcionais ? `<span class="minutas-alerta"><strong>${r.opcionais}</strong> cláusulas opcionais a confirmar</span>` : ''}
                ${r.texto_fixo_alterado ? `<span class="minutas-alerta"><strong>${r.texto_fixo_alterado}</strong> com texto fixo alterado</span>` : ''}
            </div>
            ${iaHtml()}
            ${r.pendencias || r.opcionais ? `<section class="minutas-secao">
                <div class="minutas-previa-topo"><h3>Pendências</h3>${botaoIA()}</div>
                ${painelManualHtml()}
                <ul class="minutas-lista">${pend}</ul></section>` : ''}
            ${opcionais.length ? `<section class="minutas-secao">
                <div class="minutas-previa-topo"><h3>Cláusulas opcionais do modelo da AGU (${opcionais.length})</h3>
                    <button type="button" class="conluio-btn-secondary" id="minutas-manter-todas">Manter todas as restantes</button></div>
                <p class="conluio-modo">A AGU marca estas cláusulas como opcionais: confirme as que se aplicam ao caso. Remover um item tira também os subitens.</p>
                <ul class="minutas-lista minutas-lista-compacta">${opcionais.map(pendenciaHtml).join('')}</ul></section>` : ''}
            <details class="minutas-secao"><summary><h3>O que mudou em relação ao modelo da AGU (${alt.total} alterados, ${r.removidos} removidos)</h3></summary>
                <ul class="minutas-lista">${alt.linhas}${alt.removidos}</ul></details>
            <section class="minutas-secao">
                <div class="minutas-previa-topo">
                    <h3>Minuta para o SEI</h3>
                    <button type="button" class="conluio-btn-primary" id="minutas-copiar">Copiar para o SEI</button>
                </div>
                <p class="conluio-modo">Cole com Ctrl+V no editor do SEI. A numeração vai escrita no texto; o que está em amarelo ainda está pendente.</p>
                <div class="minutas-previa">${ultimo.html_sei}</div>
            </section>`;

        resultadoDiv.querySelectorAll('[data-acao]').forEach(btn => btn.addEventListener('click', () => acao(btn)));
        resultadoDiv.querySelector('#minutas-copiar').addEventListener('click', copiar);
        resultadoDiv.querySelector('#minutas-ia')?.addEventListener('click', sugerirComIA);
        resultadoDiv.querySelector('#minutas-manual')?.addEventListener('click', () => { manualAberto = !manualAberto; desenharResultado(); });
        resultadoDiv.querySelector('#minutas-copiar-pedido')?.addEventListener('click', copiarPedido);
        resultadoDiv.querySelector('#minutas-aplicar-resposta')?.addEventListener('click', aplicarRespostaManual);
        resultadoDiv.querySelector('#minutas-resposta')?.addEventListener('input', e => { respostaManual = e.target.value; });
        resultadoDiv.querySelector('#minutas-incluir-tr')?.addEventListener('change', e => { incluirTR = e.target.checked; desenharResultado(); });
        if (manualAberto) atualizarPedidoManual();
        resultadoDiv.querySelector('#minutas-ferramenta')?.addEventListener('change', e => {
            ferramenta = e.target.value;
            try { localStorage.setItem('minutas.ferramenta', ferramenta); } catch { /* sem armazenamento */ }
        });
        resultadoDiv.querySelector('#minutas-manter-todas')?.addEventListener('click', () => {
            opcionais.forEach(p => {
                if (!decisoes.manter.includes(p.bloco)) decisoes.manter.push(p.bloco);
                decisoes.origem[p.bloco] = 'servidor';
                decisoes.motivos[p.bloco] = 'Cláusula opcional mantida pelo servidor';
            });
            montar();
        });
    }

    function acao(btn) {
        const id = btn.dataset.id;
        const item = btn.closest('li');
        switch (btn.dataset.acao) {
            case 'manter':
                return decidir('manter', id, true, 'Cláusula mantida pelo servidor');
            case 'remover':
                return decidir('remover', id, 'Removida pelo servidor: não se aplica ao caso');
            case 'ficar':
                return decidir('remover', btn.dataset.outro, 'Escolhida a outra redação alternativa');
            case 'desfazer':
                return desfazer(id);
            case 'trecho': {
                const cid = btn.dataset.campo;
                decisoes.campos[cid] = btn.dataset.manter ? MANTER_CAMPO : '';
                decisoes.origem[cid] = 'servidor';
                decisoes.motivos[cid] = btn.dataset.manter ? 'Trecho opcional mantido pelo servidor' : 'Trecho opcional retirado pelo servidor';
                return montar();
            }
            case 'texto': {
                const texto = item.querySelector(`[data-texto="${id}"]`).value.trim();
                if (texto) decidir('textos', id, texto, 'Texto ajustado pelo servidor');
                return;
            }
            case 'campos': {
                let algum = false;
                item.querySelectorAll('[data-preencher]').forEach(el => {
                    if (el.value.trim()) {
                        decisoes.campos[el.dataset.preencher] = el.value.trim();
                        decisoes.origem[el.dataset.preencher] = 'servidor';
                        decisoes.motivos[el.dataset.preencher] = 'Preenchido pelo servidor';
                        algum = true;
                    }
                });
                if (algum) montar();
                return;
            }
        }
    }

    function copiar() {
        const previa = resultadoDiv.querySelector('.minutas-previa');
        const selecao = window.getSelection();
        const faixa = document.createRange();
        faixa.selectNodeContents(previa);
        selecao.removeAllRanges();
        selecao.addRange(faixa);
        // execCommand funciona também sem HTTPS (o link interno do servidor é http)
        const ok = document.execCommand('copy');
        selecao.removeAllRanges();
        const p = ultimo.resumo.pendencias;
        if (ok) {
            setStatus(p ? `Copiado. Atenção: ${p} pendência(s) ainda marcadas em amarelo.` : 'Copiado. Cole no editor do SEI com Ctrl+V.', p ? '' : 'success');
        } else {
            setStatus('Não foi possível copiar automaticamente: selecione a minuta abaixo e use Ctrl+C.', 'error');
        }
    }

    // ------------------------------------------------------------------

    modeloSelect.addEventListener('change', () => {
        decisoes = decisoesVazias();   // decisões valem para um modelo só (os ids dos blocos mudam)
        ultimo = null;
        iaInfo = null;
        resultadoDiv.innerHTML = '';
        desenharFormulario();
    });
    montarBtn.addEventListener('click', montar);
    trInput.addEventListener('change', lerTR);

    carregarConfig().then(ok => {
        if (!ok) return;
        desenharFormulario();
        desenharUnidade();
    });
}
