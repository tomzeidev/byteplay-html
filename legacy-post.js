if (window.BYTEPLAY_CMS?.apiBase) {
  const id = document.currentScript.dataset.post;
  window.location.replace('post.html?id=' + encodeURIComponent(id));
}
