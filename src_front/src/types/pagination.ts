/** @file The envelope every paginated list endpoint returns. */

/** One page of a list, as the backend's `paginate` helper shapes it. */
export interface PaginatedResponse<T> {
    items: T[]
    total: number
    page: number
    pages: number
    per_page: number
}
