/* Capture the screenshots used in the presentation from a running demo server.
     python server.py --port 8765
     node tools/make_screens.js http://127.0.0.1:8765
   Images are written to docs/presentation/img/. They show demonstration data only. */
const { chromium, devices } = require('playwright');
const fs = require('fs');
const path = require('path');
const base = process.argv[2] || 'http://127.0.0.1:8765';
const out = path.join(__dirname, '..', 'docs', 'presentation', 'img');
(async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch();
  const staff = async email => {
    const page = await (await browser.newContext({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 2 })).newPage();
    await page.goto(base);
    await page.waitForFunction(() => document.querySelectorAll('#login-role option').length > 4);
    await page.selectOption('#login-role', email);
    await page.click('#login-form button[type=submit]');
    await page.waitForSelector('.app-shell');
    await page.waitForFunction(() => !document.querySelector('.loading'));
    await page.click('[data-language=ru]');
    return page;
  };
  const manager = await staff('manager@atu.kz');
  await manager.waitForSelector('.extra-stats');
  await manager.evaluate(() => document.querySelector('.chart-grid').scrollIntoView());
  await manager.waitForTimeout(2500);
  await manager.screenshot({ path: path.join(out, 'dashboard.png') });
  await manager.evaluate(() => navigate('periods'));
  await manager.waitForSelector('[data-period]');
  await manager.fill('#period-month', '2026-10');
  await manager.dispatchEvent('#period-month', 'change');
  await manager.waitForTimeout(800);
  await manager.evaluate(() => window.scrollTo(0, 0));
  await manager.screenshot({ path: path.join(out, 'periods.png') });
  await manager.evaluate(() => navigate('actions'));
  await manager.waitForSelector('[data-action-open]');
  await manager.click('[data-action-open]');
  await manager.waitForSelector('.history');
  await manager.waitForTimeout(500);
  await manager.screenshot({ path: path.join(out, 'action.png') });
  const operator = await staff('operator@atu.kz');
  await operator.evaluate(() => navigate('forecast'));
  await operator.waitForSelector('[data-fc]');
  await operator.waitForTimeout(600);
  await operator.evaluate(() => document.querySelector('[data-fc]').closest('section').scrollIntoView());
  await operator.screenshot({ path: path.join(out, 'forecast.png') });
  const phone = await (await browser.newContext({ ...devices['Pixel 5'] })).newPage();
  await phone.goto(base + '/student/#menu');
  await phone.waitForSelector('.s-dish');
  await phone.click('[data-lang=ru]');
  await phone.waitForTimeout(400);
  await phone.screenshot({ path: path.join(out, 'student.png') });
  await browser.close();
  console.log('written:', fs.readdirSync(out).join(', '));
})().catch(error => { console.error('FAILED', error.message); process.exit(1); });
