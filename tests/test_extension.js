// Run with: node --test tests/test_extension.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function extension(firefox = false) {
  const listeners = {};
  listeners.menus = [];
  const calls = [];
  const events = [];
  const saved = {};
  const items = new Map();
  const chrome = {
    runtime: {
      id: 'test-extension',
      getURL: p => `chrome-extension://test-extension/${p}`,
      onInstalled: { addListener: fn => { listeners.installed = fn; } },
      onStartup: { addListener: fn => { listeners.startup = fn; } },
      onMessage: { addListener: fn => { listeners.message = fn; } },
      sendNativeMessage: async (host, message) => {
        calls.push({ host, message });
        events.push('native:' + message.action);
        return { ok: true, autoCapture: true, message: 'Added to the LinuxDM queue.' };
      }
    },
    contextMenus: {
      removeAll: async () => {},
      create: item => { listeners.menus.push(item); if (item.id === 'linuxdm-download') listeners.menu = item; },
      onClicked: { addListener: fn => { listeners.clicked = fn; } }
    },
    storage: { local: {
      get: async query => {
        if (query === null) return { ...saved };
        if (typeof query === 'string') return { [query]: saved[query] };
        return Object.fromEntries(Object.entries(query).map(([key, value]) => [key, saved[key] ?? value]));
      },
      set: async data => { Object.assign(saved, data); listeners.saved = data; },
      remove: async key => { delete saved[key]; }
    } },
    downloads: {
      onCreated: { addListener: fn => { listeners.created = fn; } },
      onDeterminingFilename: { addListener: fn => { listeners.filename = fn; } },
      pause: async id => { events.push('pause'); items.get(id).paused = true; },
      resume: async id => { events.push('resume'); items.get(id).paused = false; },
      cancel: async id => { events.push('cancel'); items.get(id).state = 'interrupted'; },
      search: async ({ id }) => items.has(id) ? [{ ...items.get(id) }] : []
    },
    tabs: {
      get: async id => ({ id, url: 'https://example.com/watch', title: 'Example video' }),
      onUpdated: { addListener: fn => { listeners.updated = fn; } },
      onRemoved: { addListener: fn => { listeners.removed = fn; } }
    },
    webRequest: { onHeadersReceived: { addListener: fn => { listeners.headers = fn; } } },
    alarms: { create: async () => {}, onAlarm: { addListener: fn => { listeners.alarm = fn; } } },
    action: { setBadgeText: async () => {}, setBadgeBackgroundColor: async () => {}, setTitle: async () => {} }
  };
  const session = {};
  chrome.storage.session = { get: async key => ({ [key]: session[key] }),
    set: async data => Object.assign(session, data), remove: async key => { delete session[key]; } };
  if (firefox) delete chrome.downloads.onDeterminingFilename;
  const context = vm.createContext({ chrome, ...(firefox ? { browser: chrome } : {}), URL, console, crypto: require('node:crypto').webcrypto });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../chrome-extension/background.js'), 'utf8'), context);
  const send = (message, sender = { id: chrome.runtime.id, url: chrome.runtime.getURL('popup.html') }) =>
    new Promise(resolve => listeners.message(message, sender, resolve));
  const start = async (overrides = {}) => {
    const item = { id: 7, state: 'in_progress', paused: false, danger: 'safe',
      url: 'https://example.com/file.zip', finalUrl: 'https://cdn.example.com/file.zip',
      filename: '/home/user/Downloads/archive.zip', mime: 'application/zip', ...overrides };
    items.set(item.id, item);
    await listeners.created({ ...item });
    return item;
  };
  return { chrome, calls, listeners, send, saved, events, start, items,
    recover: () => vm.runInContext('recoverPending()', context) };
}

test('context menu is limited to HTTP(S) links', async () => {
  const ext = extension();
  await ext.listeners.installed();
  assert.equal(ext.listeners.menu.title, 'Download with LinuxDM');
  assert.equal(ext.listeners.menu.contexts.join(','), 'link');
  assert.equal(ext.listeners.menu.targetUrlPatterns.join(','), 'http://*/*,https://*/*');
});

