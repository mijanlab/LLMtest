const header = document.querySelector('.site-header');
const menuButton = document.querySelector('.menu-button');
const navigation = document.querySelector('.site-nav');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const updateHeader = () => header.classList.toggle('scrolled', window.scrollY > 80);
updateHeader();
window.addEventListener('scroll', updateHeader, { passive: true });

menuButton.addEventListener('click', () => {
  const isOpen = menuButton.getAttribute('aria-expanded') === 'true';
  menuButton.setAttribute('aria-expanded', String(!isOpen));
  menuButton.setAttribute('aria-label', isOpen ? 'Open navigation' : 'Close navigation');
  navigation.classList.toggle('open', !isOpen);
});

navigation.querySelectorAll('a').forEach((link) => {
  link.addEventListener('click', () => {
    menuButton.setAttribute('aria-expanded', 'false');
    menuButton.setAttribute('aria-label', 'Open navigation');
    navigation.classList.remove('open');
  });
});

const formatCount = (value) => Number.isInteger(value) ? String(value) : value.toFixed(1);
const animateCounter = (element) => {
  if (element.dataset.animated) return;
  element.dataset.animated = 'true';
  const target = Number(element.dataset.count);
  if (target === 0 || reducedMotion) {
    element.textContent = formatCount(target);
    return;
  }
  const duration = 1100;
  const start = performance.now();
  const frame = (now) => {
    const progress = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    const current = target * eased;
    element.textContent = formatCount(Number.isInteger(target) ? Math.round(current) : Number(current.toFixed(1)));
    if (progress < 1) requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
};

const revealObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (!entry.isIntersecting) return;
    const element = entry.target;
    if (element.dataset.delay) element.style.setProperty('--delay', `${element.dataset.delay}ms`);
    element.classList.add('visible');
    element.querySelectorAll('[data-count]').forEach(animateCounter);
    revealObserver.unobserve(element);
  });
}, { threshold: 0.12 });

document.querySelectorAll('.reveal').forEach((element) => revealObserver.observe(element));

const countObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (!entry.isIntersecting) return;
    animateCounter(entry.target);
    countObserver.unobserve(entry.target);
  });
}, { threshold: 0.7 });

document.querySelectorAll('.trust-strip [data-count]').forEach((element) => countObserver.observe(element));

const installTabs = document.querySelectorAll('.install-tabs button');
const installCommand = document.querySelector('#install-command');
installTabs.forEach((tab) => {
  tab.addEventListener('click', () => {
    installTabs.forEach((item) => {
      item.classList.remove('active');
      item.setAttribute('aria-selected', 'false');
    });
    tab.classList.add('active');
    tab.setAttribute('aria-selected', 'true');
    installCommand.textContent = tab.dataset.command;
  });
});

const toast = document.querySelector('.copy-toast');
let toastTimer;
document.querySelector('.copy-button').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(installCommand.textContent);
  } catch {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(installCommand);
    selection.removeAllRanges();
    selection.addRange(range);
    document.execCommand('copy');
    selection.removeAllRanges();
  }
  clearTimeout(toastTimer);
  toast.classList.add('show');
  toastTimer = setTimeout(() => toast.classList.remove('show'), 1800);
});

const stepItems = [...document.querySelectorAll('.steps li')];
if (!reducedMotion) {
  let activeStep = 0;
  setInterval(() => {
    stepItems[activeStep].classList.remove('active');
    activeStep = (activeStep + 1) % stepItems.length;
    stepItems[activeStep].classList.add('active');
  }, 2200);
}

document.querySelectorAll('.faq-item button').forEach((button) => {
  button.addEventListener('click', () => {
    const item = button.closest('.faq-item');
    const willOpen = !item.classList.contains('open');
    document.querySelectorAll('.faq-item').forEach((entry) => {
      entry.classList.remove('open');
      entry.querySelector('button').setAttribute('aria-expanded', 'false');
    });
    if (willOpen) {
      item.classList.add('open');
      button.setAttribute('aria-expanded', 'true');
    }
  });
});

