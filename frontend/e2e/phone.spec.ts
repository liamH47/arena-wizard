import { expect, test, type Page } from '@playwright/test'

import { builtPool } from './helpers'

async function noSidewaysScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
}

async function withinWidth(page: Page, name: string): Promise<void> {
  const button = page.getByRole('button', { name }).first()
  await button.scrollIntoViewIfNeeded()
  const box = await button.boundingBox()
  const width = page.viewportSize()?.width ?? 0
  expect(box).not.toBeNull()
  expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(width)
  expect(box?.height ?? 0).toBeGreaterThanOrEqual(44)
}

// Where an element starts, in page coordinates, measured in screen heights from the top.
async function screensDown(page: Page, locator: ReturnType<Page['locator']>): Promise<number> {
  await expect(locator).toBeVisible()
  const top = await locator.evaluate((el) => el.getBoundingClientRect().top + window.scrollY)
  return top / (page.viewportSize()?.height ?? 1)
}

test('on a phone every page fits and the event-night buttons are in reach', async ({
  page,
  request,
}, info) => {
  test.skip(info.project.name !== 'pixel7', 'phone layout only')
  const id = await builtPool(request)
  for (const path of ['/', '/pastes', '/runs', `/pools/${id}`, `/pools/${id}/decks`]) {
    await page.goto(path)
    await page.waitForLoadState('networkidle')
    await noSidewaysScroll(page)
  }
  await page.goto(`/pools/${id}`)
  expect(await screensDown(page, page.getByRole('button', { name: 'Build decks' }))).toBeLessThanOrEqual(2)
  await withinWidth(page, 'Build decks')
  await page.goto(`/pools/${id}/decks`)
  await expect(page.getByTestId('deck').first()).toBeVisible()
  expect(await screensDown(page, page.getByTestId('list-row').first())).toBeLessThanOrEqual(2)
  await withinWidth(page, 'Copy list')
  await withinWidth(page, 'Record result')
})