test('valid popup link reaches native host and feedback does not store the URL', async () => {
  const ext = extension();
  const url = 'https://example.com/file.zip?token=private';
  assert.equal((await ext.send({ action: 'download', url })).ok, true);
  assert.equal(ext.calls[0].host, 'io.linuxdm.bridge');
  assert.equal(ext.calls[0].message.url, url);
  assert.equal(JSON.stringify(ext.listeners.saved).includes('private'), false);
});

test('rejects unsupported schemes and foreign senders without contacting host', async () => {
  const ext = extension();
  for (const url of ['file:///etc/passwd', 'javascript:alert(1)', 'blob:https://example.com/id']) {
    assert.equal((await ext.send({ action: 'download', url })).ok, false);
  }
  assert.equal((await ext.send({ action: 'ping' }, { id: 'foreign', url: 'https://example.com' })).ok, false);
  assert.equal(ext.calls.length, 0);
});

test('missing host produces installation guidance', async () => {
  const ext = extension();
  ext.chrome.runtime.sendNativeMessage = async () => { throw new Error('host not found'); };
  const result = await ext.send({ action: 'ping' });
  assert.equal(result.ok, false);
  assert.match(result.message, /installer/);
});


test('automatic capture pauses first, preserves the final URL and filename, and cancels only after acceptance', async () => {
  const ext = extension();
  await ext.start();
  assert.equal(ext.events.join(','), 'native:ping,pause,native:capture,cancel');
  const message = ext.calls.find(call => call.message.action === 'capture').message;
  assert.equal(message.url, 'https://cdn.example.com/file.zip');
  assert.equal(message.filename, 'archive.zip');
  assert.match(message.requestId, /^[a-f0-9]{32}$/);
  assert.equal(ext.saved['capture:7'], undefined);
});

test('rejected capture resumes the original Chrome download', async () => {
  const ext = extension();
  const native = ext.chrome.runtime.sendNativeMessage;
  ext.chrome.runtime.sendNativeMessage = async (host, message) => message.action === 'capture'
    ? { ok: false, message: 'Handoff timed out.' } : native(host, message);
  await ext.start();
  assert.ok(ext.events.includes('pause'));
  assert.ok(ext.events.includes('resume'));
  assert.ok(!ext.events.includes('cancel'));
  assert.equal(ext.saved['capture:7'], undefined);
});

test('capture off, private, dangerous, blob and extension downloads are left alone', async () => {
  for (const overrides of [{ incognito: true }, { danger: 'file' }, { byExtensionId: 'another' },
    { url: 'blob:https://example.com/id', finalUrl: 'blob:https://example.com/id' }, { state: 'complete' }]) {
    const ext = extension();
    await ext.start(overrides);
    assert.deepEqual(ext.events, []);
  }
  const ext = extension();
  ext.saved.captureEnabled = false;
  await ext.start();
  assert.deepEqual(ext.events, []);
});

test('missing native bridge leaves Chrome downloading without pausing', async () => {
  const ext = extension();
  ext.chrome.runtime.sendNativeMessage = async () => { throw new Error('missing host'); };
  await ext.start();
  assert.ok(!ext.events.includes('pause'));
  assert.equal(ext.items.get(7).paused, false);
});

test('download completed before pause is not handed off', async () => {
  const ext = extension();
  ext.chrome.downloads.pause = async () => { throw new Error('already complete'); };
  await ext.start();
  assert.equal(ext.calls.length, 1); // Connection check only.
  assert.equal(ext.saved['capture:7'], undefined);
});

test('lost native response is resolved before deciding whether to resume Chrome', async () => {
  const ext = extension();
  const native = ext.chrome.runtime.sendNativeMessage;
  ext.chrome.runtime.sendNativeMessage = async (host, message) => {
    if (message.action === 'capture') throw new Error('pipe closed');
    if (message.action === 'capture_status') return { ok: true, message: 'Already accepted.' };
    return native(host, message);
  };
  await ext.start();
  assert.ok(ext.events.includes('cancel'));
  assert.ok(!ext.events.includes('resume'));
});

