/**
 * enquadramento.js
 * Estimativa e enquadramento da despesa — a "Informação" que a SELIT junta no SEI.
 *
 * Fluxo:
 * 1. Servidor informa a natureza (bem, serviço, engenharia…), o exercício, os itens com o
 *    valor estimado (vindo da pesquisa de preços) e as demandas semelhantes do PCA
 * 2. O enquadramento-service calcula: dispensa (art. 75, I ou II) ou pregão, soma do
 *    exercício contra o limite (fracionamento), ME/EPP (R$ 80 mil por item), 20% da
 *    Seguridade Social e o valor por extenso
 * 3. Monta o texto da Informação na redação dos textos padrão da SJGO-SECOP; o que faltar
 *    informar vai entre colchetes, em amarelo
 * 4. "Copiar para o SEI" (Times 12, formatação direta — mesmo formato das minutas)
 */

const ENQUADRAMENTO = 'http://localhost:8004';
const CHAVE_ASSINATURA = 'enquadramento.assinatura';

const ROTULO_MODALIDADE = { dispensa: 'Dispensa de licitação', pregao: 'Pregão eletrônico', concorrencia: 'Concorrência' };

function esc(texto) {
    const div = document.createElement('div');
    div.textContent = texto ?? '';
    return div.innerHTML;
}

function lerLocal() {
    try { return JSON.parse(localStorage.getItem(CHAVE_ASSINATURA) || '{}'); } catch { return {}; }
}

function salvarLocal(dados) {
    try { localStorage.setItem(CHAVE_ASSINATURA, JSON.stringify(dados)); } catch { /* sem armazenamento */ }
}

function campo(chave, rotulo, controle, largo = false) {
    return `<label class="minutas-campo${largo ? ' minutas-campo-largo' : ''}" for="enq-${chave}">
                <span class="conluio-label">${esc(rotulo)}</span>${controle}</label>`;
}

const texto = (chave, ph = '', valor = '') =>
    `<input id="enq-${chave}" data-enq="${chave}" class="conluio-input" placeholder="${esc(ph)}" value="${esc(valor)}">`;

const selecao = (chave, opcoes, valor = '') =>
    `<select id="enq-${chave}" data-enq="${chave}" class="conluio-input">${opcoes.map(([v, r]) =>
        `<option value="${esc(v)}"${v === valor ? ' selected' : ''}>${esc(r)}</option>`).join('')}</select>`;

async function copiarTextoEnq(texto) {
    try {
        if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(texto); return true; }
    } catch { /* método antigo */ }
    const area = document.createElement('textarea');
    area.value = texto; area.style.position = 'fixed'; area.style.opacity = '0';
    document.body.appendChild(area); area.select();
    const ok = document.execCommand('copy'); area.remove();
    return ok;
}

