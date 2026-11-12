/* Quick-entry scenario (ТТ 21): one measurement in at most five main actions and under 30 seconds.
   Needs a running demo server and the pre-installed Playwright:
     python server.py --port 8765
     node tests/e2e/quick_entry.js http://127.0.0.1:8765
   The time printed is the automated run; a person's time is measured with a stopwatch during the pilot. */
const { chromium, devices } = require('playwright');
const base = process.argv[2] || 'http://127.0.0.1:8765';
(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ ...devices['Pixel 5'] })).newPage();
  await page.goto(base);
  await page.waitForFunction(() => document.querySelectorAll('#login-role option').length > 4);
  await page.selectOption('#login-role', 'operator@atu.kz');
  await page.click('#login-form button[type=submit]');
  await page.waitForSelector('#quick-entry');
  await page.waitForFunction(() => !document.querySelector('.loading'));
  const started = Date.now();
  let actions = 0;
  await page.click('#quick-entry'); actions++;                    // 1. open quick entry
  await page.click('[data-quick-cat]:nth-child(2)'); actions++;   // 2. choose the waste type
  await page.keyboard.type('2.4'); actions++;                     // 3. type the quantity on the numeric keypad
  await page.click('#quick-form button[type=submit]'); actions++; // 4. save
  await page.waitForFunction(() => document.querySelector('#quick-done').textContent.length > 5);
  const seconds = (Date.now() - started) / 1000;
  const saved = await page.textContent('#quick-done');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  await browser.close();
  console.log(JSON.stringify({ actions, seconds, saved, overflow }, null, 2));
  if (actions > 5 || seconds > 30 || overflow > 0 || !/Сақталды/.test(saved)) { console.error('FAILED: limits exceeded'); process.exit(1); }
  console.log('OK: at most 5 actions and under 30 seconds');
})().catch(error => { console.error('FAILED', error.message); process.exit(1); });