test('service worker recovery resumes an orphaned Chrome pause after rejection', async () => {
  const ext = extension();
  ext.items.set(9, { id: 9, state: 'in_progress', paused: true });
  ext.saved['capture:9'] = { id: 9, requestId: 'a'.repeat(32), created: Date.now() - 60000 };
  ext.chrome.runtime.sendNativeMessage = async () => ({ ok: false, message: 'Not accepted.' });
  await ext.recover();
  assert.deepEqual(ext.events, ['resume']);
  assert.equal(ext.saved['capture:9'], undefined);
});

test('unresolved native failure keeps a recovery record instead of starting a duplicate', async () => {
  const ext = extension();
  const native = ext.chrome.runtime.sendNativeMessage;
  ext.chrome.runtime.sendNativeMessage = async (host, message) => {
    if (message.action !== 'ping') throw new Error('host gone');
    return native(host, message);
  };
  await ext.start();
  assert.equal(ext.items.get(7).paused, true);
  assert.ok(ext.saved['capture:7']);
  assert.ok(!ext.events.includes('resume'));
  assert.ok(!ext.events.includes('cancel'));
});

test('filename determination shares the handoff and always releases Chrome', async () => {
  const ext = extension();
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const native = ext.chrome.runtime.sendNativeMessage;
  ext.chrome.runtime.sendNativeMessage = async (host, message) => {
    if (message.action === 'capture') await gate;
    return native(host, message);
  };
  const started = ext.start();
  let suggestions = 0;
  const released = new Promise(resolve => {
    assert.equal(ext.listeners.filename({ ...ext.items.get(7) }, () => { suggestions++; resolve(); }), true);
  });
  await new Promise(setImmediate);
  assert.equal(suggestions, 0);
  release();
  await started;
  await released;
  assert.equal(suggestions, 1);
  assert.equal(ext.calls.filter(call => call.message.action === 'capture').length, 1);
});

test('streaming video popup sends a video request with its page title', async () => {
  const ext = extension();
  const result = await ext.send({ action: 'video', url: 'https://www.youtube.com/watch?v=example', title: 'A video' });
  assert.equal(result.ok, true);
  assert.equal(ext.calls[0].message.action, 'video');
  assert.equal(ext.calls[0].message.title, 'A video');
  assert.equal(ext.calls[0].message.url, 'https://www.youtube.com/watch?v=example');
});

test('page context menu sends the page URL rather than a blob video source', async () => {
  const ext = extension();
  await ext.listeners.installed();
  assert.ok(ext.listeners.menus.find(menu => menu.id === 'linuxdm-video-page'));
  await ext.listeners.clicked({ menuItemId: 'linuxdm-video-page', pageUrl: 'https://example.com/watch',
    srcUrl: 'blob:https://example.com/123' }, { title: 'Page video', url: 'https://example.com/watch' });
  assert.equal(ext.calls[0].message.action, 'video');
  assert.equal(ext.calls[0].message.url, 'https://example.com/watch');
});


test('detected videos are scoped to the tab and deduplicated, without a native download', async () => {
  const ext = extension();
  const sender = { id: ext.chrome.runtime.id, url: 'https://example.com/watch', frameId: 0, tab: { id: 4 } };
  const video = { url: 'https://cdn.example.com/movie.mp4', title: 'Movie', label: 'Video' };
  assert.equal((await ext.send({ action: 'detected', page: sender.url, videos: [video, video] }, sender)).ok, true);
  const list = await ext.send({ action: 'videos', tabId: 4 });
  assert.equal(list.videos.length, 1);
  assert.equal(list.videos[0].url, video.url);
  assert.equal((await ext.send({ action: 'videos', tabId: 5 })).videos.length, 0);
  assert.equal(ext.calls.length, 0);
  assert.equal(JSON.stringify(ext.saved).includes('movie.mp4'), false);
  ext.listeners.updated(4, { url: 'https://example.com/next' });
  assert.equal((await ext.send({ action: 'videos', tabId: 4 })).videos.length, 0);
});

