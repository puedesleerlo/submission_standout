import { test, expect } from '@playwright/test';

test('reusable bank search and import preserve the source and allow unknown deadlines', async ({page, request}) => {
  const headers = {Authorization: 'Bearer standout-e2e-observer'};
  const created = await request.post('/api/projects', {headers, data: {
    name: 'Exploratory company conversation', institution: 'Example company', domain: 'Job',
    posting: 'An exploratory conversation with no official posting or announced deadline.', focus: ['forecasting'],
  }});
  expect(created.ok()).toBeTruthy();
  const project = await created.json();
  const saved = await request.post('/api/library', {headers, data: {entries: [{
    key: 'browser.calibration-case', bank: 'Experience', title: 'Calibration regression case',
    body: 'Built a reproducible evaluation suite with carefully timestamped evidence and held-out outcomes.',
    sources: [{reference: 'https://example.com/case', accessed_on: '2026-09-21'}],
    caveats: 'Applicant-reported result; no independent validation.',
  }]}});
  expect(saved.ok()).toBeTruthy();
  await page.goto(`/?project=${project.id}&view=library#access=standout-e2e-observer`);
  await expect(page.getByRole('heading', {name: 'Reusable banks', exact: true})).toBeVisible();
  await page.getByLabel('Search reusable banks').fill('calibration');
  await expect(page.getByRole('heading', {name: 'Calibration regression case'})).toBeVisible();
  await page.getByLabel('Reusable bank', {exact: true}).selectOption('Experience');
  await expect(page.getByText('1 entry', {exact: true})).toBeVisible();
  await page.getByText('Sources (1)', {exact: true}).click();
  await expect(page.getByRole('link', {name: 'https://example.com/case'})).toBeVisible();
  await page.getByRole('button', {name: 'Use in this project'}).click();
  await expect(page.getByRole('status')).toContainText('attached');
  await page.screenshot({path: 'test-results/library-desktop.png', fullPage: true});
  await page.setViewportSize({width: 390, height: 844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path: 'test-results/library-mobile.png', fullPage: true});
  await page.getByRole('button', {name: 'Project brief', exact: true}).click();
  await expect(page.getByText('Not announced', {exact: true})).toBeVisible();
  const ws = await (await request.get(`/api/projects/${project.id}`, {headers})).json();
  expect(ws.evidence).toHaveLength(1);
  expect(ws.evidence[0].bank_revision).toBe(1);
  expect(ws.evidence[0].body).toContain('no independent validation');
});
