/* Минимальный service worker: делает WebApp устанавливаемым (PWA).
   Кэширования нет — все запросы идут в сеть, поэтому обновления
   подхватываются сразу и «застрявших» старых версий не бывает. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
