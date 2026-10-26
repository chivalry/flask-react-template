/** @file End-of-list marker that loads the next page when it scrolls into view. */

import { Box, CircularProgress } from '@mui/material'
import { useEffect, useRef } from 'react'

/** Props accepted by {@link InfiniteScrollSentinel}, taken from an infinite query. */
interface InfiniteScrollSentinelProps {
    hasNextPage: boolean
    isFetchingNextPage: boolean
    fetchNextPage: () => void
}

/**
 * Request the next page whenever the marker becomes visible and one exists.
 *
 * @param props - The component props.
 * @returns The marker, with a spinner while a page is loading.
 */
export default function InfiniteScrollSentinel(props: InfiniteScrollSentinelProps) {
    const { hasNextPage, isFetchingNextPage, fetchNextPage } = props
    const sentinelRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const observer = new IntersectionObserver(
            ([entry]) => {
                if (entry.isIntersecting && hasNextPage && !isFetchingNextPage) {
                    fetchNextPage()
                }
            },
            { threshold: 0.1 },
        )
        // The ref is attached by the time effects run; the marker is always rendered.
        observer.observe(sentinelRef.current!)
        return () => observer.disconnect()
    }, [hasNextPage, isFetchingNextPage, fetchNextPage])

    return (
        <Box ref={sentinelRef} sx={{ display: 'flex', justifyContent: 'center', py: 1 }}>
            {isFetchingNextPage && <CircularProgress size={20} />}
        </Box>
    )
}
