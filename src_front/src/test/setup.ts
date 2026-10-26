import '@testing-library/jest-dom'
import { beforeEach, vi } from 'vitest'

// jsdom has no IntersectionObserver. Provide an inert stub so components that
// render an InfiniteScrollSentinel mount cleanly; behavior tests replace it.
class IntersectionObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
}

beforeEach(() => {
    vi.stubGlobal('IntersectionObserver', IntersectionObserverStub)
})
