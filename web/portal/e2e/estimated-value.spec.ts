import { expect, test, type Page } from '@playwright/test';
import { estimateCopy as writtenCopy } from '../src/lib/estimateCopy';

// Component unit tests in a real browser: no application/auth or API fixtures.
async function mount(page: Page, props: Record<string, unknown> = {}, copy?: [string, string]) {
  await page.route('**/__estimated-value-unit__', route => route.fulfill({
    contentType: 'text/html',
    body: `<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><script type="module">
      import RefreshRuntime from '/@react-refresh';
      RefreshRuntime.injectIntoGlobalHook(window);
      window.$RefreshReg$ = () => {};
      window.$RefreshSig$ = () => type => type;
      window.__vite_plugin_react_preamble_installed__ = true;
    </script></head><body><div id="unit"></div><button id="outside" style="display:block;margin-top:180px">Outside</button>
    <script type="module">
      import '/src/index.css';
      import '/src/styles/globals.css';
      import '/src/styles/portal-surface-polish.css';
      import React from '/node_modules/.vite/deps/react.js';
      import ReactDOM from '/node_modules/.vite/deps/react-dom_client.js';
      import { EstimatedValue } from '/src/components/EstimatedValue.tsx';
      import { estimateCopy } from '/src/lib/estimateCopy.ts';
      import { formatWatts, formatNumber } from '/src/lib/formatters.ts';
      ${copy ? `estimateCopy.hrss = ${JSON.stringify(copy)};` : ''}
      const props = ${JSON.stringify(props)};
      const formatValue = props.decimals === undefined ? formatWatts : n => formatNumber(n, props.decimals, props.decimals);
      ReactDOM.createRoot(document.getElementById('unit')).render(React.createElement(EstimatedValue,
        {measurement:{value:251, estimate:true, basis:'threshold_cp_3_7_15_v1', ...props}, formatValue}));
    </script></body></html>`,
  }));
  await page.goto('/__estimated-value-unit__');
}

test('estimate mark has its spoken name, hidden symbol and unchanged value precision', async ({ page }) => {
  await mount(page, { value: 251.4, range: [238, 264] });
  const button = page.getByRole('button', { name: 'Estimated 251 watts', exact: true });
  await expect(button).toHaveText('≈251 W');
  await expect(button.locator('[aria-hidden="true"]')).toHaveText('≈');
  await expect(button).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('keyboard opens the non-modal card, Escape restores focus, blur and outside pointer close it', async ({ page }) => {
  await mount(page, { range: [238, 264] });
  const button = page.getByRole('button', { name: 'Estimated 251 watts' });
  await page.keyboard.press('Tab');
  await expect(button).toBeFocused();
  await page.keyboard.press('Enter');
  const card = page.getByRole('dialog', { name: 'Estimated 251 watts' });
  await expect(card).toBeVisible();
  await expect(button).toHaveAttribute('aria-expanded', 'true');
  await expect(card).not.toHaveAttribute('aria-modal', 'true');
  await expect(card).toContainText('251 W');
  await card.focus();
  await page.keyboard.press('Escape');
  await expect(card).toHaveCount(0);
  await expect(button).toBeFocused();
  await page.keyboard.press('Space');
  await expect(card).toBeVisible();
  await page.keyboard.press('Tab');
  await expect(card).toHaveCount(0);
  await expect(page.getByRole('button', {name:'Outside'})).toBeFocused();
  await button.click();
  await expect(card).toBeVisible();
  await page.getByRole('button', {name:'Outside'}).focus();
  await expect(card).toHaveCount(0);
  await expect(page.getByRole('button', {name:'Outside'})).toBeFocused();
  await button.click();
  await expect(card).toBeVisible();
  await page.getByRole('button', {name:'Outside'}).click();
  await expect(card).toHaveCount(0);
});

test('hover opens without moving focus and clicking keeps the card open', async ({ page }) => {
  await mount(page, { range: [238, 264] });
  const button = page.getByRole('button', { name: 'Estimated 251 watts' });
  await page.getByRole('button', {name:'Outside'}).focus();
  await button.hover();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('button', {name:'Outside'})).toBeFocused();
  await page.getByRole('dialog').hover();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', {name:'Outside'}).hover();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await button.click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', {name:'Outside'}).hover();
  await expect(page.getByRole('dialog')).toBeVisible();
});

