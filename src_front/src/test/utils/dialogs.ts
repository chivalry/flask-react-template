/** @file Dialog interactions shared by screen tests. */

import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import type userEvent from '@testing-library/user-event'
import { expect } from 'vitest'

/** Cancel the visible dialog and wait until its closing transition completes. */
export async function cancelOpenDialog(user: ReturnType<typeof userEvent.setup>) {
    const dialog = within(screen.getByRole('dialog'))
    await user.click(dialog.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
}

/**
 * Press Escape inside the visible dialog, where MUI's modal listens for it.
 *
 * The key goes to the dialog itself, so it reaches the modal even while every
 * button in it is disabled and focus has nowhere else to sit.
 */
export function pressEscapeInDialog() {
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
}
