import { getRecentFiles, getFileById, deleteFile } from './db.js';

const FILE_ICONS = {
  'application/pdf': {
    class: 'pdf-icon',
    svg: `<svg class="file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>`,
  },
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': {
    class: 'excel-icon',
    svg: `<svg class="file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="9" y1="3" x2="9" y2="21"></line><line x1="15" y1="3" x2="15" y2="21"></line><line x1="3" y1="9" x2="21" y2="9"></line><line x1="3" y1="15" x2="21" y2="15"></line></svg>`,
  },
  'application/vnd.ms-excel': {
    class: 'excel-icon',
    svg: `<svg class="file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="9" y1="3" x2="9" y2="21"></line><line x1="15" y1="3" x2="15" y2="21"></line><line x1="3" y1="9" x2="21" y2="9"></line><line x1="3" y1="15" x2="21" y2="15"></line></svg>`,
  },
};

const DEFAULT_ICON = {
  class: 'generic-icon',
  svg: `<svg class="file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline></svg>`,
};

const DOWNLOAD_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>`;

const TRASH_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path><path d="M10 11v6"></path><path d="M14 11v6"></path><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path></svg>`;

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function timeAgo(timestamp) {
  const seconds = Math.floor((Date.now() - timestamp) / 1000);
  if (seconds < 60) return 'Agora';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `Há ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `Há ${hours}h`;
  const days = Math.floor(hours / 24);
  if (days === 1) return 'Ontem';
  return `Há ${days} dias`;
}

async function downloadFile(id) {
  const record = await getFileById(id);
  if (!record) return;

  const url = URL.createObjectURL(record.blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = record.name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function createFileItem(record) {
  const iconInfo = FILE_ICONS[record.mimeType] || DEFAULT_ICON;

  const li = document.createElement('li');
  li.className = 'recent-file-item';

  li.innerHTML = `
    <div class="file-icon-wrapper ${iconInfo.class}">
      ${iconInfo.svg}
    </div>
    <div class="file-details">
      <span class="file-name" title="${record.name}">${record.name}</span>
      <span class="file-meta">${formatSize(record.size)} • ${timeAgo(record.createdAt)}</span>
    </div>
    <div class="file-actions">
      <button class="file-action-btn" title="Baixar">
        ${DOWNLOAD_SVG}
      </button>
      <button class="file-action-btn file-delete-btn" title="Remover">
        ${TRASH_SVG}
      </button>
    </div>
  `;

  li.querySelector('.file-action-btn').addEventListener('click', () => downloadFile(record.id));
  li.querySelector('.file-delete-btn').addEventListener('click', async () => {
    await deleteFile(record.id);
    await renderRecentFiles();
  });

  return li;
}

export async function renderRecentFiles() {
  const list = document.querySelector('.recent-files-list');
  if (!list) return;

  const files = await getRecentFiles();

  list.innerHTML = '';

  if (files.length === 0) {
    list.innerHTML = `
      <li class="recent-files-empty">
        <span>Nenhum arquivo recente</span>
      </li>
    `;
    return;
  }

  for (const record of files) {
    list.appendChild(createFileItem(record));
  }
}
