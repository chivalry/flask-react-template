/** @file The admin screen: one tab and one child route per section, from one list. */

import { Box, Container, Tab, Tabs } from '@mui/material'
import type { ReactNode } from 'react'
import { Link, Navigate, Route, Routes, useParams } from 'react-router-dom'

import AdminAuditLogTab from '../components/admin/AdminAuditLogTab'
import UsersAdmin from '../components/admin/UsersAdmin'

/** One admin section: its route segment, its tab label, and its content. */
interface AdminSection {
    path: string
    label: string
    element: ReactNode
}

/** Where `App.tsx` mounts this page, as `/admin/*`. */
const ADMIN_BASE = '/admin'

/** Every admin section, in tab order; `/admin` and unknown paths land on the first. */
const SECTIONS: AdminSection[] = [
    { path: 'users', label: 'Users', element: <UsersAdmin /> },
    { path: 'audit', label: 'Audit', element: <AdminAuditLogTab /> },
]

/** The first section's absolute path, the target of both redirects. */
const LANDING_PATH = `${ADMIN_BASE}/${SECTIONS[0].path}`

/**
 * Render the section tabs and, beneath them, the section the URL names.
 *
 * The sections are descendant routes of `/admin/*`, declared here rather than in
 * `App.tsx`, so adding a section means adding one entry to `SECTIONS`. Tab links and
 * redirects use absolute paths: under a splat route React Router resolves a relative
 * path against the whole URL, so `users` from `/admin/nope` would mean
 * `/admin/nope/users` and redirect forever. The selected tab comes from the first
 * segment of the splat; an empty or unknown segment selects no tab (`false`), so
 * `Tabs` never warns about a value it has no tab for while the redirect lands.
 *
 * @returns The page element.
 */
export default function AdminPage() {
    const segment = useParams()['*']?.split('/')[0]
    const selected = SECTIONS.find((section) => section.path === segment)?.path ?? false
    return (
        <Container maxWidth="md" sx={{ py: 2 }}>
            <Tabs
                value={selected}
                variant="scrollable"
                scrollButtons="auto"
                sx={{ mb: 2 }}
            >
                {SECTIONS.map((section) => (
                    <Tab
                        key={section.path}
                        value={section.path}
                        label={section.label}
                        component={Link}
                        to={`${ADMIN_BASE}/${section.path}`}
                    />
                ))}
            </Tabs>
            <Box>
                <Routes>
                    <Route index element={<Navigate to={LANDING_PATH} replace />} />
                    {SECTIONS.map((section) => (
                        <Route
                            key={section.path}
                            path={section.path}
                            element={section.element}
                        />
                    ))}
                    <Route path="*" element={<Navigate to={LANDING_PATH} replace />} />
                </Routes>
            </Box>
        </Container>
    )
}
