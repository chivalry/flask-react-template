/** @file The Account page's section for adding, renaming, and deleting passkeys. */

import { Box } from '@mui/material'
import { browserSupportsWebAuthn } from '@simplewebauthn/browser'

import { usePasskeyMutations, usePasskeys } from '../../hooks/passkeys'
import {
    passkeyFormDefaults,
    passkeyFormSchema,
    toPasskeyPayload,
} from '../../schemas/passkey'
import type { Passkey, PasskeyPayload } from '../../types/auth'
import { describePasskeyUse, passkeyName } from '../../utils/passkeys'
import FormDialog from '../common/FormDialog'
import FormTextField from '../common/FormTextField'
import QueryState from '../common/QueryState'
import RecordSection, { type RecordDialogProps } from '../common/RecordSection'

/** Why Add is off in a browser that cannot create passkeys. */
const UNSUPPORTED = 'This browser cannot create passkeys.'

/**
 * Ask for a nickname: before the browser creates a passkey, or to rename one.
 *
 * @param props - The dialog props from the owning record section.
 * @returns The dialog element.
 */
function PasskeyFormDialog(props: RecordDialogProps<Passkey, PasskeyPayload>) {
    const { open, item, onClose, onSubmit } = props
    return (
        <FormDialog
            open={open}
            title={item ? 'Rename passkey' : 'Add a passkey'}
            schema={passkeyFormSchema}
            defaultValues={passkeyFormDefaults(item)}
            submitLabel={item ? 'Save' : 'Continue'}
            onClose={onClose}
            onSubmit={(values) => onSubmit(toPasskeyPayload(values))}
        >
            <FormTextField
                name="nickname"
                label="Nickname"
                helperText="Optional: a name that tells this passkey from your others."
                autoFocus
            />
        </FormDialog>
    )
}

/**
 * Say what deleting a passkey does.
 *
 * @param passkey - The passkey about to be deleted.
 * @returns The confirmation's text.
 */
function deleteWarning(passkey: Passkey): string {
    const name = passkeyName(passkey)
    return `${name} will stop signing in here. Remove it from your device as well.`
}

/**
 * Show the signed-in account's passkeys, and let it add, rename, and delete them.
 *
 * Adding one asks for an optional nickname, then for the browser's prompt. A refused
 * delete, such as of the account's last way to sign in, shows the server's message in
 * the confirmation.
 *
 * @returns The section element.
 */
export default function Passkeys() {
    const query = usePasskeys()
    const mutations = usePasskeyMutations()
    const addDisabledReason = browserSupportsWebAuthn() ? undefined : UNSUPPORTED
    return (
        <Box component="section" sx={{ mt: 4 }}>
            <QueryState query={query}>
                {(passkeys) => (
                    <RecordSection<Passkey, PasskeyPayload>
                        title="Passkeys"
                        addLabel="Add passkey"
                        emptyText="No passkeys yet."
                        items={passkeys}
                        mutations={mutations}
                        renderPrimary={passkeyName}
                        renderSecondary={describePasskeyUse}
                        deleteTitle="Delete passkey"
                        deleteMessage={deleteWarning}
                        renderDialog={(dialog) => <PasskeyFormDialog {...dialog} />}
                        addDisabledReason={addDisabledReason}
                    />
                )}
            </QueryState>
        </Box>
    )
}
