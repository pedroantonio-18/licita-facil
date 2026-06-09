export function initGeminiTest() {
  const statusBadge = document.getElementById('gemini-status-badge');
  const toggleConfigBtn = document.getElementById('toggle-config-btn');
  const configBody = document.getElementById('gemini-config-body');
  const keyInput = document.getElementById('gemini-key-input');
  const toggleKeyVisibilityBtn = document.getElementById('toggle-key-visibility');
  const saveKeyBtn = document.getElementById('save-key-btn');
  const clearKeyBtn = document.getElementById('clear-key-btn');
  
  const promptInput = document.getElementById('gemini-prompt-input');
  const sendBtn = document.getElementById('gemini-send-btn');
  const outputBody = document.getElementById('gemini-output');
  const copyOutputBtn = document.getElementById('copy-output-btn');

  let activeApiKey = '';

  // 1. Resolve API Key from env variable or localStorage
  function loadApiKey() {
    // Try Vite define/environment variable first
    const envKey = import.meta.env.VITE_GEMINI_API_KEY;
    const localKey = localStorage.getItem('GEMINI_API_KEY');

    if (envKey && envKey.trim()) {
      activeApiKey = envKey.trim();
      keyInput.value = '••••••••••••••••••••••••••••••••';
      keyInput.disabled = true;
      statusBadge.textContent = 'API Key (Injetada via Env)';
      statusBadge.className = 'config-status-badge active';
      saveKeyBtn.disabled = true;
      clearKeyBtn.disabled = true;
      keyInput.placeholder = 'Injetada automaticamente via .env';
    } else if (localKey && localKey.trim()) {
      activeApiKey = localKey.trim();
      keyInput.value = activeApiKey;
      keyInput.disabled = false;
      statusBadge.textContent = 'API Key Configurada';
      statusBadge.className = 'config-status-badge active';
      saveKeyBtn.disabled = false;
      clearKeyBtn.disabled = false;
      keyInput.placeholder = 'Cole sua API Key aqui (AIzaSy...)';
    } else {
      activeApiKey = '';
      keyInput.value = '';
      keyInput.disabled = false;
      statusBadge.textContent = 'Sem Chave de API';
      statusBadge.className = 'config-status-badge';
      saveKeyBtn.disabled = false;
      clearKeyBtn.disabled = true;
      keyInput.placeholder = 'Cole sua API Key aqui (AIzaSy...)';
    }
  }

  // 2. Toggle config panel visibility
  toggleConfigBtn.addEventListener('click', () => {
    configBody.classList.toggle('hidden');
    if (configBody.classList.contains('hidden')) {
      toggleConfigBtn.textContent = 'Configurar Chave';
    } else {
      toggleConfigBtn.textContent = 'Ocultar Configuração';
    }
  });

  // 3. Toggle key input visibility (password vs text)
  toggleKeyVisibilityBtn.addEventListener('click', () => {
    if (keyInput.type === 'password') {
      keyInput.type = 'text';
      toggleKeyVisibilityBtn.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="icon-sm">
          <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
          <line x1="1" y1="1" x2="23" y2="23"></line>
        </svg>
      `;
    } else {
      keyInput.type = 'password';
      toggleKeyVisibilityBtn.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="icon-sm">
          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
          <circle cx="12" cy="12" r="3"></circle>
        </svg>
      `;
    }
  });

  // 4. Save API Key
  saveKeyBtn.addEventListener('click', () => {
    const value = keyInput.value.trim();
    if (!value) {
      alert('Por favor, insira uma chave de API válida.');
      return;
    }
    localStorage.setItem('GEMINI_API_KEY', value);
    loadApiKey();
    alert('Chave de API salva com sucesso!');
    configBody.classList.add('hidden');
    toggleConfigBtn.textContent = 'Configurar Chave';
  });

  // 5. Clear API Key
  clearKeyBtn.addEventListener('click', () => {
    localStorage.removeItem('GEMINI_API_KEY');
    loadApiKey();
    alert('Chave de API removida.');
  });

  // 6. Copy output
  copyOutputBtn.addEventListener('click', () => {
    const rawText = outputBody.innerText;
    navigator.clipboard.writeText(rawText)
      .then(() => {
        const originalText = copyOutputBtn.innerHTML;
        copyOutputBtn.innerHTML = `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="icon-sm"><polyline points="20 6 9 17 4 12"></polyline></svg>
          <span>Copiado!</span>
        `;
        setTimeout(() => {
          copyOutputBtn.innerHTML = originalText;
        }, 2000);
      })
      .catch((err) => {
        console.error('Falha ao copiar:', err);
      });
  });

  // 7. Format markdown output
  function formatMarkdown(text) {
    // 1. Escape basic HTML elements to prevent HTML injection
    let escapedText = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // 2. Parse code blocks (restore actual text formatting inside blocks)
    // We temporarily preserve the code block matches by tokenizing them
    const codeBlocks = [];
    escapedText = escapedText.replace(/```([\s\S]*?)```/g, (match, code) => {
      const id = `__CODE_BLOCK_${codeBlocks.length}__`;
      codeBlocks.push(`<pre><code>${code.trim()}</code></pre>`);
      return id;
    });

    // 3. Parse inline code
    escapedText = escapedText.replace(/`([^`]+)`/g, '<code>$1</code>');

    // 4. Parse bold text
    escapedText = escapedText.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    escapedText = escapedText.replace(/\*([^*]+)\*/g, '<em>$1</em>');

    // 5. Parse bullet lists
    const lines = escapedText.split('\n');
    let inList = false;
    const processedLines = [];

    for (let line of lines) {
      const trimmed = line.trim();
      const listMatch = trimmed.match(/^[-*+]\s+(.+)/);

      if (listMatch) {
        if (!inList) {
          processedLines.push('<ul>');
          inList = true;
        }
        processedLines.push(`<li>${listMatch[1]}</li>`);
      } else {
        if (inList) {
          processedLines.push('</ul>');
          inList = false;
        }
        processedLines.push(line);
      }
    }
    if (inList) {
      processedLines.push('</ul>');
    }
    escapedText = processedLines.join('\n');

    // 6. Split into paragraphs (avoid wrapping existing structures)
    const blocks = escapedText.split(/\n\n+/);
    let html = blocks.map(block => {
      const trimmed = block.trim();
      if (!trimmed) return '';
      if (trimmed.startsWith('__CODE_BLOCK_') || trimmed.startsWith('<ul>') || trimmed.startsWith('<li>')) {
        return trimmed;
      }
      return `<p>${trimmed.replace(/\n/g, '<br>')}</p>`;
    }).filter(Boolean).join('');

    // 7. Inject code blocks back
    codeBlocks.forEach((codeHtml, idx) => {
      html = html.replace(`__CODE_BLOCK_${idx}__`, codeHtml);
    });

    return `<div class="gemini-markdown-output">${html}</div>`;
  }

  // 8. Call Gemini API
  async function callGeminiAPI(prompt) {
    if (!activeApiKey) {
      throw new Error('Chave de API não configurada. Por favor, adicione uma chave de API na seção de configuração.');
    }

    const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${activeApiKey}`;
    
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        contents: [
          {
            parts: [
              {
                text: prompt
              }
            ]
          }
        ]
      })
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => null);
      const message = errorData?.error?.message || `Erro do Gemini (${response.status})`;
      throw new Error(message);
    }

    const data = await response.json();
    const text = data?.candidates?.[0]?.content?.parts?.[0]?.text;
    
    if (!text) {
      throw new Error('Nenhuma resposta retornada do modelo.');
    }

    return text;
  }

  // 9. Send button event listener
  sendBtn.addEventListener('click', async () => {
    const prompt = promptInput.value.trim();
    if (!prompt) return;

    // Loading UI state
    sendBtn.disabled = true;
    copyOutputBtn.style.display = 'none';
    outputBody.innerHTML = `
      <div class="output-loading">
        <div class="spinner"></div>
        <span>Aguardando resposta do Gemini...</span>
      </div>
    `;

    try {
      const result = await callGeminiAPI(prompt);
      outputBody.innerHTML = formatMarkdown(result);
      copyOutputBtn.style.display = 'flex';
    } catch (error) {
      outputBody.innerHTML = `
        <div class="output-error">
          <strong>Erro:</strong> ${error.message}
        </div>
      `;
      copyOutputBtn.style.display = 'none';
    } finally {
      sendBtn.disabled = false;
    }
  });

  // Allow Command/Control + Enter to send prompt
  promptInput.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      sendBtn.click();
    }
  });

  // Initial load
  loadApiKey();
}
