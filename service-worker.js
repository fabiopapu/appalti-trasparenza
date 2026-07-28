// Service worker minimale: necessario perché Chrome/Edge/Opera considerino
// il sito "installabile", ma non fa alcun caching — lascia passare le
// richieste di rete normalmente.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', () => self.clients.claim());
self.addEventListener('fetch', (evento) => {
  evento.respondWith(fetch(evento.request));
});
