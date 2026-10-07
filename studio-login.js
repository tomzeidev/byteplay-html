const base = window.BYTEPLAY_CMS?.apiBase;
if (base) {
  document.getElementById('login-message').textContent = 'Sign in to write development updates and manage your studio.';
  const link = document.getElementById('login-link'); link.href = base.replace(/\/$/, '') + '/admin'; link.hidden = false;
}
