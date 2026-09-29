import { expect, test } from '@playwright/test'

import { GRADES_TEXT } from './helpers'

// Excel saves "Unicode Text" as UTF-16 with a byte-order mark, and "CSV" as Windows-1252.
// The upload is decoded like the server does, so both arrive as clean text.
test('an uploaded UTF-16 or Windows-1252 export reads as clean text', async ({ page }) => {
  await page.goto('/pastes')
  const upload = page.getByLabel('Upload the exported file', { exact: true })
  const text = page.getByLabel('Paste text', { exact: true })

  const utf16 = Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from(GRADES_TEXT, 'utf16le')])
  await upload.setInputFiles({ name: 'grades.txt', mimeType: 'text/plain', buffer: utf16 })
  await expect(text).toHaveValue(GRADES_TEXT)

  const cp1252 = Buffer.from('Name,Tier\nDáin Ironfoot,B\n', 'latin1')
  await upload.setInputFiles({ name: 'grades.csv', mimeType: 'text/csv', buffer: cp1252 })
  await expect(text).toHaveValue('Name,Tier\nDáin Ironfoot,B\n')
})
