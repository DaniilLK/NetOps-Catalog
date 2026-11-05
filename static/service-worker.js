// Service worker: кэширует только статическую оболочку сайта.
// Запросы к API (/api/*) и всё, что не GET, никогда не кэшируются —
// иначе можно отдать пользователю чужие/устаревшие данные.

const CACHE_NAME = 'netops-shell-v1';

const SHELL_ASSETS = [
    '/',
    '/index.html',
    '/main.css',
    '/main.js',
    '/manifest.json',
    '/icons/icon-192.png',
    '/icons/icon-512.png',
    '/icons/apple-touch-icon-180.png'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.addAll(SHELL_ASSETS))
            .catch(() => {})
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(
                keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
            ))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (event) => {
    const request = event.request;

    // Кэшируем только простые GET-запросы своего origin
    if (request.method !== 'GET') return;
    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return;
    if (url.pathname.startsWith('/api/')) return;

    // Сеть в приоритете (свежие версии файлов), кэш — только при сбое сети
    event.respondWith(
        fetch(request)
            .then((response) => {
                if (response && response.ok) {
                    const copy = response.clone();
                    caches.open(CACHE_NAME)
                        .then((cache) => cache.put(request, copy))
                        .catch(() => {});
                }
                return response;
            })
            .catch(() => caches.match(request).then((cached) => {
                if (cached) return cached;
                if (request.mode === 'navigate') return caches.match('/index.html');
                return Response.error();
            }))
    );
});
