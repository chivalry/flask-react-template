/** @file Admin tab for the audit log: every table's changes, narrowed by filters. */

import { MenuItem, Stack, TextField } from '@mui/material'
import { useState } from 'react'

import { useAuditedTables, useAuditLog } from '../../hooks/auditLogs'
import { useUsers } from '../../hooks/users'
import type { AuditLogFilters } from '../../types/auditLog'
import { addLocalDays, localIsoDate } from '../../utils/dates'
import AuditLogTab from '../common/AuditLogTab'

/** How many local days the log opens on, today included. */
const DEFAULT_DAYS = 30

/** Props accepted by {@link FilterSelect}. */
interface FilterSelectProps {
    label: string
    /** What the first choice, which matches anything, says. */
    allLabel: string
    value: string
    options: readonly { value: string; label: string }[]
    onChange: (value: string) => void
}

/** Props accepted by {@link DateFilter}. */
interface DateFilterProps {
    label: string
    value: string
    /** The earliest day the picker allows; any when blank. */
    min?: string
    /** The latest day the picker allows; any when blank. */
    max?: string
    onChange: (value: string) => void
}

/** Props accepted by {@link AuditLogFilterBar}. */
interface AuditLogFilterBarProps {
    filters: AuditLogFilters
    onChange: (patch: Partial<AuditLogFilters>) => void
}

/**
 * Open the log on the last 30 local days, today included, for every table and user.
 *
 * @returns The starting filters.
 */
function defaultFilters(): AuditLogFilters {
    const today = localIsoDate(new Date())
    return {
        tableName: '',
        changedById: '',
        from: addLocalDays(today, 1 - DEFAULT_DAYS),
        to: today,
    }
}

/**
 * Render a dropdown whose first choice means any.
 *
 * `displayEmpty` makes MUI show that choice for the empty value, with the label raised
 * above it; without it the field would be blank under an unshrunk label. This is not
 * `FormSelectField`, which needs a form context.
 *
 * @param props - The component props.
 * @returns The select field.
 */
function FilterSelect(props: FilterSelectProps) {
    const { label, allLabel, value, options, onChange } = props
    return (
        <TextField
            select
            size="small"
            label={label}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            sx={{ minWidth: 180 }}
            slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}
        >
            <MenuItem value="">{allLabel}</MenuItem>
            {options.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                    {option.label}
                </MenuItem>
            ))}
        </TextField>
    )
}

/**
 * Render a date field that can be bounded by another filter's day.
 *
 * @param props - The component props.
 * @returns The date field.
 */
function DateFilter(props: DateFilterProps) {
    const { label, value, min, max, onChange } = props
    return (
        <TextField
            type="date"
            size="small"
            label={label}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            slotProps={{
                inputLabel: { shrink: true },
                htmlInput: { min: min || undefined, max: max || undefined },
            }}
        />
    )
}

/**
 * Render the Table, User, From, and To filters in a row, or a column on a phone.
 *
 * The table names and accounts load beside the log; until they arrive each dropdown
 * offers only its first choice.
 *
 * @param props - The component props.
 * @returns The filter bar.
 */
function AuditLogFilterBar(props: AuditLogFilterBarProps) {
    const { filters, onChange } = props
    const tables = useAuditedTables().data ?? []
    const users = useUsers().data ?? []
    return (
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 2 }}>
            <FilterSelect
                label="Table"
                allLabel="All tables"
                value={filters.tableName}
                options={tables.map((name) => ({ value: name, label: name }))}
                onChange={(tableName) => onChange({ tableName })}
            />
            <FilterSelect
                label="User"
                allLabel="All users"
                value={filters.changedById}
                options={users.map((user) => ({
                    value: String(user.id),
                    label: user.email,
                }))}
                onChange={(changedById) => onChange({ changedById })}
            />
            <DateFilter
                label="From"
                value={filters.from}
                max={filters.to}
                onChange={(from) => onChange({ from })}
            />
            <DateFilter
                label="To"
                value={filters.to}
                min={filters.from}
                onChange={(to) => onChange({ to })}
            />
        </Stack>
    )
}

/**
 * Render the filters above the audit log of every audited table.
 *
 * The filters sit outside the log's query state, so changing one shows the spinner
 * below them without unmounting them. Only admins may call the endpoints behind it.
 *
 * @returns The tab content.
 */
export default function AdminAuditLogTab() {
    const [filters, setFilters] = useState(defaultFilters)
    return (
        <>
            <AuditLogFilterBar
                filters={filters}
                onChange={(patch) => setFilters((current) => ({ ...current, ...patch }))}
            />
            <AuditLogTab
                query={useAuditLog(filters)}
                showRecord
                emptyText="No changes match these filters."
            />
        </>
    )
}
