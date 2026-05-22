import { compressPdf } from './api.js';
import { renderRecentFiles } from './recentFiles.js';

const DOWNLOAD_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>`;

const PDF_ICON_SVG = `<svg class="file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>`;

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

function renderSessionResults(container, results) {
  if (results.length === 0) {
    container.innerHTML = '';
    return;
  }

  container.innerHTML = `
    <h3 class="session-results-title">Arquivos processados</h3>
    <ul class="session-results-list"></ul>
  `;

  const list = container.querySelector('.session-results-list');

  for (const result of results) {
    const li = document.createElement('li');
    li.className = 'session-result-item';

    li.innerHTML = `
      <div class="file-icon-wrapper pdf-icon">
        ${PDF_ICON_SVG}
      </div>
      <div class="file-details">
        <span class="file-name" title="${result.name}">${result.name}</span>
        <span class="file-meta">${formatSize(result.originalSize)} → ${formatSize(result.size)}</span>
      </div>
      <button class="file-action-btn" title="Baixar">
        ${DOWNLOAD_SVG}
      </button>
    `;

    const btn = li.querySelector('.file-action-btn');
    btn.addEventListener('click', () => downloadBlob(result.blob, result.name));

    list.appendChild(li);
  }
}

export function initCompressor() {
  const section = document.getElementById('pdf-compressor');
  if (!section) return;

  const dropzone = section.querySelector('.dropzone');
  const fileInput = section.querySelector('.dropzone-input');
  const levelSelect = section.querySelector('.level-select');
  const submitBtn = section.querySelector('.compress-btn');
  const fileInfo = section.querySelector('.file-info');
  const fileName = section.querySelector('.file-info-name');
  const removeBtn = section.querySelector('.file-remove-btn');
  const statusMsg = section.querySelector('.compress-status');
  const resultsContainer = section.querySelector('.session-results');

  let selectedFile = null;
  let sessionResults = [];

  function showFile(file) {
    selectedFile = file;
    fileName.textContent = file.name;
    fileInfo.classList.add('visible');
    submitBtn.disabled = false;
    dropzone.classList.add('has-file');
  }

  function clearFile() {
    selectedFile = null;
    fileInput.value = '';
    fileInfo.classList.remove('visible');
    submitBtn.disabled = true;
    dropzone.classList.remove('has-file');
    statusMsg.textContent = '';
    statusMsg.className = 'compress-status';
  }

  function setStatus(text, type) {
    statusMsg.textContent = text;
    statusMsg.className = `compress-status ${type}`;
  }

  dropzone.addEventListener('click', () => fileInput.click());

  dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('drag-over');
  });

  dropzone.addEventListener('dragleave', () => {
    dropzone.classList.remove('drag-over');
  });

  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file && file.type === 'application/pdf') {
      showFile(file);
    } else {
      setStatus('Selecione um arquivo PDF válido.', 'error');
    }
  });

  fileInput.addEventListener('change', () => {
    const file = fileInput.files[0];
    if (file) showFile(file);
  });

  removeBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    clearFile();
  });

  submitBtn.addEventListener('click', async () => {
    if (!selectedFile) return;

    const originalSize = selectedFile.size;
    submitBtn.disabled = true;
    setStatus('Comprimindo...', 'loading');

    sessionResults = [];
    renderSessionResults(resultsContainer, sessionResults);

    try {
      const level = levelSelect.value;
      const result = await compressPdf(selectedFile, level);
      await renderRecentFiles();

      sessionResults.push({
        name: result.name,
        size: result.size,
        originalSize,
        blob: result.blob,
      });

      renderSessionResults(resultsContainer, sessionResults);
      setStatus('Arquivo comprimido com sucesso!', 'success');
      clearFile();
    } catch (err) {
      setStatus(err.message || 'Erro ao comprimir.', 'error');
      submitBtn.disabled = false;
    }
  });
}
