/* La credencial del motor, en un solo sitio.

   Antes cada script la leia por su cuenta y solo de la URL: bastaba un guardado (que responde un 303
   a `/settings?...` sin token) para que la pantalla se quedase sin credencial y todo lo demas fallara
   como si el motor estuviera caido. Aqui se resuelve una vez, en este orden de prioridad:

     1. `?token=` de la URL (como llega desde el escritorio o desde la consola del motor),
     2. `<meta name="nexus-token">`, que el servidor pinta en las dos paginas,
     3. `sessionStorage`, para que una navegacion interna no la pierda.

   Y se estampa en todo enlace interno (`a[href^="/"]`) que no la lleve ya: un enlace sin token es una
   pantalla que pierde la credencial al pulsarla. No lleva nada de datos del motor, solo la cadena. */
(function () {
  const meta = document.querySelector('meta[name="nexus-token"]');
  const fromUrl = new URLSearchParams(location.search).get('token') || '';
  let stored = '';
  try { stored = sessionStorage.getItem('nexus-token') || ''; } catch (error) { stored = ''; }
  const token = fromUrl || (meta && meta.content) || stored || '';
  if (fromUrl) {
    try { sessionStorage.setItem('nexus-token', fromUrl); } catch (error) { /* modo privado */ }
  }
  window.NexusToken = token;
  if (!token) return;

  function stamp() {
    for (const link of document.querySelectorAll('a[href^="/"]')) {
      const href = link.getAttribute('href');
      if (!href || href.includes('token=')) continue;
      link.setAttribute('href', href + (href.includes('?') ? '&' : '?')
        + 'token=' + encodeURIComponent(token));
    }
  }
  stamp();
  document.addEventListener('DOMContentLoaded', stamp);
}());
