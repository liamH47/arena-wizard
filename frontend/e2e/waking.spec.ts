import { expect, test } from '@playwright/test'

// Render's free instance sleeps and Neon wakes slowly, so the app retries 503s behind a
// banner. The banner must appear while retrying and go away once a request succeeds; a
// banner stuck on after recovery reads as "the server is down".
test('the waking banner shows while the server is waking and clears when it answers', async ({
  page,
}) => {
  const started = Date.now()
  await page.route('**/api/sets', async (route) => {
    if (Date.now() - started < 3_200) {
      await route.fulfill({ status: 503, contentType: 'application/json', body: '{"status":"warming"}' })
    } else {
      await route.continue()
    }
  })
  await page.goto('/')
  await expect(page.getByTestId('waking-banner')).toBeVisible()
  await expect(page.getByTestId('waking-banner')).toBeHidden({ timeout: 20_000 })
  await expect(page.getByLabel('Set', { exact: true })).toContainText('FRA')
})
