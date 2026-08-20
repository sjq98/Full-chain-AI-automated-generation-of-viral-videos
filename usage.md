# MP4 Golden Clip Workbench Usage

This repository can run as a local source package on Windows and macOS. The
source package does not require a signed DMG or EXE, but the user must install
the local dependencies once before starting the workbench.

## Before sending the source package

Use GitHub's **Code > Download ZIP** or create a clean archive from Git:

```bash
git archive --format=zip --output MP4-Golden-Clip-Workbench-source.zip main
```

Do not send the following local files or folders: `data/`, `browser_data/`,
`user-settings.json`, `.logs/`, `vendor/MediaCrawler/.venv/`, `.git/`, and
`desktop/node_modules/`. They can contain personal settings, task history,
login state, or machine-specific binaries.

## Windows

### First use

1. Extract the source ZIP to a writable folder, such as `Documents`.
2. Install Python 3.10, 3.11, or 3.12 and select **Add Python to PATH** during
   installation.
3. Install FFmpeg and make sure both `ffmpeg` and `ffprobe` are available in
   Command Prompt. A common option is `winget install Gyan.FFmpeg`.
4. Double-click `install-deps.bat` and wait for the dependency installation to
   finish.
5. Double-click `start.bat`.

The workbench opens at `http://127.0.0.1:8789/`. Keep the Command Prompt
window open while using it; closing that window stops the local server.

### If a dependency check fails

Open Command Prompt in the project folder and run:

```bat
python --version
ffmpeg -version
ffprobe -version
```

Then run `install-deps.bat` again after fixing the missing item.

## macOS

### First use

1. Extract the source ZIP to a writable folder, such as `Documents`.
2. Install [Homebrew](https://brew.sh) if it is not already installed.
3. In Finder, right-click `macos-install.command` and choose **Open**. This
   installs Python 3.11, FFmpeg, MediaCrawler dependencies, yt-dlp, and the
   Playwright Chromium runtime.
4. When it finishes, right-click `macos-start.command` and choose **Open**.

The launcher opens `http://127.0.0.1:8789/` in the default browser. Keep its
Terminal window open while using the workbench. Logs are stored in
`.logs/workbench.log`.

### If macOS blocks the command files

Open Terminal, change into the extracted project folder, and run:

```bash
chmod +x macos-install.command macos-start.command
./macos-install.command
./macos-start.command
```

## First-time configuration

1. Open **Provider Management** in the workbench.
2. Add the transcription and LLM providers you plan to use.
3. Upload a local MP4 or MOV video, or open **Viral Search** to find a source
   video and import it into the workbench.

Provider configuration and local task data stay on the user's own computer.
They are not included in a clean source package.

## Viral Search platform login

For a MediaCrawler platform search, the first search opens the project's own
Chrome profile. Complete the platform login in that browser window once. The
login state is stored locally in `browser_data/` and reused on later searches.

Do not share `browser_data/`; it can contain platform login cookies. Use the
feature only for personal, lawful research and in accordance with each
platform's terms and applicable rules.

## Stopping the workbench

- Windows: close the `start.bat` Command Prompt window.
- macOS: close the Terminal window launched by `macos-start.command` or press
  `Control + C` in it.

The local address is only available on that user's computer. No inbound public
port is opened.
