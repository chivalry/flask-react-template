import '@testing-library/jest-dom'
import { beforeEach, vi } from 'vitest'

import { stubViewportWidth } from './utils/viewport'

// jsdom has no IntersectionObserver. Provide an inert stub so components that
// render an InfiniteScrollSentinel mount cleanly; behavior tests replace it.
class IntersectionObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
}

beforeEach(() => {
    vi.stubGlobal('IntersectionObserver', IntersectionObserverStub)
    // jsdom has no matchMedia either. Every test starts on a desktop-wide viewport,
    // and a test of a phone layout calls stubViewportWidth(375) before it renders.
    stubViewportWidth(1280)
})
