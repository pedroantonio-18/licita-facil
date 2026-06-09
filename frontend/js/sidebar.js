export function initSidebar() {
  initDropdowns();
  initNavigation();
}

function initDropdowns() {
  const triggers = document.querySelectorAll('.dropdown-trigger');

  triggers.forEach((trigger) => {
    trigger.addEventListener('click', () => {
      const parent = trigger.closest('.nav-item.dropdown');
      parent.classList.toggle('open');
    });
  });
}

function initNavigation() {
  const navLinks = document.querySelectorAll('.nav-link');
  const sections = document.querySelectorAll('.content-section');
  const headerTitle = document.querySelector('.main-heading');

  const PAGE_TITLES = {
    'pdf-compressor': 'Comprimir PDF',
    'pdf-merger': 'Mesclar PDFs',
    'pdf-to-excel': 'Converter PDF para XLSX',
    'gemini-test': 'Playground Gemini'
  };

  function navigateTo(targetId) {
    const targetSection = document.getElementById(targetId);
    if (!targetSection) return;

    sections.forEach((section) => section.classList.remove('active'));
    targetSection.classList.add('active');

    navLinks.forEach((l) => {
      const hrefId = l.getAttribute('href')?.replace('#', '');
      if (hrefId === targetId) {
        l.classList.add('active');
        const dropdownParent = l.closest('.nav-item.dropdown');
        if (dropdownParent) {
          dropdownParent.classList.add('open');
        }
      } else {
        l.classList.remove('active');
      }
    });

    if (headerTitle && PAGE_TITLES[targetId]) {
      headerTitle.textContent = PAGE_TITLES[targetId];
    }

    if (window.location.hash !== `#${targetId}`) {
      window.history.pushState(null, '', `#${targetId}`);
    }
  }

  navLinks.forEach((link) => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const targetId = link.getAttribute('href')?.replace('#', '');
      if (targetId) {
        navigateTo(targetId);
      }
    });
  });

  window.addEventListener('popstate', () => {
    const hashId = window.location.hash.replace('#', '') || 'pdf-compressor';
    navigateTo(hashId);
  });

  const initialHash = window.location.hash.replace('#', '') || 'pdf-compressor';
  navigateTo(initialHash);
}
