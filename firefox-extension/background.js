const api = typeof browser !== 'undefined' ? browser : chrome;
const HOST = 'io.linuxdm.bridge';
const RECOVERY_ALARM = 'linuxdm-recover';
const CAPTURE_PREFIX = 'capture:';
const activeCaptures = new Set();
const captureTasks = new Map();

api.runtime.onInstalled.addListener(async () => {
  await api.contextMenus.removeAll();
  {
    api.contextMenus.create({
      id: 'linuxdm-download', title: 'Download with LinuxDM', contexts: ['link'],
      targetUrlPatterns: ['http://*/*', 'https://*/*']
    });
    api.contextMenus.create({ id: 'linuxdm-video-page', title: 'Download video from this page',
      contexts: ['page', 'video'], documentUrlPatterns: ['http://*/*', 'https://*/*'] });
    api.contextMenus.create({ id: 'linuxdm-video-link', title: 'Download linked video with LinuxDM',
      contexts: ['link'], targetUrlPatterns: ['http://*/*', 'https://*/*'] });
  }
  api.alarms.create(RECOVERY_ALARM, { periodInMinutes: 1 });
});

function validUrl(value) {
  try {
    const url = new URL(value);
    return typeof value === 'string' && value.length <= 16384 &&
      !/[\x00-\x1f]/.test(value) && ['http:', 'https:'].includes(url.protocol);
  } catch { return false; }
}

async function request(message) {
  if (!['download', 'video', 'capture', 'capture_status', 'ping'].includes(message?.action) ||
      (['download', 'video', 'capture'].includes(message.action) && !validUrl(message.url))) {
    return { ok: false, message: 'Enter a valid HTTP or HTTPS download link.' };
  }
  try {
    const result = await api.runtime.sendNativeMessage(HOST, message);
    if (typeof result?.ok !== 'boolean' || typeof result.message !== 'string') throw new Error('Invalid response');
    return result;
  } catch {
    return { ok: false, connectionError: true,
      message: 'Cannot reach LinuxDM. Open the desktop app or run the bridge installer, then try again.' };
  }
}

async function feedback(result) {
  // Never persist URLs, which may contain private download tokens.
  await api.storage.local.set({ lastResult: result });
  await api.action.setBadgeText({ text: result.ok ? (result.pending ? '…' : '✓') : '!' });
  await api.action.setBadgeBackgroundColor({ color: result.ok ? '#b58a32' : '#b73c3c' });
  await api.action.setTitle({ title: `LinuxDM: ${result.message}` });
}

async function download(url, kind = 'download', title = '') {
  const result = await request({ action: kind, url, ...(kind === 'video' ? { title: String(title).slice(0, 512) } : {}) });
  await feedback(result);
  return result;
}

function eligible(item) {
  return item.state === 'in_progress' && !item.paused && !item.incognito &&
    !item.byExtensionId && item.danger === 'safe' && validUrl(item.finalUrl || item.url);
}

async function finishCapture(record, result) {
  const key = CAPTURE_PREFIX + record.id;
  if (result.connectionError) {
    // Ownership is uncertain: do not start a second copy. The watchdog retries.
    await feedback({ ok: false, message: 'Handoff is being checked. This Chrome download is paused; keep LinuxDM available.' });
    return;
  }
  const [item] = await api.downloads.search({ id: record.id });
  if (item?.state === 'in_progress' || (item?.state === 'interrupted' && item.canResume)) {
    try {
      if (result.ok) await api.downloads.cancel(record.id);
      else if (item.paused || item.state === 'interrupted') await api.downloads.resume(record.id);
    } catch {
      await feedback({ ok: false, message: 'Chrome could not finish the handoff. Check the paused download in Chrome; recovery will retry.' });
      return;
    }
  }
  await api.storage.local.remove(key);
  await feedback(result.ok ? result : { ok: false, message: 'LinuxDM could not accept this download. It remains in Chrome.' });
}

async function recoverCapture(record) {
  const result = await request({ action: 'capture_status', requestId: record.requestId });
  await finishCapture(record, result);
}

