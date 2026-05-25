import { convertPdfToExcel } from './api.js';
import { renderRecentFiles } from './recentFiles.js';

const DOWNLOAD_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>`;

const SPREADSHEET_ICON_SVG = `<svg class="file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><line x1="10" y1="9" x2="8" y2="9"></line></svg>`;

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
      <div class="file-icon-wrapper excel-icon">
        ${SPREADSHEET_ICON_SVG}
      </div>
      <div class="file-details">
        <span class="file-name" title="${result.name}">${result.name}</span>
        <span class="file-meta">${formatSize(result.size)}</span>
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

export function initExcelConverter() {
  const section = document.getElementById('pdf-to-excel');
  if (!section) return;

  const dropzone = section.querySelector('.excel-dropzone');
  const fileInput = section.querySelector('.excel-input');
  const submitBtn = section.querySelector('.convert-btn');
  const fileInfo = section.querySelector('.excel-file-info');
  const fileName = section.querySelector('.excel-file-name');
  const removeBtn = section.querySelector('.excel-remove-btn');
  const statusMsg = section.querySelector('.convert-status');
  const resultsContainer = section.querySelector('.excel-results');

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
    statusMsg.className = 'convert-status';
  }

  function setStatus(text, type) {
    statusMsg.textContent = text;
    statusMsg.className = `convert-status ${type}`;
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

    submitBtn.disabled = true;
    setStatus('Convertendo...', 'loading');

    sessionResults = [];
    renderSessionResults(resultsContainer, sessionResults);

    try {
      const result = await convertPdfToExcel(selectedFile);
      await renderRecentFiles();

      sessionResults.push({
        name: result.name,
        size: result.size,
        blob: result.blob,
      });

      renderSessionResults(resultsContainer, sessionResults);
      setStatus('PDF convertido com sucesso!', 'success');
      clearFile();
    } catch (err) {
      setStatus(err.message || 'Erro ao converter arquivo.', 'error');
      submitBtn.disabled = false;
    }
  });
}
