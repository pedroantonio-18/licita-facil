import { saveFile } from './db.js';

const API_BASE = 'http://localhost:8000';

export async function compressPdf(file, level = 'medium') {
  const formData = new FormData();
  formData.append('file', file);

  const url = `${API_BASE}/compressor/compress?level=${encodeURIComponent(level)}`;

  const response = await fetch(url, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    const message = errorData?.detail || `Erro ${response.status}`;
    throw new Error(message);
  }

  let fileName = `compressed_${file.name}`;
  const disposition = response.headers.get('Content-Disposition');
  if (disposition) {
    const match = disposition.match(/filename=(.+)/i);
    if (match) {
      fileName = match[1].replace(/["']/g, '').trim();
    }
  }

  const blob = await response.blob();

  const id = await saveFile({
    name: fileName,
    blob,
    mimeType: blob.type || 'application/pdf',
    size: blob.size,
    source: 'compressor',
  });

  return { id, name: fileName, size: blob.size, blob };
}

export async function mergePdfs(files, suggestedName = 'merged.pdf') {
  const formData = new FormData();
  for (const file of files) {
    formData.append('files', file);
  }

  const url = `${API_BASE}/merger/merge`;

  const response = await fetch(url, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    const message = errorData?.detail || `Erro ${response.status}`;
    throw new Error(message);
  }

  let fileName = suggestedName;
  const disposition = response.headers.get('Content-Disposition');
  if (disposition) {
    const match = disposition.match(/filename=(.+)/i);
    if (match) {
      const parsed = match[1].replace(/["']/g, '').trim();
      if (parsed !== 'merged.pdf') {
        fileName = parsed;
      }
    }
  }

  const blob = await response.blob();

  const id = await saveFile({
    name: fileName,
    blob,
    mimeType: blob.type || 'application/pdf',
    size: blob.size,
    source: 'merger',
  });

  return { id, name: fileName, size: blob.size, blob };
}