test('passive network detection finds manifests and ignores media fragments', async () => {
  const ext = extension();
  ext.listeners.headers({ tabId: 4, statusCode: 200, url: 'https://cdn.example.com/live.m3u8', responseHeaders: [] });
  ext.listeners.headers({ tabId: 4, statusCode: 200, url: 'https://cdn.example.com/segment.ts',
    responseHeaders: [{ name: 'Content-Type', value: 'video/mp2t' }] });
  ext.listeners.headers({ tabId: 4, statusCode: 206, url: 'https://r.googlevideo.com/videoplayback',
    responseHeaders: [{ name: 'Content-Type', value: 'video/mp4' }] });
  const reply = await ext.send({ action: 'videos', tabId: 4 });
  assert.equal(reply.videos.length, 1);
  assert.equal(reply.videos[0].label, 'Streaming video');
  ext.listeners.removed(4);
  assert.equal((await ext.send({ action: 'videos', tabId: 4 })).videos.length, 0);
});

test('detection rejects private tabs and forged page reports', async () => {
  const ext = extension();
  const sender = { id: ext.chrome.runtime.id, url: 'https://example.com/watch', frameId: 0, tab: { id: 4, incognito: true } };
  const message = { action: 'detected', page: sender.url, videos: [{ url: 'https://example.com/a.mp4' }] };
  assert.equal((await ext.send(message, sender)).ok, false);
  sender.tab.incognito = false;
  assert.equal((await ext.send({ ...message, page: 'https://forged.example' }, sender)).ok, false);
  assert.equal((await ext.send(message)).ok, false);
  assert.equal((await ext.send({ action: 'videos', tabId: 4 })).videos.length, 0);
});

test('content detector recognizes YouTube and follows SPA navigation without copying URLs', () => {
  const messages = [];
  let poll;
  const location = { href: 'https://www.youtube.com/watch?v=first' };
  const document = { title: 'First movie', documentElement: {},
    querySelectorAll: () => [{ currentSrc: 'blob:https://www.youtube.com/media', src: '', querySelectorAll: () => [] }],
    addEventListener: () => {} };
  const context = vm.createContext({ URL, location, document, Date,
    chrome: { runtime: { sendMessage: async message => messages.push(message) } },
    window: { addEventListener: () => {} }, MutationObserver: class { observe() {} },
    setInterval: fn => { poll = fn; }, setTimeout: () => {}, clearTimeout: () => {} });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../chrome-extension/detect.js'), 'utf8'), context);
  assert.equal(messages[0].videos[0].url, location.href);
  assert.equal(messages[0].videos[0].label, 'YouTube video');
  location.href = 'https://www.youtube.com/watch?v=second';
  document.title = 'Second movie';
  poll();
  assert.equal(messages[1].videos[0].url, location.href);
  assert.equal(messages[1].videos[0].title, 'Second movie');
});

test('content detector collects real player sources and rejects browser-only URLs', () => {
  const messages = [];
  const document = { title: 'Movie page', documentElement: {},
    querySelectorAll: () => [
      { currentSrc: 'https://cdn.example/movie.mp4', src: 'https://cdn.example/movie.mp4', querySelectorAll: () => [] },
      { currentSrc: 'data:video/mp4;base64,AAAA', src: '', querySelectorAll: () => [] }
    ], addEventListener: () => {} };
  const context = vm.createContext({ URL, location: { href: 'https://example.com/watch' }, document, Date,
    chrome: { runtime: { sendMessage: async message => messages.push(message) } },
    window: { addEventListener: () => {} }, MutationObserver: class { observe() {} },
    setInterval: () => {}, setTimeout: () => {}, clearTimeout: () => {} });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../chrome-extension/detect.js'), 'utf8'), context);
  assert.equal(messages[0].videos.length, 1);
  assert.equal(messages[0].videos[0].url, 'https://cdn.example/movie.mp4');
});

