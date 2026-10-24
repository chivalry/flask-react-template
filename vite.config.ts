import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

/** Vendor chunk for each top-level `node_modules` directory it collects. */
const VENDOR_CHUNKS: Record<string, string> = {
    react: 'react',
    'react-dom': 'react',
    'react-router': 'react',
    'react-router-dom': 'react',
    scheduler: 'react',
    '@emotion': 'mui',
    '@mui': 'mui',
    'react-transition-group': 'mui',
    stylis: 'mui',
    '@hookform': 'forms',
    'react-hook-form': 'forms',
    zod: 'forms',
}

/**
 * Name the vendor chunk a module belongs to.
 *
 * Vendor chunks change only when dependencies do, so they keep their hashes across
 * deploys that change only application code. Rollup places everything else, and
 * Vite 8 drops the object form of `manualChunks`, so this is the function form.
 *
 * @param id - The module's resolved path.
 * @returns The chunk name, or `undefined` to let Rollup place the module.
 */
function vendorChunk(id: string): string | undefined {
    // Greedy `.*` reaches the last node_modules segment, the package that owns the file.
    const match = /.*\/node_modules\/(@[^/]+|[^/]+)\//.exec(id)
    return match ? VENDOR_CHUNKS[match[1]] : undefined
}

export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, process.cwd(), 'VITE_')
    const apiTarget = env.VITE_API_URL ?? 'http://localhost:5000'

    return {
        root: 'src_front',
        // Keep Vite's cache beside the root node_modules instead of creating
        // a stray src_front/node_modules directory.
        cacheDir: '../node_modules/.vite',
        plugins: [
            react({
                babel: {
                    // Optimize production; keep test coverage on authored source.
                    plugins: mode === 'production' ? ['babel-plugin-react-compiler'] : [],
                },
            }),
        ],
        resolve: {
            alias: {
                '@': '/src_front/src',
            },
        },
        server: {
            port: parseInt(process.env.FRONTEND_PORT ?? '5174'),
            // Regex keys match whole path segments, like the Flask 404 handler, so
            // a client route such as /api-docs is not proxied to the backend.
            proxy: {
                '^/api(/|$)': {
                    target: apiTarget,
                    changeOrigin: true,
                },
                '^/uploads(/|$)': {
                    target: apiTarget,
                    changeOrigin: true,
                },
            },
        },
        build: {
            outDir: '../dist',
            emptyOutDir: true,
            rollupOptions: {
                output: {
                    manualChunks: vendorChunk,
                },
            },
        },
        test: {
            globals: true,
            environment: 'jsdom',
            setupFiles: './src/test/setup.ts',
            coverage: {
                provider: 'v8',
                reporter: ['text', 'lcov'],
                // Paths are relative to `root`. Listing every source file means
                // an untested module counts against the thresholds instead of
                // being invisible to them.
                include: ['src/**/*.{ts,tsx}'],
                exclude: ['src/test/**', 'src/main.tsx'],
                thresholds: {
                    lines: 100,
                    functions: 100,
                    branches: 100,
                    statements: 100,
                },
            },
        },
    }
})
