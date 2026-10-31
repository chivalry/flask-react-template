/**
 * @file Saves a file from the API in the browser, under a name the app chooses.
 *
 * The request goes through the axios client rather than a plain link, so it carries the
 * session, a 401 still reports a lost session, and a failure rejects with the server's
 * `{ error }` text for the caller to show.
 */

import client from './client'

/**
 * How long an object URL outlives its click, in milliseconds.
 *
 * WebKit has lost downloads whose URL was revoked at once. Nothing else can reach the
 * URL, so revoking late costs only the memory it holds; FileSaver.js waits as long.
 */
const REVOKE_DELAY_MS = 40_000

/**
 * Fetch a file from the API and save it in the browser.
 *
 * The request sets no timeout, because the client's 15 seconds would cover the whole
 * transfer and abort a large file partway.
 *
 * @param path - The endpoint, relative to the API base, such as `/v1/users/export.csv`.
 * @param filename - The name the browser saves the file under.
 * @returns A promise that resolves once the file is handed to the browser; it rejects
 *   when the request fails.
 */
export async function downloadFile(path: string, filename: string): Promise<void> {
    const { data } = await client.get<Blob>(path, { responseType: 'blob', timeout: 0 })
    const url = URL.createObjectURL(data)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.click()
    setTimeout(() => {
        URL.revokeObjectURL(url)
    }, REVOKE_DELAY_MS)
}