async function capture(item) {
  if (!eligible(item) || activeCaptures.has(item.id)) return;
  activeCaptures.add(item.id);
  try {
    const settings = await api.storage.local.get({ captureEnabled: true });
    if (!settings.captureEnabled) return;
    const ping = await request({ action: 'ping' });
    if (!ping.ok || !ping.autoCapture) {
      await feedback({ ok: false, message: 'LinuxDM is unavailable or needs an update. This download stays in Chrome.' });
      return;
    }
    const record = { id: item.id, requestId: crypto.randomUUID().replaceAll('-', ''), created: Date.now() };
    const key = CAPTURE_PREFIX + item.id;
    // Persist before pausing, so a service-worker restart cannot strand a download.
    await api.storage.local.set({ [key]: record });
    await api.alarms.create(RECOVERY_ALARM, { periodInMinutes: 1 });
    try {
      await api.downloads.pause(item.id);
    } catch {
      await api.storage.local.remove(key); // Already completed or interrupted: keep Chrome's copy.
      return;
    }
    const [current] = await api.downloads.search({ id: item.id });
    if (!current || current.state !== 'in_progress' || !current.paused) {
      await api.storage.local.remove(key);
      return;
    }
    if (current.danger !== 'safe' || !validUrl(current.finalUrl || current.url)) {
      await finishCapture(record, { ok: false });
      return;
    }
    const result = await request({ action: 'capture', requestId: record.requestId,
      url: current.finalUrl || current.url,
      filename: (current.filename || '').split(/[\\/]/).pop(), mime: current.mime || '' });
    if (result.connectionError) await recoverCapture(record);
    else await finishCapture(record, result);
  } finally {
    activeCaptures.delete(item.id);
  }
}

async function recoverPending() {
  const all = await api.storage.local.get(null);
  for (const [key, record] of Object.entries(all)) {
    if (!key.startsWith(CAPTURE_PREFIX) || activeCaptures.has(record.id) || Date.now() - record.created < 30000) continue;
    activeCaptures.add(record.id);
    try { await recoverCapture(record); }
    finally { activeCaptures.delete(record.id); }
  }
}

function beginCapture(item) {
  if (!captureTasks.has(item.id)) {
    const task = capture(item).finally(() => captureTasks.delete(item.id));
    captureTasks.set(item.id, task);
  }
  return captureTasks.get(item.id);
}

api.downloads.onCreated.addListener(item => beginCapture(item).catch(console.error));
api.downloads.onDeterminingFilename?.addListener((item, suggest) => {
  // Keep even small files from completing while the shared handoff is in flight.
  // We do not change Chrome's filename; release its decision on every outcome.
  beginCapture(item).catch(console.error).finally(() => suggest());
  return true;
});
api.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === RECOVERY_ALARM) recoverPending().catch(console.error);
});
api.runtime.onStartup.addListener(() => {
  api.alarms.create(RECOVERY_ALARM, { periodInMinutes: 1 });
  recoverPending().catch(console.error);
});
api.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === 'linuxdm-download') download(info.linkUrl).catch(console.error);
  if (info.menuItemId === 'linuxdm-video-page') return download(info.pageUrl || tab?.url, 'video', tab?.title || '').catch(console.error);
  if (info.menuItemId === 'linuxdm-video-link') return download(info.linkUrl, 'video').catch(console.error);
});
// Derive YouTube videos directly from Chrome's current tab URL. This also works
// on already-open tabs after an extension reload, without a content-script report.
function youtubeVideo(tab) {
  if (tab.incognito || !validUrl(tab.url)) return null;
  const page = new URL(tab.url);
  const host = page.hostname.toLowerCase();
  let id;
  if (host === 'youtu.be') id = page.pathname.split('/')[1];
  else if (host === 'youtube.com' || host.endsWith('.youtube.com') ||
           host === 'youtube-nocookie.com' || host.endsWith('.youtube-nocookie.com')) {
    if (page.pathname === '/watch') id = page.searchParams.get('v');
    else id = page.pathname.match(/^\/(?:shorts|embed|live)\/([^/]+)/)?.[1];
  }
  if (!id || !/^[a-zA-Z0-9_-]{11}$/.test(id)) return null;
  return { url: `https://www.youtube.com/watch?v=${id}`,
    title: String(tab.title || 'YouTube video').slice(0, 512), label: 'YouTube video' };
}

