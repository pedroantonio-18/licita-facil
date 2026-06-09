import { initSidebar } from './sidebar.js';
import { renderRecentFiles } from './recentFiles.js';
import { initCompressor } from './compressor.js';
import { initMerger } from './merger.js';
import { initExcelConverter } from './excelConverter.js';
import { initGeminiTest } from './geminiTest.js';

document.addEventListener('DOMContentLoaded', () => {
  initSidebar();
  renderRecentFiles();
  initCompressor();
  initMerger();
  initExcelConverter();
  initGeminiTest();
});