export function initEnquadramento() {
    const section = document.getElementById('enquadramento');
    if (!section) return;

    const form = section.querySelector('.enq-form');
    const gerarBtn = section.querySelector('#enq-gerar');
    const statusEl = section.querySelector('.enq-status');
    const resultadoDiv = section.querySelector('.enq-resultado');
    let config = null;
    let ultimo = null;
    let gerado = false;
    let timer = null;

    function copiarPedidoPCA() { return copiarTextoEnq(config.pedido_ia_pca || ''); }

    function setStatus(msg, tipo = '') {
        statusEl.textContent = msg;
        statusEl.className = `conluio-status enq-status ${tipo}`;
    }

    // ------------------------------------------------------------------
    // Formulário
    // ------------------------------------------------------------------

    function linhaItem(item = {}) {
        return `<tr><td><input class="conluio-input" data-col="descricao" placeholder="Descrição do item" value="${esc(item.descricao || '')}"></td>
                    <td><input class="conluio-input enq-valor" data-col="valor" placeholder="0,00" value="${esc(item.valor || '')}"></td>
                    <td><label class="conluio-check" title="Bem divisível (ex.: 100 cadeiras): acima de R$ 80 mil tem cota reservada para ME/EPP">
                        <input type="checkbox" data-col="divisivel"${item.divisivel ? ' checked' : ''}> divisível</label></td>
                    <td><button type="button" class="juntada-link-btn" data-remover-linha>remover</button></td></tr>`;
    }

    function linhaDemanda(d = {}) {
        return `<tr><td><input class="conluio-input" data-col="descricao" placeholder="Ex.: SETMAT_0005, garrafa 500 ml" value="${esc(d.descricao || '')}"></td>
                    <td><input class="conluio-input" data-col="origem" placeholder="Ex.: Dispensa (art. 75, II) / NE 2026NE000318" value="${esc(d.origem || '')}"></td>
                    <td><input class="conluio-input enq-valor" data-col="valor" placeholder="0,00" value="${esc(d.valor || '')}"></td>
                    <td><select class="conluio-input" data-col="tipo">
                        <option value="pca">Demanda semelhante no PCA</option>
                        <option value="contratada">Já contratada no exercício</option>
                        <option value="propria">É esta própria demanda (não soma)</option></select></td>
                    <td><button type="button" class="juntada-link-btn" data-remover-linha>remover</button></td></tr>`;
    }

    function desenharFormulario() {
        const ano = String(new Date().getFullYear());
        const anos = [...new Set([...Object.keys(config.limites), ano, String(+ano + 1)])].sort();
        const assinatura = lerLocal();
        form.innerHTML = `
            <fieldset class="minutas-grupo">
                <legend>Objeto e enquadramento</legend>
                <div class="minutas-campos">
                    ${campo('natureza', 'Natureza do objeto', selecao('natureza', Object.entries(config.naturezas), 'bem'))}
                    ${campo('exercicio', 'Exercício (PCA)', selecao('exercicio', anos.map(a => [a, a]), ano))}
                    ${campo('objeto', 'Objeto, como na Informação (“aquisição de…”, “contratação de…”)',
                        `<textarea id="enq-objeto" data-enq="objeto" class="conluio-input" rows="2" placeholder="aquisição de materiais elétricos, destinados a ..."></textarea>`, true)}
                    ${campo('doc_referencia', 'Documento de referência', texto('doc_referencia', 'Estudo Técnico Preliminar - ETP Completo 00000000'))}
                    ${campo('destinatarios', 'Destinatários', texto('destinatarios', '', 'Senhor Supervisor da Seplo e Senhora Supervisora da Secon,'))}
                </div>
                <label class="conluio-check"><input type="checkbox" data-enq="forcar_licitacao"> Licitar mesmo abaixo do limite da dispensa</label>
                <p class="conluio-modo enq-limite"></p>
            </fieldset>

            <fieldset class="minutas-grupo">
                <legend>Itens e valor estimado</legend>
                <p class="conluio-modo">Um item por linha, com o valor total estimado (da pesquisa de preços). A regra de ME/EPP é por item (R$ ${esc(config.limite_me_epp)}).</p>
                <table class="enq-tabela enq-itens"><thead><tr><th>Descrição</th><th>Valor total (R$)</th><th>Natureza</th><th></th></tr></thead>
                    <tbody>${linhaItem()}</tbody></table>
                <button type="button" class="conluio-btn-secondary" data-nova-linha="itens">+ Item</button>
                <label class="conluio-check"><input type="checkbox" data-enq="grupo_unico"> Julgamento em grupo/lote único (ME/EPP pelo valor do grupo)</label>
            </fieldset>

            <fieldset class="minutas-grupo">
                <legend>Pesquisa de preços</legend>
                <div class="minutas-campos">
                    ${campo('fonte', 'Origem da estimativa', selecao('fonte', [['banco_precos', 'Relatório Banco de Preços'], ['seeng', 'Planilha da SEENG (engenharia)']]))}
                    ${campo('relatorio', 'Nº SEI do relatório / planilha', texto('relatorio', '00000000'))}
                    ${campo('metodologia', 'Metodologia', selecao('metodologia', Object.entries(config.metodologias)))}
                    ${campo('base_seeng', 'Base da SEENG', selecao('base_seeng', [['tabelas_oficiais', 'Tabelas oficiais (SINAPI, AGETOP…)'], ['contratacoes_similares', 'Contratações similares (art. 23, § 2º, III)']]))}
                    ${campo('info_conclusiva', 'Nº SEI da informação conclusiva (pregão)', texto('info_conclusiva', 'opcional'))}
                </div>
                <span class="conluio-label">Incisos do art. 5º da IN SEGES/ME nº 65/2021 usados</span>
                <div class="minutas-temas">${['I', 'II', 'III', 'IV', 'V', 'VI'].map(i =>
                    `<label class="conluio-check"><input type="checkbox" data-inciso="${i}"${i === 'II' ? ' checked' : ''}> ${i}</label>`).join('')}</div>
            </fieldset>

            <fieldset class="minutas-grupo">
                <legend>PCA e contratações do exercício (fracionamento)</legend>
                <p class="conluio-modo">Demandas semelhantes do PCA (mesmo PDM para materiais; mesma descrição para serviços — art. 4º da IN 67/2021)
                   e o que já foi contratado no exercício. Deixe em branco se não houver.</p>
                <div class="enq-pca">
                    <p class="conluio-modo enq-pca-situacao"></p>
                    <div class="minutas-manual-linha">
                        <label class="conluio-btn-secondary enq-pca-arquivo">Carregar o PDF do PCA deste exercício
                            <input type="file" accept=".pdf,application/pdf" hidden></label>
                        <button type="button" class="conluio-btn-primary" data-pca-buscar>Procurar demandas semelhantes no PCA</button>
                    </div>
                    <details class="enq-pca-lista"><summary>PCA com a tabela em imagem? Importar a lista com a sua IA</summary>
                        <p class="minutas-aviso-ia">Use apenas ferramentas de IA autorizadas pelo TRF1. O PCA é público, mas tem nomes de servidores.</p>
                        <p class="conluio-modo">Copie o pedido, anexe o PDF do PCA na sua IA, cole o pedido e depois cole a resposta abaixo.</p>
                        <button type="button" class="conluio-btn-secondary" data-pca-copiar>Copiar pedido</button>
                        <textarea class="conluio-input" rows="4" data-pca-resposta placeholder="Cole aqui a resposta da IA (lista de demandas)"></textarea>
                        <button type="button" class="conluio-btn-secondary" data-pca-importar>Importar lista</button>
                    </details>
                    <div class="enq-pca-sugestoes"></div>
                </div>
                ${campo('pca_referencia', 'Referência do PCA consultado', texto('pca_referencia', 'PCA 2026 (00000000)'))}
                <table class="enq-tabela enq-demandas"><thead><tr><th>Demanda</th><th>Origem</th><th>Valor (R$)</th><th>Tipo</th><th></th></tr></thead>
                    <tbody></tbody></table>
                <button type="button" class="conluio-btn-secondary" data-nova-linha="demandas">+ Demanda</button>
            </fieldset>

            <fieldset class="minutas-grupo">
                <legend>ME/EPP, registro de preços e pedidos</legend>
                <div class="minutas-campos">
                    ${campo('me_epp_dispensa', 'ME/EPP na dispensa', selecao('me_epp_dispensa', [['exclusiva', 'Exclusiva para ME/EPP'], ['preferencial', 'Preferencialmente para ME/EPP']]))}
                    ${campo('ref_comum', 'Pregão: onde o TR/ETP define o objeto como comum', texto('ref_comum', 'item D do ETP Completo 00000000'))}
                    ${campo('encerramento', 'Encerramento', selecao('encerramento', [['Respeitosamente,', 'Respeitosamente,'], ['À consideração.', 'À consideração.']]))}
                </div>
                <label class="conluio-check"><input type="checkbox" data-enq="incluir_seguridade" checked> Informar 20% da Seguridade Social (dispensa)</label>
                <label class="conluio-check"><input type="checkbox" data-enq="pedir_tr" checked> Pedir à Secon a elaboração do Termo de Referência</label>
            </fieldset>

            <details class="minutas-grupo minutas-jf">
                <summary>Assinatura</summary>
                <div class="minutas-campos-jf">
                    ${campo('servidor', 'Servidor', texto('servidor', '', assinatura.servidor || ''))}
                    ${campo('cargo_servidor', 'Cargo – matrícula', texto('cargo_servidor', 'Técnico Judiciário – GO00000', assinatura.cargo_servidor || ''))}
                    ${campo('supervisor', 'Supervisor(a)', texto('supervisor', '', assinatura.supervisor || ''))}
                    ${campo('cargo_supervisor', 'Cargo', texto('cargo_supervisor', 'Supervisor da Secop', assinatura.cargo_supervisor || ''))}
                </div>
                <p class="conluio-modo">Ficam salvos neste navegador.</p>
            </details>`;
        atualizarLimite();
        alternarCampos();
        atualizarPCA();
        form.querySelector('.enq-pca-arquivo input').addEventListener('change', enviarPCA);
    }

    function anoAtual() { return form.querySelector('[data-enq="exercicio"]').value; }

    function atualizarPCA() {
        const info = config.pca?.[anoAtual()];
        form.querySelector('.enq-pca-situacao').textContent = info
            ? `PCA ${anoAtual()} carregado: ${info.demandas} demandas (${info.origem}).`
            : `PCA ${anoAtual()} ainda não carregado. Baixe o PDF no portal da SJGO (Plano Anual de Contratações) e carregue aqui.`;
        form.querySelector('[data-pca-buscar]').disabled = !info;
    }

    async function recarregarConfig() {
        try { config = await (await fetch(`${ENQUADRAMENTO}/enquadramento/config`)).json(); } catch { /* mantém a anterior */ }
        atualizarPCA();
    }

    async function enviarPCA(e) {
        const arquivo = e.target.files[0];
        if (!arquivo) return;
        const fd = new FormData(); fd.append('arquivo', arquivo);
        setStatus('Lendo o PCA…', 'loading');
        try {
            const r = await fetch(`${ENQUADRAMENTO}/enquadramento/pca/${anoAtual()}`, { method: 'POST', body: fd });
            const corpo = await r.json();
            if (!r.ok) throw new Error(corpo.detail || 'Falha ao ler o PCA');
            if (corpo.em_imagem) {
                form.querySelector('.enq-pca-lista').open = true;
                setStatus('A tabela deste PCA está em imagem: importe a lista com a sua IA (abaixo) ou digite as demandas.', 'error');
            } else {
                setStatus(`PCA ${anoAtual()} carregado: ${corpo.demandas} demandas.`, 'success');
            }
            await recarregarConfig();
        } catch (err) {
            setStatus(err.message === 'Failed to fetch' ? 'Serviço de enquadramento indisponível.' : err.message, 'error');
        }
        e.target.value = '';
    }

    async function importarListaPCA() {
        const resposta = form.querySelector('[data-pca-resposta]').value.trim();
        if (!resposta) { setStatus('Cole a resposta da IA antes de importar.', 'error'); return; }
        try {
            const r = await fetch(`${ENQUADRAMENTO}/enquadramento/pca/${anoAtual()}/lista`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ resposta }) });
            const corpo = await r.json();
            if (!r.ok) throw new Error(corpo.detail || 'Falha ao importar');
            setStatus(`PCA ${anoAtual()} carregado: ${corpo.demandas} demandas. Confira por amostragem com o PDF.`, 'success');
            await recarregarConfig();
        } catch (err) {
            setStatus(err.message === 'Failed to fetch' ? 'Serviço de enquadramento indisponível.' : err.message, 'error');
        }
    }

    async function buscarPCA() {
        const objeto = form.querySelector('[data-enq="objeto"]').value.trim();
        const alvo = form.querySelector('.enq-pca-sugestoes');
        if (!objeto) { setStatus('Preencha o objeto antes de procurar no PCA.', 'error'); return; }
        try {
            const r = await fetch(`${ENQUADRAMENTO}/enquadramento/pca/${anoAtual()}/buscar`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ objeto }) });
            const corpo = await r.json();
            if (!r.ok) throw new Error(corpo.detail || 'Falha na busca');
            alvo.innerHTML = corpo.sugestoes.length ? `
                <p class="conluio-modo">Demandas do PCA com descrição parecida (palavras em comum). Confira se são da mesma natureza
                   (mesmo PDM para materiais; mesma descrição para serviços) antes de somar.</p>
                <ul class="minutas-lista minutas-lista-compacta">${corpo.sugestoes.map((d, n) => `
                    <li class="minutas-opcional">
                        <span class="minutas-num">${esc(d.semelhanca)}%</span>
                        <span class="minutas-opcional-texto"><strong>${esc(d.id)}</strong> — ${esc(d.descricao.slice(0, 220))}
                            <br><span class="conluio-modo">${esc(d.forma)} · ${esc(d.tipo)} · desembolso R$ ${esc(d.desembolso || '—')}</span></span>
                        <span class="minutas-acoes">
                            <button type="button" class="conluio-btn-secondary" data-pca-somar="${n}" data-tipo="pca">Somar</button>
                            <button type="button" class="conluio-btn-secondary" data-pca-somar="${n}" data-tipo="propria">É esta demanda</button>
                        </span></li>`).join('')}</ul>`
                : `<p class="conluio-modo">Nenhuma demanda parecida no PCA ${esc(anoAtual())} (${corpo.total} demandas). Se houver, inclua à mão.</p>`;
            alvo._sugestoes = corpo.sugestoes;
        } catch (err) {
            setStatus(err.message === 'Failed to fetch' ? 'Serviço de enquadramento indisponível.' : err.message, 'error');
        }
    }

    function somarDemanda(btn) {
        const d = form.querySelector('.enq-pca-sugestoes')._sugestoes[+btn.dataset.pcaSomar];
        const tbody = form.querySelector('.enq-demandas tbody');
        tbody.insertAdjacentHTML('beforeend', linhaDemanda({
            descricao: `${d.id}, ${d.descricao.slice(0, 80)}`, origem: d.forma === '-' ? d.tipo : d.forma, valor: d.desembolso || d.valor_total }));
        tbody.lastElementChild.querySelector('[data-col="tipo"]').value = btn.dataset.tipo;
        btn.closest('li').remove();
        if (!form.querySelector('[data-enq="pca_referencia"]').value) form.querySelector('[data-enq="pca_referencia"]').value = `PCA ${anoAtual()}`;
        agendar();
    }

    function atualizarLimite() {
        const ano = form.querySelector('[data-enq="exercicio"]').value;
        const natureza = form.querySelector('[data-enq="natureza"]').value;
        const conhecidos = Object.keys(config.limites).sort();
        const usado = config.limites[ano] ? ano : conhecidos.filter(a => a < ano).pop();
        const lim = config.limites[usado];
        const inciso = ['servico_engenharia', 'manutencao_veiculos', 'obra'].includes(natureza) ? 'I' : 'II';
        form.querySelector('.enq-limite').textContent = lim
            ? `Limite da dispensa (art. 75, inciso ${inciso}): R$ ${lim[inciso]} — ${lim.decreto}${usado !== ano ? ` (último publicado, de ${usado})` : ''}${lim[`confirmado_${inciso}`] === false ? ' — valor a confirmar com a SELIT' : ''}.`
            : 'Limite da dispensa não cadastrado para este exercício.';
    }

    function alternarCampos() {
        const seeng = form.querySelector('[data-enq="fonte"]').value === 'seeng';
        form.querySelector('#enq-base_seeng').closest('label').hidden = !seeng;
        form.querySelector('#enq-metodologia').closest('label').hidden = seeng;
    }

    function lerTabela(classe, mapa) {
        return [...form.querySelectorAll(`.${classe} tbody tr`)].map(tr => {
            const linha = {};
            tr.querySelectorAll('[data-col]').forEach(el => { linha[el.dataset.col] = el.type === 'checkbox' ? el.checked : el.value.trim(); });
            return mapa(linha);
        }).filter(l => l.valor);
    }

    function pedido() {
        const v = k => form.querySelector(`[data-enq="${k}"]`);
        const dados = {};
        ['objeto', 'doc_referencia', 'destinatarios', 'fonte', 'relatorio', 'metodologia', 'base_seeng', 'info_conclusiva',
         'pca_referencia', 'me_epp_dispensa', 'ref_comum', 'encerramento', 'servidor', 'cargo_servidor', 'supervisor',
         'cargo_supervisor'].forEach(k => { dados[k] = v(k).value.trim(); });
        dados.incluir_seguridade = v('incluir_seguridade').checked;
        dados.pedir_tr = v('pedir_tr').checked;
        dados.incisos_in65 = [...form.querySelectorAll('[data-inciso]:checked')].map(el => el.dataset.inciso);
        salvarLocal({ servidor: dados.servidor, cargo_servidor: dados.cargo_servidor, supervisor: dados.supervisor,
                      cargo_supervisor: dados.cargo_supervisor });
        return {
            natureza: v('natureza').value, exercicio: v('exercicio').value, forcar_licitacao: v('forcar_licitacao').checked,
            grupo_unico: v('grupo_unico').checked,
            itens: lerTabela('enq-itens', l => ({ descricao: l.descricao, valor: l.valor, divisivel: !!l.divisivel })),
            demandas: lerTabela('enq-demandas', l => ({ descricao: l.descricao, origem: l.origem, valor: l.valor,
                                                        ja_contratada: l.tipo === 'contratada', propria: l.tipo === 'propria' })),
            dados,
        };
    }

    // ------------------------------------------------------------------
    // Servidor
    // ------------------------------------------------------------------

    async function gerar() {
        const p = pedido();
        if (!p.itens.length) { setStatus('Informe ao menos um item com o valor estimado.', 'error'); return; }
        gerarBtn.disabled = true;
        setStatus('Gerando…', 'loading');
        try {
            const r = await fetch(`${ENQUADRAMENTO}/enquadramento/gerar`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p),
            });
            const corpo = await r.json();
            if (!r.ok) throw new Error(corpo.detail || 'Falha ao gerar');
            ultimo = corpo;
            gerado = true;
            desenharResultado();
            setStatus(corpo.pendencias ? `Informação gerada. ${corpo.pendencias} campo(s) a informar (em amarelo).` : 'Informação gerada.',
                      corpo.pendencias ? '' : 'success');
        } catch (err) {
            setStatus(err.message === 'Failed to fetch' ? 'Serviço de enquadramento indisponível (porta 8004).' : err.message, 'error');
        } finally {
            gerarBtn.disabled = false;
        }
    }

    function desenharResultado() {
        const e = ultimo.enquadramento;
        const me = e.me_epp.regra === 'exclusiva' ? 'Exclusiva para ME/EPP (itens até R$ 80 mil)'
            : e.me_epp.regra === 'ampla' ? 'Ampla participação (itens acima de R$ 80 mil)'
            : `Por item: ${e.me_epp.exclusivos.length} exclusivo(s), ${(e.me_epp.cotas || []).length} com cota reservada, ${e.me_epp.amplos.length + (e.me_epp.sem_beneficio || []).length} ampla(s)`;
        resultadoDiv.innerHTML = `
            <div class="enq-cartao enq-${esc(e.modalidade)}">
                <div class="enq-modalidade">${esc(ROTULO_MODALIDADE[e.modalidade] || e.modalidade)}${e.modalidade === 'dispensa' ? ` — art. 75, inciso ${esc(e.inciso)}` : ''}</div>
                <div class="enq-numeros">
                    <span>Valor estimado <strong>R$ ${esc(e.valor_estimado)}</strong></span>
                    <span>Soma do exercício <strong>R$ ${esc(e.soma_exercicio)}</strong></span>
                    <span>Limite da dispensa <strong>R$ ${esc(e.limite)}</strong></span>
                    <span>ME/EPP <strong>${esc(me)}</strong></span>
                    ${e.seguridade ? `<span>20% Seguridade <strong>R$ ${esc(e.seguridade)}</strong></span>` : ''}
                </div>
                ${ultimo.avisos.length ? `<ul class="enq-avisos">${ultimo.avisos.map(a => `<li>${esc(a)}</li>`).join('')}</ul>` : ''}
            </div>
            <section class="minutas-secao">
                <div class="minutas-previa-topo">
                    <h3>Informação para o SEI</h3>
                    <button type="button" class="conluio-btn-primary" id="enq-copiar">Copiar para o SEI</button>
                </div>
                <p class="conluio-modo">Cole com Ctrl+V no documento “Informação” do SEI. O que estiver em amarelo ainda precisa ser informado.</p>
                <div class="minutas-previa">${ultimo.html_sei}</div>
            </section>`;
        resultadoDiv.querySelector('#enq-copiar').addEventListener('click', copiar);
    }

    function copiar() {
        const previa = resultadoDiv.querySelector('.minutas-previa');
        const selecao = window.getSelection();
        const faixa = document.createRange();
        faixa.selectNodeContents(previa);
        selecao.removeAllRanges();
        selecao.addRange(faixa);
        const ok = document.execCommand('copy');      // funciona também sem HTTPS
        selecao.removeAllRanges();
        if (!ok) { setStatus('Não foi possível copiar: selecione o texto abaixo e use Ctrl+C.', 'error'); return; }
        setStatus(ultimo.pendencias ? `Copiado. Atenção: ${ultimo.pendencias} campo(s) em amarelo a informar.` : 'Copiado. Cole no SEI com Ctrl+V.',
                  ultimo.pendencias ? '' : 'success');
    }

    // ------------------------------------------------------------------

    form.addEventListener('click', ev => {
        const nova = ev.target.closest('[data-nova-linha]');
        if (nova) {
            const tbody = form.querySelector(nova.dataset.novaLinha === 'itens' ? '.enq-itens tbody' : '.enq-demandas tbody');
            tbody.insertAdjacentHTML('beforeend', nova.dataset.novaLinha === 'itens' ? linhaItem() : linhaDemanda());
        }
        if (ev.target.closest('[data-pca-buscar]')) buscarPCA();
        if (ev.target.closest('[data-pca-importar]')) importarListaPCA();
        if (ev.target.closest('[data-pca-somar]')) somarDemanda(ev.target.closest('[data-pca-somar]'));
        if (ev.target.closest('[data-pca-copiar]')) {
            copiarPedidoPCA().then(ok => setStatus(ok ? 'Pedido copiado. Cole na sua IA e anexe o PDF do PCA.' : 'Não foi possível copiar.', ok ? 'success' : 'error'));
        }
        const remover = ev.target.closest('[data-remover-linha]');
        if (remover) {
            remover.closest('tr').remove();
            agendar();
        }
    });
    form.addEventListener('change', ev => {
        if (ev.target.matches('[data-enq="exercicio"], [data-enq="natureza"]')) atualizarLimite();
        if (ev.target.matches('[data-enq="exercicio"]')) atualizarPCA();
        if (ev.target.matches('[data-enq="fonte"]')) alternarCampos();
        agendar();
    });
    form.addEventListener('input', agendar);
    gerarBtn.addEventListener('click', gerar);

    // Depois da primeira geração, a Informação acompanha o que o servidor digita
    function agendar() {
        if (!gerado) return;
        clearTimeout(timer);
        timer = setTimeout(gerar, 600);
    }

    fetch(`${ENQUADRAMENTO}/enquadramento/config`)
        .then(r => r.json())
        .then(c => { config = c; desenharFormulario(); })
        .catch(() => setStatus('Serviço de enquadramento indisponível. Verifique se o enquadramento-service está rodando (porta 8004).', 'error'));
}