// Keep signed media URLs in session memory only, scoped to their browser tab.
const videoTasks = new Map();
function videoTask(tabId, operation) {
  const task = (videoTasks.get(tabId) || Promise.resolve()).catch(() => {}).then(operation);
  videoTasks.set(tabId, task);
  task.finally(() => { if (videoTasks.get(tabId) === task) videoTasks.delete(tabId); }).catch(() => {});
  return task;
}
async function videoState(tabId) {
  const key = `videos:${tabId}`;
  return (await api.storage.session.get(key))[key] || { page: '', frames: {}, streams: [] };
}
function videoList(state) {
  const result = [];
  for (const item of [...Object.values(state.frames).flat(), ...state.streams]) {
    if (!result.some(v => v.url === item.url)) result.push(item);
  }
  return result.slice(0, 30);
}
async function saveVideos(tabId, state) {
  await api.storage.session.set({ [`videos:${tabId}`]: state });
  const count = videoList(state).length;
  await api.action.setBadgeText({ tabId, text: count ? String(count) : '' });
  await api.action.setBadgeBackgroundColor({ tabId, color: '#e9bd55' });
}
async function recordVideos(message, sender) {
  if (sender.tab.incognito || !validUrl(sender.url) || message.page !== sender.url || !Array.isArray(message.videos))
    return { ok: false };
  return videoTask(sender.tab.id, async () => {
    const tab = await api.tabs.get(sender.tab.id);
    if (sender.frameId === 0 && message.page !== tab.url) return { ok: false };
    const state = await videoState(tab.id);
    if (state.page !== tab.url) { state.frames = {}; state.streams = []; }
    state.page = tab.url;
    state.frames[sender.frameId || 0] = message.videos.slice(0, 20)
      .filter(item => item && validUrl(item.url)).map(item => ({ url: item.url,
        title: String(item.title || tab.title || 'Detected video').slice(0, 512),
        label: String(item.label || 'Video').slice(0, 40) }));
    await saveVideos(tab.id, state);
    return { ok: true };
  });
}
api.webRequest.onHeadersReceived.addListener(details => {
  if (details.tabId < 0 || details.statusCode < 200 || details.statusCode >= 300 || !validUrl(details.url)) return;
  const mime = (details.responseHeaders || []).find(h => h.name.toLowerCase() === 'content-type')?.value?.split(';')[0].trim().toLowerCase() || '';
  const manifest = /(?:mpegurl|dash\+xml)/.test(mime) || /\.(m3u8|mpd)(?:\?|$)/i.test(details.url);
  const file = /^(video\/(mp4|webm|ogg|quicktime))$/.test(mime);
  if (!manifest && !file) return;
  // YouTube's individual audio/video ranges are not standalone movies; the page detector supplies its extractor URL.
  if (/(^|\.)googlevideo\.com$/.test(new URL(details.url).hostname)) return;
  videoTask(details.tabId, async () => {
    const tab = await api.tabs.get(details.tabId);
    if (tab.incognito || !validUrl(tab.url)) return;
    const state = await videoState(tab.id);
    if (state.page !== tab.url) { state.frames = {}; state.streams = []; }
    state.page = tab.url;
    if (!state.streams.some(v => v.url === details.url)) state.streams.push({ url: details.url,
      title: tab.title || 'Detected video', label: manifest ? 'Streaming video' : 'Video file' });
    state.streams = state.streams.slice(-20);
    await saveVideos(tab.id, state);
  }).catch(() => {});
}, { urls: ['http://*/*', 'https://*/*'] }, ['responseHeaders']);
api.tabs.onRemoved.addListener(tabId => {
  videoTask(tabId, () => api.storage.session.remove(`videos:${tabId}`)).catch(() => {});
});
api.tabs.onUpdated.addListener((tabId, change) => {
  if (change.url || change.status === 'loading' || change.status === 'complete') videoTask(tabId, async () => {
    if (change.url || change.status === 'loading') await api.storage.session.remove(`videos:${tabId}`);
    const tab = await api.tabs.get(tabId);
    const youtube = youtubeVideo(tab);
    const state = await videoState(tabId);
    const count = youtube ? 1 : state.page === tab.url ? videoList(state).length : 0;
    await api.action.setBadgeText({ tabId, text: count ? String(count) : '' });
    await api.action.setBadgeBackgroundColor({ tabId, color: '#e9bd55' });
  }).catch(() => {});
});

api.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id === api.runtime.id && sender.tab && message?.action === 'detected') {
    recordVideos(message, sender).then(respond, () => respond({ ok: false }));
    return true;
  }
  if (sender.id === api.runtime.id && sender.url === api.runtime.getURL('popup.html') && message?.action === 'videos') {
    videoTask(message.tabId, async () => {
      const tab = await api.tabs.get(message.tabId);
      const state = await videoState(message.tabId);
      const youtube = youtubeVideo(tab);
      // On YouTube, use the current page rather than stale player reports or ad streams.
      const videos = youtube ? [youtube] : !tab.incognito && state.page === tab.url ? videoList(state) : [];
      await api.action.setBadgeText({ tabId: tab.id, text: videos.length ? String(videos.length) : '' });
      return { ok: true, videos };
    }).then(respond, () => respond({ ok: false, videos: [] }));
    return true;
  }
  if (sender.id !== api.runtime.id || sender.url !== api.runtime.getURL('popup.html') ||
      !['download', 'video', 'ping'].includes(message?.action)) {
    respond({ ok: false, message: 'Unsupported sender or request.' });
    return false;
  }
  const operation = ['download', 'video'].includes(message.action)
    ? download(message.url, message.action, message.title || '') : request(message);
  operation.then(respond, () => respond({ ok: false, message: 'Could not send the link. Please try again.' }));
  return true;
});
