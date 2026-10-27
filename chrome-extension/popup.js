const api = typeof browser !== 'undefined' ? browser : chrome;
const connection = document.querySelector('#connection');
const result = document.querySelector('#result');
const captureToggle = document.querySelector('#capture-enabled');
const videos = document.querySelector('#videos');
captureToggle.disabled = true;

function showResult(reply) {
  result.textContent = reply.message;
  result.classList.toggle('error', !reply.ok);
}

async function initialize() {
  const saved = await api.storage.local.get({ lastResult: null, captureEnabled: true });
  captureToggle.checked = saved.captureEnabled;
  captureToggle.disabled = false;
  if (saved.lastResult) showResult(saved.lastResult);
  const reply = await api.runtime.sendMessage({ action: 'ping' });
  connection.textContent = reply.ok ? '● Desktop bridge connected' : reply.message;
  connection.classList.toggle('error', !reply.ok);
}
initialize().catch(() => {
  connection.textContent = 'Connection check failed. Reload the extension and try again.';
  connection.classList.add('error');
});

async function refreshVideos() {
  const [tab] = await api.tabs.query({ active: true, currentWindow: true });
  const reply = tab ? await api.runtime.sendMessage({ action: 'videos', tabId: tab.id }) : { videos: [] };
  const items = reply.videos || [];
  const fingerprint = JSON.stringify(items);
  if (videos.dataset.items === fingerprint) return;
  videos.dataset.items = fingerprint;
  videos.replaceChildren();
  if (!items.length) {
    const empty = document.createElement('p');
    empty.textContent = 'No videos detected yet. Play a video on this page. After reloading the extension, reload the page too.';
    videos.append(empty);
  }
  for (const item of items) {
    const row = document.createElement('div');
    row.className = 'video-row';
    const title = document.createElement('strong');
    title.textContent = item.title || 'Detected video';
    const label = document.createElement('small');
    label.textContent = item.label;
    const button = document.createElement('button');
    button.textContent = 'Download';
    button.addEventListener('click', async () => {
      button.disabled = true;
      try { showResult(await api.runtime.sendMessage({ action: 'video', url: item.url, title: item.title })); }
      catch { showResult({ ok: false, message: 'Could not contact LinuxDM.' }); }
      finally { button.disabled = false; }
    });
    row.append(title, label, button);
    videos.append(row);
  }
}
refreshVideos().catch(() => { videos.textContent = 'Open a video page to detect videos.'; });
setInterval(() => refreshVideos().catch(() => {}), 1000);

captureToggle.addEventListener('change', async () => {
  captureToggle.disabled = true;
  try {
    await api.storage.local.set({ captureEnabled: captureToggle.checked });
    showResult({ ok: true, message: captureToggle.checked
      ? 'New supported downloads will open in LinuxDM.'
      : 'New downloads will stay in Chrome. Downloads already handed off continue in LinuxDM.' });
  } catch {
    captureToggle.checked = !captureToggle.checked;
    showResult({ ok: false, message: 'Could not save the setting. Try again.' });
  } finally { captureToggle.disabled = false; }
});
