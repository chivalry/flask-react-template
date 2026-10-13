import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

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
