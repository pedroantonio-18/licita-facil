import { initSidebar } from './sidebar.js';
import { renderRecentFiles } from './recentFiles.js';
import { initCompressor } from './compressor.js';

document.addEventListener('DOMContentLoaded', () => {
  initSidebar();
  renderRecentFiles();
  initCompressor();
});
