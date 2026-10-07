const menu = document.getElementById('hamburger');
const nav = document.getElementById('main-nav');
menu.setAttribute('aria-expanded', 'false');
menu.setAttribute('aria-controls', 'main-nav');
menu.addEventListener('click', () => {
  const open = menu.classList.toggle('open');
  nav.classList.toggle('open', open);
  menu.setAttribute('aria-expanded', String(open));
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && nav.classList.contains('open')) {
    nav.classList.remove('open'); menu.classList.remove('open');
    menu.setAttribute('aria-expanded', 'false'); menu.focus();
  }
});
document.getElementById('copy-ip').addEventListener('click', async () => {
  const feedback = document.getElementById('copy-feedback');
  try {
    await navigator.clipboard.writeText('fertilia.byteplay.xyz');
    feedback.textContent = 'Copied! See you in Fertilia.';
  } catch {
    feedback.textContent = 'Copy this address: fertilia.byteplay.xyz';
  }
});
fetch('footer.html').then(response => {
  if (!response.ok) throw new Error('Footer unavailable');
  return response.text();
}).then(html => { document.getElementById('footer-placeholder').innerHTML = html; })
.catch(() => { document.getElementById('footer-placeholder').textContent = 'BytePlay — Small studio. Big worlds.'; });

// Enhance visible content only when the browser supports scroll observation.
const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
const ticker = document.querySelector('.studio-ticker');
const tickerToggle = document.querySelector('.ticker-toggle');
tickerToggle.addEventListener('click', () => {
  const paused = ticker.classList.toggle('is-paused');
  tickerToggle.setAttribute('aria-pressed', String(paused));
  tickerToggle.setAttribute('aria-label', paused ? 'Resume moving banner' : 'Pause moving banner');
  tickerToggle.textContent = paused ? 'Play' : 'Pause';
});

if ('IntersectionObserver' in window) {
  const revealTargets = document.querySelectorAll('.intro-top, .studio-intro h1, .intro-bottom, .fertilia-heading, .fertilia-story, .fertilia-journey > div, .fertilia-connect, .section-heading, .studio-game, .community-inner > div, .note-row, .studio-hiring');
  revealTargets.forEach((element, index) => {
    element.classList.add('motion-reveal');
    element.style.setProperty('--reveal-delay', `${(index % 3) * 80}ms`);
  });
  const revealObserver = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        revealObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });
  revealTargets.forEach(element => revealObserver.observe(element));

  const statsObserver = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      statsObserver.unobserve(entry.target);
      if (motionPreference.matches) return;
      const element = entry.target;
      const node = element.firstChild;
      const original = node.textContent;
      const total = Number(original.replace(/,/g, ''));
      element.setAttribute('aria-label', element.textContent);
      const start = performance.now();
      function count(now) {
        const progress = Math.min((now - start) / 1300, 1);
        node.textContent = Math.round(total * (1 - (1 - progress) ** 3)).toLocaleString('en-US');
        if (progress < 1 && !motionPreference.matches) requestAnimationFrame(count);
        else node.textContent = original;
      }
      requestAnimationFrame(count);
    });
  }, { threshold: 0.6 });
  document.querySelectorAll('.community-numbers strong').forEach(element => statsObserver.observe(element));
}

// A small scroll-linked shift gives the Minecraft scene depth without moving text.
const opening = document.querySelector('.immersive-opening');
let scrollFrame = null;
function updateScene() {
  scrollFrame = null;
  const offset = motionPreference.matches ? 0 : Math.min(window.scrollY * 0.16, 100);
  opening.style.setProperty('--scene-offset', `${offset}px`);
  document.querySelector('.main-header').classList.toggle('has-scrolled', window.scrollY > 20);
}
window.addEventListener('scroll', () => {
  if (scrollFrame === null) scrollFrame = requestAnimationFrame(updateScene);
}, { passive: true });
motionPreference.addEventListener('change', updateScene);
updateScene();

// Show the newest managed stories after the CMS is connected.
if (window.BytePlayBlog?.enabled) {
  const notes = document.querySelector('.studio-notes');
  notes.querySelectorAll('.note-row').forEach(row => row.remove());
  BytePlayBlog.request('posts').then(({posts}) => {
    posts.slice(0, 2).forEach(post => {
      const row = document.createElement('a'); row.className = 'note-row'; row.href = 'post.html?id=' + encodeURIComponent(post.id);
      const category = document.createElement('span'); category.className = 'note-type'; category.textContent = post.category.toUpperCase() + ' / STUDIO NOTE';
      const title = document.createElement('h3'); title.textContent = post.title;
      const arrow = document.createElement('span'); arrow.className = 'note-arrow'; arrow.textContent = '→';
      row.append(category, title, arrow); notes.appendChild(row);
    });
  }).catch(() => {
    const message = document.createElement('p'); message.textContent = 'Studio notes are temporarily unavailable. Please check back soon.'; notes.appendChild(message);
  });
}
