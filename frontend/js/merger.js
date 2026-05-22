import { saveFile } from './db.js';
import { renderRecentFiles } from './recentFiles.js';
import { mergePdfs } from './api.js';

const DOWNLOAD_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>`;

const PDF_ICON_SVG = `<svg class="file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>`;

const TRASH_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path><path d="M10 11v6"></path><path d="M14 11v6"></path><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path></svg>`;

const UP_ARROW_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 15 12 9 6 15"></polyline></svg>`;

const DOWN_ARROW_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>`;

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
        <span class="file-meta">Tamanho total: ${formatSize(result.size)}</span>
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

export function initMerger() {
  const section = document.getElementById('pdf-merger');
  if (!section) return;

  const dropzone = section.querySelector('.merger-dropzone');
  const fileInput = section.querySelector('.merger-input');
  const fileListContainer = section.querySelector('.merger-file-list-container');
  const fileList = section.querySelector('.merger-file-list');
  const mergeBtn = section.querySelector('.merge-btn');
  const statusMsg = section.querySelector('.merge-status');
  const resultsContainer = section.querySelector('.merger-results');

  let selectedFiles = [];
  let sessionResults = [];

  function updateUI() {
    if (selectedFiles.length === 0) {
      fileListContainer.style.display = 'none';
      mergeBtn.disabled = true;
      dropzone.classList.remove('has-file');
    } else {
      fileListContainer.style.display = 'block';
      mergeBtn.disabled = selectedFiles.length < 2;
      dropzone.classList.add('has-file');
    }

    renderList();
  }

  function renderList() {
    fileList.innerHTML = '';

    selectedFiles.forEach((item, index) => {
      const li = document.createElement('li');
      li.className = 'merger-file-item';

      const isFirst = index === 0;
      const isLast = index === selectedFiles.length - 1;

      li.innerHTML = `
        <div class="merger-file-number">${index + 1}</div>
        <div class="file-icon-wrapper pdf-icon">
          ${PDF_ICON_SVG}
        </div>
        <div class="file-details">
          <span class="file-name" title="${item.file.name}">${item.file.name}</span>
          <span class="file-meta">${formatSize(item.file.size)}</span>
        </div>
        <div class="merger-file-actions">
          <button type="button" class="file-action-btn move-up-btn" title="Mover para cima" ${isFirst ? 'disabled' : ''}>
            ${UP_ARROW_SVG}
          </button>
          <button type="button" class="file-action-btn move-down-btn" title="Mover para baixo" ${isLast ? 'disabled' : ''}>
            ${DOWN_ARROW_SVG}
          </button>
          <button type="button" class="file-action-btn file-delete-btn" title="Remover">
            ${TRASH_SVG}
          </button>
        </div>
      `;

      const upBtn = li.querySelector('.move-up-btn');
      if (!isFirst) {
        upBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          swapItems(index, index - 1);
        });
      }

      const downBtn = li.querySelector('.move-down-btn');
      if (!isLast) {
        downBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          swapItems(index, index + 1);
        });
      }

      const deleteBtn = li.querySelector('.file-delete-btn');
      deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeFile(index);
      });

      fileList.appendChild(li);
    });
  }

  function swapItems(idx1, idx2) {
    const temp = selectedFiles[idx1];
    selectedFiles[idx1] = selectedFiles[idx2];
    selectedFiles[idx2] = temp;
    updateUI();
  }

  function removeFile(index) {
    selectedFiles.splice(index, 1);
    updateUI();
  }

  function handleFilesInput(files) {
    let addedCount = 0;
    Array.from(files).forEach((file) => {
      if (file.type === 'application/pdf' || file.name.endsWith('.pdf')) {
        selectedFiles.push({
          file,
          id: Math.random().toString(36).substring(2, 9)
        });
        addedCount++;
      }
    });

    if (addedCount > 0) {
      setStatus('');
      updateUI();
    } else {
      setStatus('Selecione arquivos PDF válidos.', 'error');
    }
  }

  function setStatus(text, type = '') {
    statusMsg.textContent = text;
    statusMsg.className = `merge-status ${type}`;
  }

  function clearFiles() {
    selectedFiles = [];
    fileInput.value = '';
    updateUI();
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
    if (e.dataTransfer.files.length > 0) {
      handleFilesInput(e.dataTransfer.files);
    }
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
      handleFilesInput(fileInput.files);
    }
  });

  mergeBtn.addEventListener('click', async () => {
    if (selectedFiles.length < 2) return;

    mergeBtn.disabled = true;
    setStatus('Mesclando PDFs...', 'loading');

    sessionResults = [];
    renderSessionResults(resultsContainer, sessionResults);

    try {
      const fileNames = selectedFiles.map(item => {
        const name = item.file.name;
        const lastDot = name.lastIndexOf('.');
        return lastDot !== -1 ? name.substring(0, lastDot) : name;
      });
      const outputName = `merged_${fileNames.join('_')}.pdf`;

      const filesToMerge = selectedFiles.map(item => item.file);

      const result = await mergePdfs(filesToMerge, outputName);

      await renderRecentFiles();

      sessionResults.push({
        id: result.id,
        name: result.name,
        size: result.size,
        blob: result.blob
      });

      renderSessionResults(resultsContainer, sessionResults);
      setStatus('Arquivos mesclados com sucesso!', 'success');
      clearFiles();
    } catch (err) {
      setStatus(err.message || 'Erro ao mesclar arquivos.', 'error');
      mergeBtn.disabled = false;
    }
  });
}
