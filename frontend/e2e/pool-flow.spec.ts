import { expect, test } from '@playwright/test'

import { GRADES_PATH, POOL_TEXT, clearPastes } from './helpers'

test('paste a pool, build, paste grades, build again, record and edit a result', async ({
  page,
  request,
}) => {
  await clearPastes(request)

  await page.goto('/')
  await page.getByLabel('Set', { exact: true }).selectOption('FRA')
  await page.getByLabel('Arena export', { exact: true }).fill(POOL_TEXT)
  await page.getByRole('button', { name: 'Review pool' }).click()
  await expect(page).toHaveURL(/\/pools\/[0-9a-f-]+$/)
  await expect(page.getByText('83 non-basic cards; FRA pools usually run 78–86.')).toBeVisible()
  const poolUrl = page.url()

  await page.getByRole('button', { name: 'Build decks' }).click()
  await expect(page).toHaveURL(/\/decks$/)
  await expect(page.getByTestId('data-block')).toContainText('FRA data for this build')
  await expect(page.getByTestId('data-block')).toContainText('Add it on the Pastes page')
  await expect(page.getByText(/No card values for FRA/)).toBeVisible()

  await page.goto('/pastes')
  await page.getByLabel('Set', { exact: true }).selectOption('FRA')
  await page.getByLabel('Source', { exact: true }).selectOption('llu-marc')
  await page.getByLabel('Upload the exported file', { exact: true }).setInputFiles(GRADES_PATH)
  await expect(page.getByLabel('Paste text', { exact: true })).not.toBeEmpty()
  await page.getByRole('button', { name: 'Store paste' }).click()
  await expect(page.getByText(/^(Stored|Identical)/)).toBeVisible()

  await page.goto(`${poolUrl}/decks`)
  await page.getByRole('button', { name: 'Build again' }).first().click()
  await expect(page.getByTestId('deck').first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Copy list' }).first()).toBeVisible()

  const deck = page.getByTestId('deck').first()
  for (let i = 0; i < 3; i += 1) await deck.getByRole('button', { name: 'more wins' }).click()
  await deck.getByRole('button', { name: 'more losses' }).click()
  await deck.getByRole('button', { name: 'Record result' }).click()
  await expect(deck.getByText('Recorded 3-1.', { exact: false })).toBeVisible()

  await page.goto('/runs')
  const run = page.getByTestId('run').first()
  await expect(run.getByTestId('record')).toHaveText('3-1')
  await run.getByRole('button', { name: '+1 win' }).click()
  await expect(run.getByTestId('record')).toHaveText('4-1')
})
