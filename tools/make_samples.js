/* Build the sample quarterly summary (XLSX and PDF) from a running demo server.
     python server.py --port 8765
     node tools/make_samples.js http://127.0.0.1:8765
   The files are written to docs/samples/. They contain demonstration data only. */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const base = process.argv[2] || 'http://127.0.0.1:8765';
const out = path.join(__dirname, '..', 'docs', 'samples');
const period = 'start=2026-07-01&end=2026-09-30';
(async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(base);
  const login = await page.evaluate(async () => (await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: 'manager@atu.kz', password: 'demo2026' }) })).status);
  if (login !== 200) throw new Error('login failed: ' + login);
  for (const lang of ['ru', 'kk']) {
    const response = await context.request.get(`${base}/api/export?format=xlsx&lang=${lang}&${period}`);
    if (!response.ok()) throw new Error('xlsx export failed: ' + response.status());
    fs.writeFileSync(path.join(out, `quarterly-2026-Q3-${lang}.xlsx`), await response.body());
    await page.goto(`${base}/api/export?format=print&auto=0&lang=${lang}&${period}`);
    await page.pdf({ path: path.join(out, `quarterly-2026-Q3-${lang}.pdf`), format: 'A4', landscape: true, margin: { top: '12mm', bottom: '12mm', left: '10mm', right: '10mm' } });
  }
  await browser.close();
  console.log('written:', fs.readdirSync(out).join(', '));
})().catch(error => { console.error('FAILED', error.message); process.exit(1); });
