import { initSidebar } from './sidebar.js';
import { renderRecentFiles } from './recentFiles.js';
import { initCompressor } from './compressor.js';
import { initMerger } from './merger.js';

document.addEventListener('DOMContentLoaded', () => {
  initSidebar();
  renderRecentFiles();
  initCompressor();
  initMerger();
});
