const mobileButton = document.querySelector('.mobile-nav');
const sidebar = document.querySelector('.sidebar');

if (mobileButton && sidebar) {
  mobileButton.addEventListener('click', () => {
    const open = sidebar.classList.toggle('open');
    mobileButton.setAttribute('aria-expanded', String(open));
  });
  sidebar.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => {
    sidebar.classList.remove('open');
    mobileButton.setAttribute('aria-expanded', 'false');
  }));
}

const toast = document.querySelector('.toast');
let toastTimer;
document.querySelectorAll('.copy-code').forEach((button) => {
  button.addEventListener('click', async () => {
    const value = button.closest('.code-block').querySelector('pre').innerText.replace(/^\$ /gm, '');
    try { await navigator.clipboard.writeText(value); }
    catch {
      const range = document.createRange();
      range.selectNodeContents(button.closest('.code-block').querySelector('pre'));
      window.getSelection().removeAllRanges();
      window.getSelection().addRange(range);
      document.execCommand('copy');
      window.getSelection().removeAllRanges();
    }
    button.querySelector('span').textContent = 'Copied';
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toast.classList.remove('show');
      button.querySelector('span').textContent = 'Copy';
    }, 1600);
  });
});

const search = document.querySelector('.doc-search');
if (search) {
  const cards = [...document.querySelectorAll('.doc-card')];
  const noResults = document.querySelector('.no-results');
  const applyFilter = () => {
    const query = search.value.trim().toLowerCase();
    let visible = 0;
    cards.forEach((card) => {
      const match = card.textContent.toLowerCase().includes(query);
      card.hidden = !match;
      if (match) visible += 1;
    });
    noResults.style.display = visible ? 'none' : 'block';
  };
  ['input', 'change', 'search', 'keyup'].forEach((eventName) => search.addEventListener(eventName, applyFilter));
}

const headings = [...document.querySelectorAll('.doc-main h2[id], .doc-main h3[id]')];
const tocLinks = [...document.querySelectorAll('.toc a')];
if (headings.length && tocLinks.length) {
  const observer = new IntersectionObserver((entries) => {
    const current = entries.filter((entry) => entry.isIntersecting).at(-1);
    if (!current) return;
    tocLinks.forEach((link) => link.classList.toggle('active', link.hash === `#${current.target.id}`));
  }, { rootMargin: '-15% 0px -70% 0px' });
  headings.forEach((heading) => observer.observe(heading));
}
