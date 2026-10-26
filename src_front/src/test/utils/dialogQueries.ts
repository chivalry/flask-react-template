/** @file Shared list and dialog queries for record-management tests. */
import { screen, within } from '@testing-library/react'

/** Scope queries to the row containing the supplied text. */
export const rowContaining = (text: string) =>
    within(screen.getByText(text).closest('li')!)

/** Scope queries to the currently open dialog. */
export const findDialog = async () => within(await screen.findByRole('dialog'))
