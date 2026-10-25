/* La pantalla de configuración funciona SIN este fichero: navegar es un `<a>` y guardar es un
   `<form>` que contesta un 303. Aquí solo van los dos atajos que un menú de ajustes debe tener
   (Ctrl+K para buscar, Esc para volver al chat) y el filtro del árbol mientras se escribe, que
   ahorra el viaje de ida y vuelta que el servidor ya sabe hacer con `?q=`. */

(function () {
  const search = document.getElementById('settings-search');

  document.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && String(event.key).toLowerCase() === 'k') {
      event.preventDefault();
      search.focus();
      search.select();
    } else if (event.key === 'Escape') {
      window.location.href = '/';
    }
  });

  search.addEventListener('input', () => {
    const needle = search.value.trim().toLowerCase();
    for (const category of document.querySelectorAll('.scat')) {
      const text = category.textContent.toLowerCase();
      category.hidden = Boolean(needle) && !text.includes(needle);
      if (needle) category.open = text.includes(needle);
    }
  });
}());
