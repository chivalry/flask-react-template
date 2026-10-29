/** @file Show the router's query string and how it got there, for tests to read. */

import { useLocation, useNavigationType } from 'react-router-dom'

/**
 * Render the current query string and navigation type in named outputs.
 *
 * An `output` has the `status` role, so each carries a name, read with
 * `screen.getByLabelText('Search')` or `screen.getByLabelText('Navigation type')`;
 * a component's own unnamed status region is then `getByRole('status', { name: '' })`.
 */
export default function LocationProbe() {
    const { search } = useLocation()
    const navigationType = useNavigationType()
    return (
        <>
            <output aria-label="Search">{search}</output>
            <output aria-label="Navigation type">{navigationType}</output>
        </>
    )
}
