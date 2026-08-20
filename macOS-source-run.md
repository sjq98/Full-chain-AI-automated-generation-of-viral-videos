# macOS Source Package

This source package can be used without installing a DMG application.

## Send this package

Send a clean source ZIP made from the repository. Do not include `data/`,
`browser_data/`, `user-settings.json`, `vendor/MediaCrawler/.venv/`,
`.git/`, or `desktop/node_modules/`.

## First use on a Mac

1. Extract the ZIP to a writable folder such as `Documents`.
2. Install Homebrew if it is not already installed.
3. In Finder, right-click `macos-install.command` and choose Open.
4. When installation finishes, right-click `macos-start.command` and choose Open.
5. Keep the Terminal window open while using the workbench. It opens at `http://127.0.0.1:8789/`.

The installer creates `vendor/MediaCrawler/.venv/`, installs Python packages,
FFmpeg, yt-dlp, and Playwright. These files stay on that Mac and are not part
of the source package.

## Platform search

The first MediaCrawler platform search opens the project's Chrome profile.
Sign in to the required platform in that browser window once. Its login state
is saved locally in `browser_data/` and can be reused for later searches.

## If macOS blocks a command file

Open Terminal and run the following from the extracted project folder:

```bash
chmod +x macos-install.command macos-start.command
./macos-install.command
./macos-start.command
```