test('YouTube appears on an already-open tab with no content script or stored detections', async () => {
  const ext = extension();
  ext.chrome.tabs.get = async id => ({ id, url: 'https://www.youtube.com/watch?v=aqz-KE-bpKQ&list=example&t=30', title: 'Big Buck Bunny' });
  const reply = await ext.send({ action: 'videos', tabId: 4 });
  assert.equal(reply.videos.length, 1);
  assert.equal(reply.videos[0].url, 'https://www.youtube.com/watch?v=aqz-KE-bpKQ');
  assert.equal(reply.videos[0].title, 'Big Buck Bunny');
  assert.equal(ext.calls.length, 0);
  await ext.send({ action: 'video', ...reply.videos[0] });
  assert.equal(ext.calls[0].message.url, reply.videos[0].url);
});

test('YouTube SPA navigation immediately replaces the detected video without a page report', async () => {
  const ext = extension();
  let current = 'https://www.youtube.com/watch?v=aqz-KE-bpKQ';
  ext.chrome.tabs.get = async id => ({ id, url: current, title: 'Current video' });
  assert.equal((await ext.send({ action: 'videos', tabId: 4 })).videos.length, 1);
  current = 'https://www.youtube.com/shorts/BaW_jenozKc';
  ext.listeners.updated(4, { url: current });
  const reply = await ext.send({ action: 'videos', tabId: 4 });
  assert.equal(reply.videos.length, 1);
  assert.equal(reply.videos[0].url, 'https://www.youtube.com/watch?v=BaW_jenozKc');
  current = 'https://www.youtube.com/';
  ext.listeners.updated(4, { url: current });
  assert.equal((await ext.send({ action: 'videos', tabId: 4 })).videos.length, 0);
});

test('YouTube detection supports mobile, live, embedded and short URLs but rejects lookalikes and private tabs', async () => {
  const ext = extension();
  for (const url of ['https://m.youtube.com/watch?v=aqz-KE-bpKQ', 'https://youtu.be/aqz-KE-bpKQ',
      'https://www.youtube.com/live/aqz-KE-bpKQ', 'https://www.youtube-nocookie.com/embed/aqz-KE-bpKQ']) {
    ext.chrome.tabs.get = async id => ({ id, url });
    const reply = await ext.send({ action: 'videos', tabId: 4 });
    assert.equal(reply.videos[0].url, 'https://www.youtube.com/watch?v=aqz-KE-bpKQ', url);
  }
  for (const url of ['https://notyoutube.com/watch?v=aqz-KE-bpKQ',
      'https://youtube.com.example.com/watch?v=aqz-KE-bpKQ', 'https://www.youtube.com/watch?v=bad',
      'https://www.youtube.com/playlist?list=abc']) {
    ext.chrome.tabs.get = async id => ({ id, url });
    assert.equal((await ext.send({ action: 'videos', tabId: 4 })).videos.length, 0, url);
  }
  ext.chrome.tabs.get = async id => ({ id, url: 'https://www.youtube.com/watch?v=aqz-KE-bpKQ', incognito: true });
  assert.equal((await ext.send({ action: 'videos', tabId: 4 })).videos.length, 0);
});


test('Firefox background works without Chromium filename event and uses browser promises', async () => {
  const ext = extension(true);
  await ext.listeners.installed();
  assert.equal(ext.listeners.menus.length, 3);
  assert.equal(ext.listeners.filename, undefined);
  const item = await ext.start();
  assert.equal(item.state, 'interrupted');
  assert.ok(ext.calls.some(call => call.message.action === 'capture'));
  const result = await ext.send({ action: 'video', url: 'https://www.youtube.com/watch?v=aqz-KE-bpKQ' });
  assert.equal(result.ok, true);
});