test('range uses the same formatter and decimal precision; missing copy never leaks a basis or TIM slot', async ({ page }) => {
  for (const basis of ['unknown_backend_basis', 'hrss']) {
    await mount(page, { value: 251.126, range: [238.124, 264.126], basis, decimals: 2 }, ['', 'TIM: awaiting words']);
    await page.getByRole('button', { name: 'Estimated 251.13' }).click();
    const card = page.getByRole('dialog');
    await expect(card.locator('.estimated-value__range')).toHaveText('238.12–264.13');
    await expect(card.locator('.estimated-value__copy')).toHaveCount(0);
    await expect(card).not.toContainText(/TIM:|threshold_cp|unknown_backend_basis|hrss/);
  }
  await mount(page, { basis: 'hrss' }, ['  Written fixture copy.  ', 'TIM: awaiting words']);
  await page.getByRole('button', { name: 'Estimated 251 watts' }).click();
  await expect(page.getByRole('dialog').locator('.estimated-value__range')).toHaveCount(0);
  await expect(page.getByRole('dialog').locator('.estimated-value__copy')).toHaveText('Written fixture copy.');
  // Tim's written pair shows as written, beside the range.
  await mount(page, { range: [238, 264] });
  await page.getByRole('button', { name: 'Estimated 251 watts' }).click();
  for (const line of writtenCopy.threshold_cp_3_7_15_v1) await expect(page.getByRole('dialog')).toContainText(line);
  await expect(page.getByRole('dialog')).not.toContainText(/TIM:|threshold_cp/);
});

test('absent and measured values do not become estimate buttons', async ({ page }) => {
  await mount(page, { estimate: false, value: 251.4 });
  await expect(page.locator('#unit')).toHaveText('251 W');
  await expect(page.locator('#unit button')).toHaveCount(0);
  await mount(page, { value: null });
  await expect(page.locator('#unit')).toBeEmpty();
});

test('estimates with no range or written copy are static accessible marks', async ({ page }) => {
  for (const props of [
    { basis: 'hrss' },
    { basis: 'unknown_backend_basis' },
    { basis: 'hrss', range: [] },
    { basis: 'hrss', range: [238, null] },
  ]) {
    await mount(page, props, ['  ', 'TIM: awaiting words']);
    const value = page.locator('#unit .estimated-value');
    await expect(value.locator('[aria-hidden="true"]')).toHaveText('≈251 W');
    await expect(value.locator('.sr-only')).toHaveText('Estimated 251 watts');
    await expect(value).toMatchAriaSnapshot('- text: Estimated 251 watts');
    await expect(value).not.toHaveRole('img');
    await expect(page.locator('#unit button')).toHaveCount(0);
    await expect(value).toHaveCSS('text-decoration-line', 'none');
    await value.hover();
    await value.click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.keyboard.press('Tab');
    await expect(page.getByRole('button', { name: 'Outside' })).toBeFocused();
  }
});

test('card fits at both edges of a mobile viewport and closes on outside tap', async ({ browser }) => {
  const context = await browser.newContext({viewport:{width:390,height:844},hasTouch:true,isMobile:true});
  const page = await context.newPage();
  await mount(page, { range: [238,264] });
  for (const right of [false,true]) {
    await page.locator('#unit').evaluate((element, right) => {
      Object.assign((element as HTMLElement).style, {position:'fixed',top:'740px',left:right?'auto':'0',right:right?'0':'auto'});
    }, right);
    await page.getByRole('button', {name:'Estimated 251 watts'}).tap();
    const card = page.getByRole('dialog');
    await expect(card).toBeVisible();
    const bounds = (await card.boundingBox())!;
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(390);
    expect(bounds.y + bounds.height).toBeLessThanOrEqual(844);
    await page.getByRole('button', {name:'Outside'}).tap();
    await expect(card).toHaveCount(0);
  }
  await context.close();
});
