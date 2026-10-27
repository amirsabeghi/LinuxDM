const api = typeof browser !== 'undefined' ? browser : chrome;
// Runs in Chrome's isolated world. Detect media without altering the page/player.
(() => {
  let previous = '';
  let reported = 0;
  function scan() {
    const videos = [...document.querySelectorAll('video')];
    const page = new URL(location.href);
    const youtube = /(^|\.)youtube\.com$/.test(page.hostname) &&
      (page.pathname === '/watch' && page.searchParams.has('v') || /^\/(shorts|embed)\//.test(page.pathname));
    const candidates = [];
    const add = (url, label) => {
      try {
        const parsed = new URL(url, location.href);
        if (!/^https?:$/.test(parsed.protocol)) return;
        if (!candidates.some(item => item.url === parsed.href))
          candidates.push({ url: parsed.href, title: document.title.slice(0, 512), label });
      } catch { /* Empty or browser-only media source. */ }
    };
    if (youtube) add(page.href, 'YouTube video');
    else for (const video of videos) {
      const sources = [video.currentSrc, video.src, ...[...video.querySelectorAll('source')].map(s => s.src)].filter(Boolean);
      for (const src of sources) {
        if (src.startsWith('blob:')) add(page.href, 'Video page');
        else add(src, 'Video');
      }
      if (!sources.length) add(page.href, 'Video page');
    }
    const message = { action: 'detected', page: page.href, videos: candidates.slice(0, 20) };
    const fingerprint = JSON.stringify(message);
    if (fingerprint === previous && Date.now() - reported < 10000) return;
    reported = Date.now();
    previous = fingerprint;
    api.runtime.sendMessage(message).catch(() => {});
  }
  let timer;
  const schedule = () => { clearTimeout(timer); timer = setTimeout(scan, 250); };
  new MutationObserver(schedule).observe(document.documentElement,
    { childList: true, subtree: true, attributes: true, attributeFilter: ['src'] });
  document.addEventListener('loadedmetadata', schedule, true);
  document.addEventListener('play', schedule, true);
  document.addEventListener('yt-navigate-finish', schedule);
  window.addEventListener('popstate', schedule);
  // Also covers players using pushState without changing their DOM.
  setInterval(scan, 2000);
  scan();
})();
