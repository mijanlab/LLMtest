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
