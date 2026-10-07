(() => {
  const base = (window.BYTEPLAY_CMS?.apiBase || '').replace(/\/$/, '');
  window.BytePlayBlog = {
    enabled: Boolean(base),
    async request(path) {
      const response = await fetch(base + '/api/public/' + path, { credentials: 'omit', signal: AbortSignal.timeout(12000) });
      if (!response.ok) throw new Error(response.status === 404 ? 'Post not found.' : 'The blog service is temporarily unavailable. Please try again.');
      return response.json();
    },
    asset(path) {
      if (!path) return '';
      // Historical assets stay on Pages; new uploads are HTTPS URLs from the CMS.
      return path;
    },
    date(value) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
      return new Date(value + 'T00:00:00Z').toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
    }
  };
})();
