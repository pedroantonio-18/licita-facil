import { initSidebar } from './sidebar.js';
import { renderRecentFiles } from './recentFiles.js';
import { initCompressor } from './compressor.js';
import { initMerger } from './merger.js';
import { initExcelConverter } from './excelConverter.js';
import { initGeminiTest } from './geminiTest.js';
import { initConluio } from './conluio.js';
import { initJuntada } from './juntada.js';
import { initMinutas } from './minutas.js';
import { initEnquadramento } from './enquadramento.js';

document.addEventListener('DOMContentLoaded', () => {
  initSidebar();
  renderRecentFiles();
  initCompressor();
  initMerger();
  initExcelConverter();
  initGeminiTest();
  initConluio();
  initJuntada();
  initMinutas();
  initEnquadramento();
});
