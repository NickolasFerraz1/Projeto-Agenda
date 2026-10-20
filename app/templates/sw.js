// Service worker do Projeto Agenda (gerado por /sw.js; a versão renova o cache).
const CACHE = "agenda-v{{ VERSAO }}";
const ESTATICOS = [
	"/offline",
	"/manifest.webmanifest",
	"/static/app.css?v={{ VERSAO }}",
	"/static/vendor/htmx-2.0.4.min.js?v={{ VERSAO }}",
	"/static/vendor/alpine-3.14.8.min.js?v={{ VERSAO }}",
	"/static/vendor/sortable-1.15.6.min.js?v={{ VERSAO }}",
	"/static/icons/icon-192.png?v={{ VERSAO }}",
	"/static/icons/icon-512.png",
];

self.addEventListener("install", (e) => {
	e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ESTATICOS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
	e.waitUntil(
		caches.keys()
			.then((nomes) => Promise.all(nomes.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
			.then(() => self.clients.claim())
	);
});

self.addEventListener("fetch", (e) => {
	const req = e.request;
	const url = new URL(req.url);
	if (req.method !== "GET" || url.origin !== location.origin) return;

	// Arquivos estáticos: cache primeiro (as URLs têm ?v=, então mudam a cada versão).
	if (url.pathname.startsWith("/static/")) {
		e.respondWith(caches.match(req).then((r) => r || fetch(req)));
		return;
	}

	// Páginas: sempre da rede (dados atuais); sem rede, a página "sem conexão".
	if (req.mode === "navigate") {
		e.respondWith(fetch(req).catch(() => caches.match("/offline")));
	}
	// API e requisições do HTMX: direto para a rede.
});
