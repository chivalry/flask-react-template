/** @file Dialog interactions shared by screen tests. */

import { screen, waitFor, within } from '@testing-library/react'
import type userEvent from '@testing-library/user-event'
import { expect } from 'vitest'

/** Cancel the visible dialog and wait until its closing transition completes. */
export async function cancelOpenDialog(user: ReturnType<typeof userEvent.setup>) {
    const dialog = within(screen.getByRole('dialog'))
    await user.click(dialog.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
}
