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
