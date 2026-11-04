/** @file A passkey button and the provider links share one divider, or none shows. */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { listProviders } from '../../../api/oauth'
import SignInOptions from '../../../components/auth/SignInOptions'
import { usePasskeyLogin } from '../../../hooks/usePasskeyLogin'
import { googleProvider } from '../../utils/fixtures'

vi.mock('../../../api/oauth')
vi.mock('../../../hooks/usePasskeyLogin')

const run = vi.fn()
const signIn = vi.fn()

/**
 * Make the passkey hook report what the browser offers.
 *
 * @param available - Whether the browser can use passkeys.
 * @param pending - Whether the button's sign-in is running.
 */
const passkeys = (available: boolean, pending = false) =>
    vi.mocked(usePasskeyLogin).mockReturnValue({ available, pending, signIn })

/** Render the options, then wait for the providers to load. */
const renderSignInOptions = async () => {
    const view = render(<SignInOptions next="/widgets/12" run={run} />)
    await waitFor(() => expect(listProviders).toHaveBeenCalledTimes(1))
    return view
}

describe('SignInOptions', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        vi.mocked(listProviders).mockResolvedValue([])
        passkeys(true)
    })

    it('renders nothing, divider included, with no passkey and no provider', async () => {
        passkeys(false)

        const { container } = await renderSignInOptions()

        expect(screen.queryByRole('separator')).not.toBeInTheDocument()
        expect(container).toBeEmptyDOMElement()
    })

    it('shows the divider and the passkey button with only a passkey', async () => {
        await renderSignInOptions()

        expect(screen.getByRole('separator')).toHaveTextContent('or')
        expect(
            screen.getByRole('button', { name: 'Sign in with a passkey' }),
        ).toBeInTheDocument()
        expect(screen.queryByRole('link')).not.toBeInTheDocument()
    })

    it('shows the divider and the provider link with only a provider', async () => {
        passkeys(false)
        vi.mocked(listProviders).mockResolvedValue([googleProvider])

        await renderSignInOptions()

        expect(
            await screen.findByRole('link', { name: 'Continue with Google' }),
        ).toHaveAttribute('href', '/api/v1/auth/oauth/google/start?next=%2Fwidgets%2F12')
        expect(screen.getByRole('separator')).toHaveTextContent('or')
        expect(screen.queryByRole('button')).not.toBeInTheDocument()
    })

    it('places the passkey button before the provider link', async () => {
        vi.mocked(listProviders).mockResolvedValue([googleProvider])

        await renderSignInOptions()

        const link = await screen.findByRole('link', { name: 'Continue with Google' })
        const button = screen.getByRole('button', { name: 'Sign in with a passkey' })
        expect(button.compareDocumentPosition(link)).toBe(
            Node.DOCUMENT_POSITION_FOLLOWING,
        )
    })

    it('signs in with a passkey on a click', async () => {
        const user = userEvent.setup()
        await renderSignInOptions()

        await user.click(screen.getByRole('button', { name: 'Sign in with a passkey' }))

        expect(signIn).toHaveBeenCalledTimes(1)
    })

    it('disables the passkey button while its sign-in runs', async () => {
        passkeys(true, true)

        await renderSignInOptions()

        expect(
            screen.getByRole('button', { name: 'Sign in with a passkey' }),
        ).toBeDisabled()
    })

    it('hands the page run to the passkey hook', async () => {
        await renderSignInOptions()

        expect(usePasskeyLogin).toHaveBeenCalledWith(run)
    })
})