const progressBar = document.querySelector('.scroll-progress i');
const updateScrollProgress = () => {
  const scrollable = document.documentElement.scrollHeight - window.innerHeight;
  const progress = scrollable > 0 ? (window.scrollY / scrollable) * 100 : 0;
  progressBar.style.setProperty('--scroll', `${Math.min(100, Math.max(0, progress))}%`);
};
updateScrollProgress();
window.addEventListener('scroll', updateScrollProgress, { passive: true });
window.addEventListener('resize', updateScrollProgress);

const terminalOutput = document.querySelector('#terminal-output');
const terminalForm = document.querySelector('.terminal-form');
const terminalInput = document.querySelector('#terminal-command');
const terminalReplay = document.querySelector('.terminal-replay');
const terminalClear = document.querySelector('.terminal-clear');
const initialTerminalNodes = [...terminalOutput.children].map((node) => node.cloneNode(true));
let replayTimers = [];

const clearReplayTimers = () => {
  replayTimers.forEach(clearTimeout);
  replayTimers = [];
};

const appendTerminalLine = (text, className = '') => {
  const line = document.createElement('p');
  line.className = `term-new ${className}`.trim();
  line.textContent = text;
  terminalOutput.appendChild(line);
  line.scrollIntoView({ block: 'nearest', behavior: reducedMotion ? 'auto' : 'smooth' });
};

const replayTerminal = () => {
  clearReplayTimers();
  terminalOutput.replaceChildren();
  initialTerminalNodes.forEach((source, index) => {
    const timer = setTimeout(() => {
      const node = source.cloneNode(true);
      node.classList.add('term-new');
      terminalOutput.appendChild(node);
    }, reducedMotion ? 0 : index * 95);
    replayTimers.push(timer);
  });
};

terminalReplay.addEventListener('click', replayTerminal);
terminalClear.addEventListener('click', () => {
  clearReplayTimers();
  terminalOutput.replaceChildren();
  terminalInput.focus();
});

terminalForm.addEventListener('submit', (event) => {
  event.preventDefault();
  clearReplayTimers();
  const command = terminalInput.value.trim();
  if (!command) return;
  appendTerminalLine(`$ ${command}`, 'term-command');
  terminalInput.value = '';
  const normalized = command.toLowerCase();
  if (normalized === 'clear') {
    terminalOutput.replaceChildren();
  } else if (normalized === 'llmtest --version' || normalized === 'llmtest -v') {
    appendTerminalLine('llmtest 1.0.6', 'muted');
  } else if (normalized === 'llmtest --help' || normalized === 'llmtest -h') {
    appendTerminalLine('usage: llmtest [endpoint | update | uninstall] [key] [filter] [options]', 'muted');
    appendTerminalLine('options: --runs  --concurrency  --prompt  --timeout  --open', 'muted');
  } else if (normalized === 'llmtest' || normalized.startsWith('llmtest ')) {
    appendTerminalLine('Interactive setup ready. Endpoint, key, filter, and concurrency will be prompted.', 'muted');
    appendTerminalLine('Demo only — run this command in your local terminal to benchmark models.', 'ok');
  } else {
    appendTerminalLine(`Command not available in this demo: ${command}`, 'term-error');
    appendTerminalLine('Try llmtest, llmtest --help, llmtest --version, or clear.', 'muted');
  }
});

const heroVisual = document.querySelector('.hero-visual');
const appWindow = document.querySelector('.app-window');
if (!reducedMotion && window.matchMedia('(pointer: fine)').matches) {
  heroVisual.addEventListener('pointermove', (event) => {
    const bounds = heroVisual.getBoundingClientRect();
    const x = (event.clientX - bounds.left) / bounds.width - 0.5;
    const y = (event.clientY - bounds.top) / bounds.height - 0.5;
    appWindow.style.transform = `rotateY(${(-4 + x * 3).toFixed(2)}deg) rotateX(${(1.5 - y * 3).toFixed(2)}deg) translateY(-2px)`;
  });
  heroVisual.addEventListener('pointerleave', () => {
    appWindow.style.transform = '';
  });
}
