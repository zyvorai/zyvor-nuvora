// Applies the stored theme before first paint. External file: the server CSP forbids inline scripts.
(function () {
  try {
    var t = localStorage.getItem('nuvora-theme');
    if (t !== 'dark' && t !== 'light') t = 'light';
    document.documentElement.setAttribute('data-theme', t);
    var m = document.querySelector('meta[name="theme-color"]');
    if (m) m.setAttribute('content', t === 'dark' ? '#000000' : '#ffffff');
  } catch (e) {
    document.documentElement.setAttribute('data-theme', 'light');
  }
})();
