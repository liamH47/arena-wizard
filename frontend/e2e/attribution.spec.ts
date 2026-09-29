import { expect, test } from '@playwright/test'

import { builtPool } from './helpers'

// Attribution at the top of every page, and the Fan Content notice at the bottom.
test('every page credits 17Lands at the top and carries the Fan Content notice', async ({
  page,
  request,
}) => {
  const id = await builtPool(request)
  for (const path of ['/', '/pastes', '/runs', `/pools/${id}`, `/pools/${id}/decks`, '/login']) {
    await page.goto(path)
    const header = page.getByTestId('attribution')
    await expect(header).toContainText('17Lands')
    await expect(header).toContainText('Not affiliated with or endorsed by 17Lands')
    await expect(header.getByRole('link', { name: '17Lands' })).toHaveAttribute(
      'href',
      'https://www.17lands.com',
    )
    await expect(header.getByRole('link', { name: 'usage guidelines' })).toHaveAttribute(
      'href',
      'https://www.17lands.com/usage_guidelines',
    )
    const footer = page.locator('footer')
    await expect(footer).toContainText('Arena Wizard is unofficial Fan Content permitted under the')
    await expect(footer).toContainText('Not approved/endorsed by Wizards.')
    await expect(footer.getByRole('link', { name: 'Fan Content Policy' })).toBeVisible()
    await expect(footer.getByRole('link', { name: 'Scryfall' })).toHaveAttribute(
      'href',
      'https://scryfall.com',
    )
  }
})
