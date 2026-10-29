/** @file Admin tab for accounts. */

import { useUserMutations, useUsers } from '../../hooks/users'
import type { User, UserPayload } from '../../types/users'
import { describeUser } from '../../utils/users'
import QueryState from '../common/QueryState'
import RecordSection from '../common/RecordSection'
import UserFormDialog from './UserFormDialog'

/**
 * Render an account's email.
 *
 * @param user - The account.
 * @returns Its email address.
 */
function userEmail(user: User): string {
    return user.email
}

/**
 * Render the account list with its dialogs; accounts are deactivated, never deleted.
 *
 * The mutations carry no `remove`, so no row offers Delete.
 *
 * @returns The tab content.
 */
export default function UsersAdmin() {
    const query = useUsers()
    const mutations = useUserMutations()
    return (
        <QueryState query={query}>
            {(users) => (
                <RecordSection<User, UserPayload>
                    title="Users"
                    addLabel="New user"
                    emptyText="No users yet."
                    items={users}
                    mutations={mutations}
                    renderPrimary={userEmail}
                    renderSecondary={describeUser}
                    renderDialog={(dialog) => <UserFormDialog {...dialog} />}
                />
            )}
        </QueryState>
    )
}
