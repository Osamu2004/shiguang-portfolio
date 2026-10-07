// Run with NODE_PATH pointing to an installation of Playwright.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
  const out = path.resolve('qa-output', process.argv[2] || 'current');
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ timezoneId: 'Asia/Shanghai', serviceWorkers: 'block' });
  await context.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
  const page = await context.newPage();
  const errors = [], results = [];
  page.on('pageerror', e => errors.push(e.message));
  for (const width of [1440, 1280, 900, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('http://127.0.0.1:18787');
    await page.waitForFunction(() => document.querySelector('#holdingList .fund-row'));
    for (const id of ['dashboard', 'holdings', 'health', 'research', 'manage', 'sync', 'market']) {
      await page.evaluate(id => go(id), id);
      if (!await page.locator('#' + id).count()) continue;
      const layout = await page.evaluate(() => ({
        viewport: innerWidth, scrollWidth: document.documentElement.scrollWidth,
        overflow: [...document.querySelectorAll('.page.active *')].filter(e => {
          const r = e.getBoundingClientRect(); return r.width > 0 && r.right > innerWidth + 2;
        }).slice(0, 8).map(e => e.id || e.className)
      }));
      results.push({ width, page: id, ...layout });
      if (['dashboard','holdings','sync'].includes(id)) await page.screenshot({ path: path.join(out, `${id}-${width}.png`), fullPage: true });
    }
  }
  await page.setViewportSize({width: 390, height: 740});
  await page.goto('http://127.0.0.1:18787');
  await page.waitForFunction(() => document.querySelector('#holdingList .fund-row'));
  await page.locator('#userMenuButton').click();
  await page.locator('#userMenu [data-page="manage"]').click();
  await page.locator('#activeHoldingActions [data-action="history"]').first().click();
  await page.waitForFunction(() => document.querySelector('#holdingHistory .history-title'));
  assert(await page.locator('#holdingHistory').isVisible());
  await page.evaluate(() => go('holdings'));
  await page.locator('#holdingList2 .fund-actions button').first().click();
  await page.locator('#strategyForm select[name="mode"]').selectOption('drawdown');
  const panel = await page.locator('.strategy-panel').boundingBox();
  assert(panel.x >= 0 && panel.y >= 0 && panel.x + panel.width <= 391 && panel.y + panel.height <= 741);
  await page.locator('#strategyForm [name="drawdown_budget"]').fill('1000');
  await page.locator('#strategyForm button.primary').click();
  await page.waitForFunction(() => document.querySelector('.strategy-panel').hidden);
  assert.equal((await page.request.get('http://127.0.0.1:18787/api/state').then(r=>r.json())).holdings[0].investment_strategy.mode, 'drawdown');
  await page.evaluate(() => {
    state={holdings:[], accounts:[{name:'零余额',account_type:'现金',balance:'0'}], total:'0',fundTotal:'0',totalCost:'0',profit:'0',snapshots:[]};
    renderDashboard();renderAllocation();renderAdvice();go('dashboard');
  });
  assert(!/NaN|Infinity/.test(await page.locator('#dashboard').innerText()));
  assert.equal(await page.locator('#riskLevel').innerText(), '—');
  const local = await page.evaluate(() => localDay(new Date('2026-09-07T01:00:00+08:00')));
  assert.equal(local, '2026-09-07');
  await page.screenshot({path:path.join(out,'empty-dashboard-390.png'),fullPage:true});
  await browser.close();
  fs.writeFileSync(path.join(out, 'layout.json'), JSON.stringify({ errors, results }, null, 2));
  console.log(JSON.stringify({ errors, overflows: results.filter(r => r.scrollWidth > r.viewport + 2), checks: results.length }, null, 2));
  assert.equal(errors.length, 0, 'Uncaught browser errors');
  assert.equal(results.filter(r => r.scrollWidth > r.viewport + 2).length, 0, 'Page overflow');
})().catch(e => { console.error(e); process.exitCode = 1; });
