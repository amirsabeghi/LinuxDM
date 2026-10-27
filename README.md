# LinuxDM

A native Linux download manager built with Python and Tk. Includes persistent named queues, configurable concurrent downloads, up to 16 connections per file, streaming-video downloads, pause/resume, progress and speed reporting, and safe destination naming.

The desktop uses a compact charcoal-and-yellow theme: 30-pixel rows, 12-pixel body text, and a 1080×640 default window that can shrink to 900×560. The Chrome popup uses the same theme.

## Run

From this directory:

```sh
python3 -m linuxdm
```

Requires Python 3.10+ and Tkinter (on Debian/Ubuntu: `sudo apt install python3-tk`). Ordinary file downloads have no pip dependencies. Streaming-video downloads additionally use the `yt-dlp` and `ffmpeg` executables, plus Deno or another supported JavaScript runtime for full YouTube support. These are already installed on this machine.

Click **New download** (Ctrl+N), paste an HTTP or HTTPS file URL, choose the destination and connection count, and click **Add to queue**. Use the sidebar to filter downloads or search by filename (Ctrl+F). The summary cards show combined speed, active transfers, and queued jobs. **Downloaded** shows bytes received so far; **Total size** shows the full file size, or a dash when it is unknown.

Press **Ctrl+A** with the download list focused to select all currently visible rows (respecting queue, status, and search filters). Select one or more rows to use **Pause** or **Resume** below the list. **Pause all** and **Resume all** apply to the selected named queue (or all queues when **All queues** is selected), including downloads hidden by status/search filters. Failed downloads can be retried with the same Resume control. The selected download's progress, destination, queue, and resume support appear in the detail panel. Controls are enabled only when the action is available.

**Remove selected** (or Delete while the list has focus) removes selected queue entries and their temporary download data. Active entries show **Removing** until their connections stop. Completed destination files are preserved. **Clear completed** removes completed entries within the selected queue (or all queues), including ones hidden by status/search filters, while leaving unfinished downloads and saved files in place.

Pausing shows **Pausing** until the connections stop. Clicking Resume during that time schedules the restart automatically; it shows **Resuming** until the old connections finish. Closing the window keeps LinuxDM running in the background with downloads and Chrome capture active. Reopen it from the application menu to restore the same window. Choose **App ▾ → Quit LinuxDM** to stop active transfers safely and save their state. Jobs run in insertion order, with two simultaneous downloads by default. The concurrency control changes that limit. Queue state and partial files are kept in `~/.local/share/linuxdm`. Interrupted jobs reopen paused.

Multiple connections require server support for byte ranges. Resume also requires an ETag or Last-Modified validator so partial files can be checked against the remote resource; otherwise downloads restart safely. Servers without range support use a single connection. Each connection has a 20-second socket timeout; pausing may take until an ongoing read finishes. Retry failed downloads manually with **Resume / Retry**.

This is an initial implementation. Authentication UI, timed scheduling, bandwidth limits, automatic retry, packaging, and update distribution are future work. Torrent downloads are not supported.

## Linux application and background operation

Install the per-user application launcher (no sudo):

```sh
python3 -m linuxdm.desktop_install
```

Search for **LinuxDM** in your Linux application menu. It launches the desktop app, or restores the existing window if it is already running. Closing the window keeps downloads running; **App ▾ → Quit LinuxDM** exits. LinuxDM has one application-menu entry. To start without a window, use its **Start in background** launcher action. The command-line equivalent is `python3 -m linuxdm --background`. Open **LinuxDM** to show the running app. While running, its panel/tray icon offers **Open LinuxDM** and **Quit LinuxDM**. Closing the window leaves the icon and downloads running; Quit safely stops transfers and removes the icon. Chrome confirmation dialogs still appear when a new download needs your choice.

Enable **App ▾ → Start in background at login** to start it automatically in your graphical desktop session. Turn that switch off to disable login startup. This preference is off initially and uses the standard per-user `~/.config/autostart/io.linuxdm.desktop` entry (or `$XDG_CONFIG_HOME/autostart`). No system service is required. Background operation continues while you are logged in; it cannot download while the computer is asleep or shut down. Saved interrupted downloads still reopen paused, so login startup does not silently resume them.

The tray uses PyGObject, GTK 3, and Ayatana AppIndicator (with legacy AppIndicator fallback), already available on this machine. On Debian/Ubuntu these are provided by `python3-gi`, `gir1.2-gtk-3.0`, and `gir1.2-ayatanaappindicator3-0.1`. Your desktop panel must support AppIndicator/StatusNotifier icons; some GNOME installations require the AppIndicator extension. If tray support is unavailable, the download app still works and its application-menu entry restores the window. The indicator shares Tk's main thread through nonblocking GLib event dispatch.

