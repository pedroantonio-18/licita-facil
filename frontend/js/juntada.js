/**
 * juntada.js
 * Juntada de documentos de habilitação.
 *
 * Fluxo:
 * 1. Servidor informa o processo e a data de referência (ex.: data da sessão)
 * 2. Para cada empresa, arrasta as certidões já emitidas (Receita, FGTS,
 *    Trabalhista, TCU, SICAF, falência…) — razão social e CNPJ são sugeridos
 * 3. O juntada-service confere CNPJ, validade e resultado de cada certidão
 *    e aponta o que falta
 * 4. Baixa os PDFs por bloco temático, como a SELIT junta no SEI
 *    (1 Habilitação Jurídica, 2 Regularidade — o SICAF, mais as avulsas que
 *    ele não cobre —, 3 Idoneidade, 4 Econômico-Financeira), e o relatório
 *    de conferência
 *
 * Tudo roda no servidor, sem internet. Receita, FGTS e Trabalhista têm
 * CAPTCHA: o servidor emite nos sites e o sistema confere.
 */

import { saveFile } from './db.js';
import { renderRecentFiles } from './recentFiles.js';

const JUNTADA = 'http://localhost:8002';

const PDF_ICON_SVG = `<svg class="file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>`;

const TRASH_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path><path d="M10 11v6"></path><path d="M14 11v6"></path><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path></svg>`;

const ROTULO_SITUACAO = { ok: 'OK', atencao: 'Conferir', problema: 'Problema', faltando: 'Faltando' };

// Links de emissão das certidões que só podem ser emitidas manualmente (CAPTCHA)
const LINKS_EMISSAO = [
    ['Receita Federal / PGFN', 'https://servicos.receitafederal.gov.br/servico/certidoes/#/home/cnpj'],
    ['FGTS (CRF)', 'https://consulta-crf.caixa.gov.br/consultacrf/pages/consultaEmpregador.jsf'],
    ['Trabalhista (CNDT)', 'https://cndt-certidao.tst.jus.br/inicio.faces'],
    ['TCU — Consulta Consolidada', 'https://certidoes-apf.apps.tcu.gov.br/'],
];

function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function esc(texto) {
    const div = document.createElement('div');
    div.textContent = texto ?? '';
    return div.innerHTML;
}

function dataBR(iso) {
    if (!iso) return '—';
    const [a, m, d] = iso.split('-');
    return `${d}/${m}/${a}`;
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

function nomeDoDownload(response, padrao) {
    const cd = response.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename="?([^"]+)"?/);
    return m ? m[1] : padrao;
}

export function initJuntada() {
    const section = document.getElementById('juntada');
    if (!section) return;

    let empresas = [];        // [{nome, cnpj, arquivos: [File], elemento, resultado}]
    let sessaoId = null;
    let config = null;

    const processoInput   = section.querySelector('#juntada-processo-id');
    const dataInput       = section.querySelector('#juntada-data-referencia');
    const obrigatoriasBox = section.querySelector('.juntada-obrigatorias');
    const objetoSelect    = section.querySelector('#juntada-objeto');
    const diasConsultas   = section.querySelector('#juntada-dias-consultas');
    const diasFalencia    = section.querySelector('#juntada-dias-falencia');
    const linksBox        = section.querySelector('.juntada-links');
    const empresasList    = section.querySelector('#juntada-empresas-lista');
    const addBtn          = section.querySelector('#juntada-add-empresa');
    const conferirBtn     = section.querySelector('#juntada-conferir');
    const statusMsg       = section.querySelector('.juntada-status');
    const resultados      = section.querySelector('.juntada-resultados');

    dataInput.value = new Date().toLocaleDateString('sv-SE');   // AAAA-MM-DD local
    linksBox.innerHTML = 'Emitir certidões: ' + LINKS_EMISSAO
        .map(([nome, url]) => `<a href="${url}" target="_blank" rel="noopener">${esc(nome)}</a>`).join(' · ');

    carregarConfig();

    processoInput.addEventListener('input', atualizarBotao);
    dataInput.addEventListener('input', atualizarBotao);
    addBtn.addEventListener('click', () => adicionarEmpresa());
    conferirBtn.addEventListener('click', () => conferirTodas());

    async function carregarConfig() {
        try {
            config = await jsonOuErro(fetch(`${JUNTADA}/juntada/config`), 'Configuração');
        } catch (erro) {
            setStatus(`${erro.message}. Verifique se o serviço de juntada está no ar.`, 'error');
            config = {
                tipos: [], objetos: {}, obrigatorias_por_objeto: {}, obrigatorias_padrao: [],
                dias_consultas_padrao: 30, dias_falencia_padrao: 30, consulta_tcu_ativa: false,
            };
        }
        diasConsultas.value = config.dias_consultas_padrao;
        diasFalencia.value = config.dias_falencia_padrao;
        objetoSelect.innerHTML = Object.entries(config.objetos)
            .map(([id, nome]) => `<option value="${esc(id)}">${esc(nome)}</option>`).join('');
        obrigatoriasBox.innerHTML = config.tipos.map(t => `
            <label class="conluio-check">
                <input type="checkbox" value="${esc(t.id)}" />
                ${esc(t.nome.split(' — ')[0].split(' (')[0])}
            </label>`).join('');
        marcarObrigatorias();
    }

    // Estadual para compra de bens, municipal para serviços (regra da SELIT);
    // o servidor ainda pode marcar ou desmarcar à mão
    function marcarObrigatorias() {
        const marcadas = config.obrigatorias_por_objeto?.[objetoSelect.value] || config.obrigatorias_padrao;
        obrigatoriasBox.querySelectorAll('input').forEach(i => { i.checked = marcadas.includes(i.value); });
    }
    objetoSelect.addEventListener('change', marcarObrigatorias);

    // ---------------------------------------------------------------------------
    // Empresas
    // ---------------------------------------------------------------------------

    function adicionarEmpresa() {
        const empresa = { nome: '', cnpj: '', arquivos: [], elemento: null, resultado: null };
        empresas.push(empresa);
        empresasList.querySelector('.conluio-hint')?.remove();

        const bloco = document.createElement('div');
        bloco.className = 'conluio-empresa-bloco';
        bloco.innerHTML = `
            <div class="empresa-bloco-header">
                <span class="empresa-bloco-titulo"></span>
                <button type="button" class="empresa-remover" title="Remover empresa">${TRASH_SVG}</button>
            </div>
            <input type="text" class="conluio-input juntada-empresa-nome" placeholder="Razão social da empresa" />
            <input type="text" class="conluio-input juntada-empresa-cnpj" placeholder="CNPJ (apenas dígitos)" />
            <div class="empresa-dropzone">
                <input type="file" class="juntada-file-input" accept=".pdf,application/pdf" multiple hidden />
                <p class="dropzone-text">Arraste as certidões aqui ou <span class="dropzone-link">clique para selecionar</span></p>
                <span class="dropzone-hint">Uma ou várias certidões por arquivo .pdf</span>
            </div>
            <ul class="empresa-arquivos-lista"></ul>
            <p class="empresa-status"></p>
        `;
        empresa.elemento = bloco;
        empresasList.appendChild(bloco);
        numerar();

        const nomeInput = bloco.querySelector('.juntada-empresa-nome');
        const cnpjInput = bloco.querySelector('.juntada-empresa-cnpj');
        const dropzone  = bloco.querySelector('.empresa-dropzone');
        const fileInput = bloco.querySelector('.juntada-file-input');

        nomeInput.addEventListener('input', e => { empresa.nome = e.target.value.trim(); atualizarBotao(); });
        cnpjInput.addEventListener('input', e => { empresa.cnpj = e.target.value.replace(/\D/g, ''); atualizarBotao(); });
        dropzone.addEventListener('click', () => fileInput.click());
        dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('drag-over'); });
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
        bloco.querySelector('.empresa-remover').addEventListener('click', () => {
            empresas = empresas.filter(e => e !== empresa);
            bloco.remove();
            if (!empresas.length) {
                empresasList.innerHTML = '<p class="conluio-hint">Nenhuma empresa adicionada ainda.</p>';
            }
            numerar();
            atualizarBotao();
        });
    }

    function numerar() {
        empresas.forEach((e, i) => {
            e.elemento.querySelector('.empresa-bloco-titulo').textContent = `Empresa ${i + 1}`;
        });
    }

    function adicionarArquivos(empresa, files) {
        const pdfs = files.filter(f => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'));
        if (!pdfs.length) return;
        empresa.arquivos.push(...pdfs);
        renderArquivos(empresa);
        atualizarBotao();
        if (!empresa.nome || !empresa.cnpj) identificar(empresa);
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
                renderArquivos(empresa);
                atualizarBotao();
            });
            lista.appendChild(li);
        });
    }

    async function identificar(empresa) {
        const form = new FormData();
        empresa.arquivos.forEach(f => form.append('arquivos', f, f.name));
        setStatusEmpresa(empresa, 'Lendo as certidões para sugerir razão social e CNPJ...', 'loading');
        try {
            const r = await jsonOuErro(fetch(`${JUNTADA}/juntada/identificar`, { method: 'POST', body: form }), 'Identificação');
            const preenchidos = [];
            if (r.razao_social && !empresa.nome) {
                empresa.nome = r.razao_social;
                empresa.elemento.querySelector('.juntada-empresa-nome').value = r.razao_social;
                preenchidos.push('razão social');
            }
            if (r.cnpj && !empresa.cnpj) {
                empresa.cnpj = r.cnpj;
                empresa.elemento.querySelector('.juntada-empresa-cnpj').value = r.cnpj;
                preenchidos.push('CNPJ');
            }
            setStatusEmpresa(empresa, preenchidos.length
                ? `Sugerido a partir das certidões: ${preenchidos.join(' e ')}. Confira antes de seguir.`
                : (r.cnpj ? '' : 'Não encontrei CNPJ no texto das certidões. Preencha manualmente.'),
                preenchidos.length ? 'success' : 'error');
        } catch (erro) {
            setStatusEmpresa(empresa, `${erro.message}. Preencha manualmente.`, 'error');
        }
        atualizarBotao();
    }

    function setStatusEmpresa(empresa, texto, tipo = '') {
        const el = empresa.elemento.querySelector('.empresa-status');
        el.textContent = texto;
        el.className = `empresa-status ${tipo}`;
    }

    function atualizarBotao() {
        conferirBtn.disabled = !(
            processoInput.value.trim() && dataInput.value && empresas.length &&
            empresas.every(e => e.nome && e.cnpj.length === 14 && e.arquivos.length)
        );
    }

    // ---------------------------------------------------------------------------
    // Conferência
    // ---------------------------------------------------------------------------

    function obrigatoriasMarcadas() {
        return [...obrigatoriasBox.querySelectorAll('input:checked')].map(i => i.value).join(',');
    }

    async function conferirTodas() {
        conferirBtn.disabled = true;
        resultados.innerHTML = '';
        sessaoId = null;
        try {
            for (let i = 0; i < empresas.length; i++) {
                const empresa = empresas[i];
                setStatus(`[${i + 1}/${empresas.length}] Conferindo as certidões de "${empresa.nome}"...`, 'loading');
                const form = new FormData();
                form.append('processo_id', processoInput.value.trim());
                form.append('data_referencia', dataInput.value);
                form.append('empresa_nome', empresa.nome);
                form.append('empresa_cnpj', empresa.cnpj);
                form.append('obrigatorias', obrigatoriasMarcadas());
                form.append('objeto', objetoSelect.value || 'compras');
                form.append('dias_consultas', diasConsultas.value || '30');
                form.append('dias_falencia', diasFalencia.value || '30');
                if (sessaoId) form.append('sessao_id', sessaoId);
                empresa.arquivos.forEach(f => form.append('arquivos', f, f.name));

                const r = await jsonOuErro(fetch(`${JUNTADA}/juntada/conferir`, { method: 'POST', body: form }), 'Conferência');
                sessaoId = r.sessao_id;
                empresa.resultado = r.empresa;
            }
            renderResultados();
            const comPendencia = empresas.filter(e => e.resultado.situacao !== 'ok').length;
            setStatus(comPendencia
                ? `Conferência concluída: ${comPendencia} empresa(s) com itens a verificar.`
                : 'Conferência concluída: todas as certidões obrigatórias estão regulares.', 'success');
        } catch (erro) {
            setStatus(`Erro: ${erro.message}`, 'error');
            console.error('[Juntada]', erro);
        } finally {
            atualizarBotao();
        }
    }

    function renderResultados() {
        resultados.innerHTML = `
            <div class="juntada-resultados-acoes">
                <h3 class="session-results-title">Resultado da conferência</h3>
                <button type="button" class="conluio-btn-secondary" id="juntada-relatorio">Baixar relatório de conferência</button>
            </div>`;
        resultados.querySelector('#juntada-relatorio').addEventListener('click', e => baixar(
            `${JUNTADA}/juntada/${sessaoId}/relatorio`, 'conferencia_certidoes.pdf', e.currentTarget));

        empresas.forEach(empresa => {
            const r = empresa.resultado;
            const card = document.createElement('div');
            card.className = 'juntada-card';
            const linhas = r.itens.map(item => {
                // Detalhes só do documento do próprio item (não do SICAF usado como referência)
                const doc = item.documentos.find(d => d.tipo === item.tipo && d.situacao === item.situacao)
                    || item.documentos.find(d => d.tipo === item.tipo);
                const obs = [...item.observacoes, ...(doc && item.fonte !== 'sicaf' ? doc.detalhes : [])];
                const acao = item.conferencia_manual
                    ? `<button type="button" class="juntada-link-btn juntada-desfazer" data-tipo="${esc(item.tipo)}">Desfazer</button>`
                    : item.situacao !== 'ok'
                        ? `<button type="button" class="juntada-link-btn juntada-manual" data-tipo="${esc(item.tipo)}">Marcar como conferido</button>`
                        : '';
                return `
                    <tr>
                        <td>${item.bloco}</td>
                        <td>${esc(item.tipo_nome.split(' — ')[0])}${item.obrigatoria ? '' : ' <span class="juntada-opcional">(complementar)</span>'}
                            ${item.fonte === 'sicaf' ? `<div class="juntada-opcional">${(item.situacao_automatica || item.situacao) === 'ok' ? 'comprovada pelo SICAF' : 'conforme o SICAF'}</div>` : ''}</td>
                        <td><span class="juntada-situacao juntada-${esc(item.situacao)}">${ROTULO_SITUACAO[item.situacao]}</span>
                            ${item.conferencia_manual ? '<div class="juntada-opcional">conferido pelo servidor</div>' : ''}
                            ${acao}</td>
                        <td>${dataBR(item.emissao)}</td>
                        <td>${dataBR(item.validade)}</td>
                        <td>${esc(item.resultado) || '—'}</td>
                        <td>${obs.map(o => `<div>${esc(o)}</div>`).join('') || '—'}</td>
                    </tr>`;
            }).join('');
            card.innerHTML = `
                <div class="juntada-card-header">
                    <div>
                        <strong>${esc(r.nome)}</strong>
                        <span class="juntada-cnpj">${esc(r.cnpj)}</span>
                    </div>
                    <span class="juntada-situacao juntada-${esc(r.situacao)}">${ROTULO_SITUACAO[r.situacao]}</span>
                </div>
                <div class="juntada-tabela-wrapper">
                    <table class="conluio-achados">
                        <thead><tr><th>Bloco</th><th>Documento</th><th>Situação</th><th>Emissão</th><th>Validade</th><th>Resultado</th><th>Observações</th></tr></thead>
                        <tbody>${linhas}</tbody>
                    </table>
                </div>
                <form class="juntada-form-manual" hidden>
                    <label class="conluio-label">Justificativa da conferência manual (aparece no relatório de conferência)</label>
                    <textarea class="conluio-input" rows="2" minlength="10" required
                        placeholder="Ex.: CNIA consultado diretamente no site do CNJ em 20/10/2026: nada consta."></textarea>
                    <div class="juntada-card-acoes">
                        <button type="submit" class="conluio-btn-primary">Confirmar</button>
                        <button type="button" class="conluio-btn-secondary juntada-cancelar">Cancelar</button>
                    </div>
                </form>
                <details class="juntada-arquivos">
                    <summary>${r.arquivos?.length || 0} arquivo(s) recebido(s)</summary>
                    <ul>${(r.arquivos || []).map(a => `<li>${esc(a.arquivo)} · ${a.paginas} pág. · <code>${esc(a.sha256.slice(0, 16))}…</code></li>`).join('')}</ul>
                </details>
                <div class="juntada-card-acoes">
                    ${(r.blocos || []).map(b => `<button type="button" class="conluio-btn-primary juntada-bloco" data-bloco="${b.numero}"
                        title="${b.documentos} documento(s)">Bloco ${b.numero} — ${esc(b.nome)}</button>`).join('')}
                    ${config?.consulta_tcu_ativa ? '<button type="button" class="conluio-btn-secondary juntada-tcu">Consultar TCU automaticamente</button>' : ''}
                </div>`;
            card.querySelectorAll('.juntada-bloco').forEach(btn => btn.addEventListener('click', e => baixar(
                `${JUNTADA}/juntada/${sessaoId}/bloco/${r.cnpj}/${btn.dataset.bloco}`,
                `bloco${btn.dataset.bloco}_${r.cnpj}.pdf`, e.currentTarget)));
            card.querySelector('.juntada-tcu')?.addEventListener('click', e => consultarTcu(empresa, e.currentTarget));

            const form = card.querySelector('.juntada-form-manual');
            card.querySelectorAll('.juntada-manual').forEach(btn => btn.addEventListener('click', () => {
                form.dataset.tipo = btn.dataset.tipo;
                form.hidden = false;
                form.querySelector('textarea').focus();
            }));
            form.querySelector('.juntada-cancelar').addEventListener('click', () => { form.hidden = true; });
            form.addEventListener('submit', e => {
                e.preventDefault();
                registrarManual(empresa, form.dataset.tipo, form.querySelector('textarea').value);
            });
            card.querySelectorAll('.juntada-desfazer').forEach(btn => btn.addEventListener('click',
                () => desfazerManual(empresa, btn.dataset.tipo)));
            resultados.appendChild(card);
        });
    }

    async function registrarManual(empresa, tipo, justificativa) {
        const form = new FormData();
        form.append('empresa_cnpj', empresa.cnpj);
        form.append('tipo', tipo);
        form.append('justificativa', justificativa);
        try {
            const r = await jsonOuErro(fetch(`${JUNTADA}/juntada/${sessaoId}/manual`, { method: 'POST', body: form }), 'Conferência manual');
            empresa.resultado = r.empresa;
            renderResultados();
            setStatus(`Conferência manual registrada para "${empresa.nome}". Baixe o relatório de conferência atualizado.`, 'success');
        } catch (erro) {
            setStatus(`Erro: ${erro.message}`, 'error');
        }
    }

    async function desfazerManual(empresa, tipo) {
        try {
            const r = await jsonOuErro(fetch(`${JUNTADA}/juntada/${sessaoId}/manual/${empresa.cnpj}/${encodeURIComponent(tipo)}`,
                { method: 'DELETE' }), 'Conferência manual');
            empresa.resultado = r.empresa;
            renderResultados();
            setStatus(`Conferência manual desfeita para "${empresa.nome}".`, 'success');
        } catch (erro) {
            setStatus(`Erro: ${erro.message}`, 'error');
        }
    }

    async function consultarTcu(empresa, botao) {
        botao.disabled = true;
        setStatus(`Consultando o TCU para "${empresa.nome}"...`, 'loading');
        try {
            const form = new FormData();
            form.append('empresa_cnpj', empresa.cnpj);
            const r = await jsonOuErro(fetch(`${JUNTADA}/juntada/${sessaoId}/tcu`, { method: 'POST', body: form }), 'Consulta TCU');
            empresa.resultado = r.empresa;
            renderResultados();
            setStatus(`Consulta do TCU acrescentada às certidões de "${empresa.nome}".`, 'success');
        } catch (erro) {
            setStatus(`Erro: ${erro.message}`, 'error');
            botao.disabled = false;
        }
    }

    async function baixar(url, padrao, botao) {
        botao.disabled = true;
        try {
            let response;
            try {
                response = await fetch(url);
            } catch {
                throw new Error(`serviço de juntada indisponível em ${JUNTADA}`);
            }
            if (!response.ok) throw new Error(await response.text());
            const blob = await response.blob();
            const nome = nomeDoDownload(response, padrao);
            await saveFile({ name: nome, blob, mimeType: 'application/pdf', size: blob.size, source: 'juntada' });
            renderRecentFiles();
            downloadBlob(blob, nome);
        } catch (erro) {
            setStatus(`Erro ao gerar o PDF: ${erro.message}`, 'error');
        } finally {
            botao.disabled = false;
        }
    }

    function setStatus(texto, tipo = '') {
        statusMsg.textContent = texto;
        statusMsg.className = `conluio-status juntada-status ${tipo}`;
    }

    async function jsonOuErro(promessa, etapa) {
        let response;
        try {
            response = await promessa;
        } catch {
            throw new Error(`${etapa}: serviço de juntada indisponível em ${JUNTADA}`);
        }
        if (!response.ok) {
            let detalhe = await response.text();
            try { detalhe = JSON.parse(detalhe).detail || detalhe; } catch { /* texto puro */ }
            throw new Error(`${etapa}: ${detalhe}`);
        }
        return response.json();
    }
}
