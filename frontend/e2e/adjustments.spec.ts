import { expect, test } from '@playwright/test'

import { builtPool, clearAdjustments } from './helpers'

test('adjust a card from a deck, build again with it, and clear it on the Pastes page', async ({
  page,
  request,
}) => {
  await clearAdjustments(request)
  const id = await builtPool(request)

  await page.goto(`/pools/${id}/decks`)
  const deck = page.getByTestId('deck').first()
  await deck.getByText('Why this deck').click()
  await deck.getByText('Adjust', { exact: true }).first().click()
  await deck.getByRole('button', { name: 'raise value' }).first().click()
  await deck.getByRole('button', { name: 'Save for the group' }).first().click()
  await expect(deck.getByText('Saved for the group. Build again to use it.')).toBeVisible()
  // The adjustment changed the build's inputs, so the page offers a rebuild.
  await expect(page.getByText(/card adjustments, or the app changed/)).toBeVisible()
  await page.getByRole('button', { name: 'Build again' }).first().click()
  await expect(page.getByText(/^Adjusted \+0\.5 by /).first()).toBeAttached()

  await page.goto('/pastes')
  await page.getByLabel('Set', { exact: true }).selectOption('FRA')
  const row = page.getByTestId('adjustment')
  await expect(row).toHaveCount(1)
  await row.getByRole('button', { name: 'Clear' }).click()
  await expect(page.getByText('No cards adjusted for this set.')).toBeVisible()
})