Right-click one or more download rows for **Pause**, **Resume**, **Remove**, **Open directory**, and **Move to queue**. Shift+F10 opens the same menu for selected rows. Remove preserves completed files. Open directory uses your default file manager.

There is no LinuxDM website or local web server. The small Chrome popup is only an extension control panel; transfers run in the native app. The launcher is installed under `~/.local/share/applications/io.linuxdm.desktop` with an icon and a wrapper pointing to this project. Rerun the installer if you move the project. To uninstall the launchers, first turn off login startup in the App menu, then remove that desktop file, `~/.local/share/linuxdm/linuxdm`, and `~/.local/share/icons/hicolor/128x128/apps/io.linuxdm.png`.

## Download categories

New downloads automatically suggest a subfolder under `~/Downloads`: **Videos**, **Music**, **Documents**, **Pictures**, **Archives**, **Programs**, or **Other**. Streaming video downloads always suggest Videos. File downloads use the filename extension (Chrome's suggested filename takes precedence over the URL); unknown extensions use Other. Folders are created when needed.

The **Category** selector in both the new-download and Chrome confirmation dialogs defaults to **Automatic**. Select a category to change its suggested destination, or edit **Save to** / use **Browse** for a custom folder. Changing the URL or filename will not overwrite a custom folder; explicitly choosing a category applies that category's default folder again. Existing downloads keep their destinations. Categories determine folders independently of named queues.

## Named queues

Use **Manage queues…** in the sidebar to create a custom name, rename a queue, or set its concurrency limit. Choose a queue in the sidebar to filter its downloads and see its speed and counts. **Pause queue** stops that queue's current transfers and holds new entries; **Resume queue** releases it and resumes transfers that the queue control paused. Downloads you paused individually stay paused.

Choose a queue when adding a download or in the incoming Chrome dialog. To reorganize existing entries, select them and use **Move to queue…** at the bottom. Deleting a queue moves its entries to **Default** without deleting downloads. Existing installations' downloads are assigned to Default automatically.

The **Overall download limit** caps all active downloads together. Each queue also obeys its own limit; runnable queues take turns filling available slots, with insertion order preserved inside each queue. Lowering a limit affects new starts; already active transfers can finish. Names, limits, assignments, and queue pause state survive app restarts in `queues.json` and `queue.json` under the app's state directory.

## Streaming videos and YouTube

In Chrome, open or play a video, then click the LinuxDM extension. Its **Videos on this page** list automatically detects YouTube watch/shorts/live/embed pages directly from the current Chrome tab—even on tabs opened before the extension was reloaded—and HTML video players (including frames), and HLS/DASH manifests or video files requested by the page. Click **Download** next to a detected video. The badge shows the detected count. No copying or pasting links is needed in the extension. Page and video-link context menus remain available; manual URLs are supported in the desktop Add Download dialog.

The desktop dialog lets you choose a queue, destination, filename, and quality: **Best available**, **1080p**, **720p**, or **480p**. Click **Start download** or **Download later**. One video is downloaded per request; playlist/channel URLs select their first item. Video pages are passed to yt-dlp’s extractor, while detected media URLs are passed directly. Detection does not guarantee that every site permits extraction; protected or session-dependent media can fail. Individual transport-stream chunks and YouTube’s separate network ranges are excluded from the detected list.

The downloader uses [yt-dlp's documented CLI output and progress templates](https://github.com/yt-dlp/yt-dlp#embedding-yt-dlp), concurrent media fragments, and FFmpeg to combine separate audio/video streams. The final container extension follows the downloaded formats. Temporary media stays in the job cache, and saved files are never overwritten. Pause stops the downloader and its child processes; resume reuses fragments where the source supports it. Separate audio and video phases can cause size/progress estimates to change.

Full YouTube extraction requires a supported JavaScript runtime and yt-dlp's EJS components; see the [official yt-dlp dependency guide](https://github.com/yt-dlp/yt-dlp#dependencies). The installed official executable includes EJS, and LinuxDM detects Deno (preferred) or Node. Keep yt-dlp updated using its installation method when a site changes. Browser cookies/login sessions are not copied; private, login-restricted, and DRM-protected videos may be unavailable. Live-stream resumption depends on the source and is not guaranteed.

## Chrome integration

The included Manifest V3 extension automatically hands supported Chrome downloads to LinuxDM. **Use LinuxDM by default** is enabled initially and can be toggled in the extension popup. It also adds **Download with LinuxDM** to the right-click menu on HTTP/HTTPS links and lists automatically detected videos. It opens LinuxDM when necessary. The app suggests the matching category folder under `~/Downloads` and preserves Chrome's suggested filename.

Every incoming Chrome link opens a **Download from Chrome** dialog with the URL, editable filename, named queue, destination folder, connection count, and video quality when applicable. Choose **Start download**, **Download later** (saved as Paused), or **Discard** (remove the incoming entry). Closing the dialog or pressing Escape also keeps the download paused. Multiple incoming links get dialogs in arrival order, without replacing a dialog already being edited. Unanswered dialogs are restored when the app reopens.

Incoming downloads are saved as **Ready** and acknowledged to Chrome immediately, before waiting for your choice. File transfers in LinuxDM begin only after you choose Start download. This lets you take your time without triggering Chrome's handoff timeout. After acceptance, Discard cancels the download in LinuxDM; it does not restart the cancelled Chrome copy.

1. Close any older LinuxDM window before setting up the bridge.
2. From the project folder, register the bridge for your user (no sudo):

   ```sh
   python3 -m linuxdm.chrome_install
   ```

3. In Chrome, enter `chrome://extensions`, enable **Developer mode**, and click **Load unpacked**. Select the `chrome-extension` directory inside this project. This follows [Chrome's local-extension loading instructions](https://developer.chrome.com/docs/extensions/get-started/tutorial/hello-world#load-unpacked).
4. Pin **LinuxDM** using Chrome's extensions menu. Open its popup and check for **Desktop bridge connected**.
5. Leave **Use LinuxDM by default** enabled, then start a normal HTTP/HTTPS file download in Chrome. In LinuxDM's incoming download dialog, choose the destination and click **Start download**. Right-clicking a file link also works.

**Updating an existing installation:** choose **App ▾ → Quit LinuxDM** and reopen it, then click **Reload** on its extension card at `chrome://extensions`. Accept newly requested permissions if Chrome prompts you. Reload existing video tabs after updating the extension. Detection uses [isolated content scripts](https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts) and passive [webRequest response observation](https://developer.chrome.com/docs/extensions/reference/api/webRequest), requiring HTTP/HTTPS site access. It does not modify requests. Detected media URLs stay in session-only extension storage and are cleared on tab navigation/closure; they are not saved in persistent extension storage. Detection skips incognito tabs. The installed bridge already points to this project's code, so reinstalling it is unnecessary unless you moved the folder.

Capture uses [Chrome's downloads API](https://developer.chrome.com/docs/extensions/reference/api/downloads). Chrome's transfer is paused while the bridge checks the URL and adds it to LinuxDM, then cancelled only after the desktop app accepts it. Chrome's download history may therefore show a cancelled entry for a transfer now owned by LinuxDM. An unavailable bridge leaves Chrome downloading normally; rejected or expired handoffs resume Chrome. Requests expire atomically so they cannot enter LinuxDM later after Chrome resumes. If a native response is lost, the extension checks ownership before resuming or cancelling; a periodic recovery alarm also handles extension-worker restarts. An unresolved handoff remains paused with an explanation in the popup until ownership can be checked.

Turn **Use LinuxDM by default** off to keep new downloads in Chrome. This does not move downloads already handed to LinuxDM. Browser-generated `blob:`/`data:` files, incognito downloads, downloads initiated by other extensions, and files flagged by Chrome stay in Chrome. Very small downloads may finish before capture can pause them. Chrome's security prompts are never accepted or bypassed by the extension.

Browser cookies, login sessions, POST bodies, and custom request headers are not transferred. For automatic file capture, a preflight GET checks for HTTP errors or a login HTML response; such rejections fall back to Chrome. Some session-dependent downloads can still fail after acceptance in LinuxDM; turn capture off and retry them in Chrome. Signed direct URLs can work while valid. Streaming pages must be sent using the video action described above.

The installer registers `io.linuxdm.bridge` in your Chrome and Chromium `NativeMessagingHosts` directories, using [Chrome's native messaging protocol](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging). It installs an executable launcher at `~/.local/share/linuxdm/chrome-native-host`. The extension's public key keeps its ID stable; only that extension ID is allowed to access this host. Pending links are saved privately in `~/.local/share/linuxdm/inbox`; only the desktop app changes the main queue. A process lock prevents multiple current app instances from competing for the queue. The extension stores capture preferences, feedback, and recovery IDs, but does not store download URLs in persistent Chrome extension storage. Detected video candidates use temporary session storage only.

Keep this project folder in place. If you move it or change Python installations, rerun the installer and reload the extension. If the popup cannot reach the bridge, rerun the installer and check that Chrome uses its standard configuration location. Custom browser profiles and sandboxed Snap/Flatpak browsers may require separate native-host configuration. If a link is saved but not added, quit any old app using its App menu and run `python3 -m linuxdm` again.

To remove the integration, remove LinuxDM from `chrome://extensions` and delete only its two `io.linuxdm.bridge.json` registration files and the `chrome-native-host` launcher. Your download queue and partial files can remain.

## Test

```sh
python3 -m unittest discover -s tests -v
node tests/test_extension.js
```

The integration tests use local HTTP servers to check ranged downloads, pause/resume, removal, preserving completed files, queue limits/fairness, and real HLS media downloading through yt-dlp with audio/video verification by FFprobe. A subprocess test checks video pause/resume. Bridge tests cover delivery, expiry, and recovery. Desktop tests cover named-queue editing, video quality selection, incoming dialogs, and compact layout. JavaScript tests exercise capture/recovery and video actions with mocked Chrome APIs; loading and testing in Chrome is still a separate manual check. Video integration tests require yt-dlp, FFmpeg, and FFprobe. Optional desktop tests require a graphical session:

```sh
LINUXDM_TEST_GUI=1 python3 -m unittest discover -s tests -v
```

## Installable packages (0.5.0)

Build outputs are in `dist/`:

- `linuxdm_0.5.0_all.deb`: Debian/Ubuntu package. Install with `sudo apt install ./dist/linuxdm_0.5.0_all.deb`. It installs the app, one desktop entry, icons, browser extension sources, and system native-messaging registrations for Chrome/Chromium and Firefox. Video tools are recommended dependencies; YouTube may also need a current yt-dlp and Deno installation. Launch with `linuxdm` or `linuxdm --background`.
- `LinuxDM-0.5.0-Setup-x64.exe`: per-user Windows x64 installer. Includes the official Python 3.13 runtime installer (used if Python 3.13 x64 is absent), Tkinter, and offline tray dependencies. Adds one Start menu shortcut, Chrome/Firefox native-host registrations, and an uninstaller. It does not bundle yt-dlp, FFmpeg, or Deno: install those on PATH for video downloads. Ordinary file downloads work without these tools. Windows queue data is stored in `%LOCALAPPDATA%\LinuxDM` and survives uninstall. The installer is unsigned and has not been validated on a native Windows machine.
- `linuxdm-firefox-0.5.0-unsigned.xpi`: Firefox development extension, described below.

Quit a running old LinuxDM before installing an update. A previous source-based Linux launcher or native-host registration in your home directory takes precedence over the Debian package's system files; remove those old per-user entries if switching permanently to the packaged installation. Keep your download state and partial files. The `.deb` contains the extension directories under `/usr/share/linuxdm/`.

### Firefox

Firefox supports the same capture toggle, detected-video list, YouTube detection, and right-click actions. A Firefox-specific background script uses the shared browser APIs. Firefox lacks Chrome's filename-determination event, so tiny files may complete before automatic capture can pause them; those remain in Firefox.

For a source checkout, register the Firefox bridge once:

```sh
python3 -m linuxdm.firefox_install
```

The Debian and Windows installers register the bridge automatically. In Firefox, open `about:debugging#/runtime/this-firefox`, choose **Load Temporary Add-on**, and select `firefox-extension/manifest.json` or the unsigned XPI. This development installation lasts until Firefox restarts. Allow site access if Firefox asks, and reload video tabs when updating the extension.

Permanent installation in standard Firefox requires Mozilla signing. The supplied XPI is **unsigned**, not an AMO release. Submit it for unlisted signing through Mozilla's developer hub, then install the signed XPI. The fixed extension ID is `linuxdm@linuxdm.local`; keep this ID when signing so the native host accepts it. No signing credentials are included. See [Mozilla's native messaging guide](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_messaging).

### Rebuild

```sh
python3 packaging/build_extensions.py
python3 packaging/build_deb.py
python3 packaging/build_windows.py
```

The Windows builder expects the checksum-verified Python 3.13.16 x64 installer at `.build/python-runtime-verified.exe`, Windows CPython 3.13 wheels for pystray/Pillow/six in `.build/wheels`, and extracted Debian `nsis`/`nsis-common` packages under `.build/nsis`. The Python installer is checked against its published SHA-256 before packaging. Its source is [Python's official release page](https://www.python.org/downloads/release/python-31316/). Third-party package licenses are retained in the bundled wheel metadata. Firefox files are generated from `chrome-extension`; make shared changes there and rerun the extension builder.
