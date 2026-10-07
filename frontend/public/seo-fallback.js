(() => {
  const paths = document.querySelector('meta[name="seo-public-paths"]')?.content.split(',') ?? [];
  const pathname = window.location.pathname.replace(/\/+$/, '') || '/';
  if (paths.includes(pathname)) return;

  const robots = document.querySelector('meta[name="robots"]');
  if (robots) robots.setAttribute('content', 'noindex, follow');
})();
