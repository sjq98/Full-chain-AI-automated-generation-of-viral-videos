import type { BrowserContext, Page } from 'patchright';

function normalizedUrl(value: string): string {
  return String(value || '').trim().replace(/\/$/, '');
}

function pageHost(page: Page): string {
  try {
    return new URL(page.url()).host.toLowerCase();
  } catch {
    return '';
  }
}

function reusablePage(context: BrowserContext, targetUrl: string): Page | undefined {
  const pages = context.pages().filter((page) => !page.isClosed());
  const normalizedTarget = normalizedUrl(targetUrl);
  const exact = pages.find((page) => normalizedUrl(page.url()) === normalizedTarget);
  if (exact) return exact;

  let targetHost = '';
  try {
    targetHost = new URL(targetUrl).host.toLowerCase();
  } catch {
    // Keep looking for a disposable blank page.
  }
  if (targetHost) {
    const sameHost = pages.find((page) => pageHost(page) === targetHost);
    if (sameHost) return sameHost;
  }

  return pages.find((page) => ['', 'about:blank', 'chrome://newtab'].includes(normalizedUrl(page.url())));
}

export async function keepOnlyPage(context: BrowserContext, keepPage: Page): Promise<number> {
  let closed = 0;
  for (const page of context.pages()) {
    if (page === keepPage || page.isClosed()) continue;
    try {
      await page.close();
      closed += 1;
    } catch {
      // A page may disappear while Chrome is completing a redirect.
    }
  }
  return closed;
}

export async function restoreVisibleWindow(page: Page): Promise<boolean> {
  let session: any;
  try {
    await page.bringToFront();
    session = await page.context().newCDPSession(page);
    const { windowId } = await session.send('Browser.getWindowForTarget');
    if (windowId === undefined || windowId === null) return false;
    await session.send('Browser.setWindowBounds', {
      windowId,
      bounds: { windowState: 'normal' },
    });
    await session.send('Browser.setWindowBounds', {
      windowId,
      bounds: { left: 60, top: 40, width: 1280, height: 900 },
    });
    await page.bringToFront();
    return true;
  } catch {
    return false;
  } finally {
    await session?.detach().catch(() => {});
  }
}

export async function prepareSingleVisiblePage(context: BrowserContext, targetUrl: string): Promise<Page> {
  const page = reusablePage(context, targetUrl) || (await context.newPage());
  await keepOnlyPage(context, page);
  await restoreVisibleWindow(page);
  return page;
}
