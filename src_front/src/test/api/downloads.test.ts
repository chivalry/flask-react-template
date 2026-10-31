/** @file downloadFile saves a response body through a temporary anchor. */

import type { AxiosResponse } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import client from '../../api/client'
import { downloadFile } from '../../api/downloads'

vi.mock('../../api/client')

const OBJECT_URL = 'blob:http://localhost/export'
const PATH = '/v1/users/export.csv'
const FILENAME = 'accounts.csv'
const body = new Blob(['a,b\r\n'], { type: 'text/csv' })

describe('downloadFile', () => {
    beforeEach(() => {
        vi.useFakeTimers()
        vi.resetAllMocks()
        vi.mocked(client.get).mockResolvedValue({ data: body } as AxiosResponse)
        vi.spyOn(URL, 'createObjectURL').mockReturnValue(OBJECT_URL)
        vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
        vi.spyOn(document, 'createElement')
    })

    afterEach(() => {
        vi.useRealTimers()
        vi.restoreAllMocks()
    })

    it('fetches the file as a blob, without the client timeout', async () => {
        await downloadFile(PATH, FILENAME)

        expect(client.get).toHaveBeenCalledExactlyOnceWith(PATH, {
            responseType: 'blob',
            timeout: 0,
        })
    })

    it('clicks one anchor that saves the body under the filename', async () => {
        const clicked: { href: string; download: string }[] = []
        vi.mocked(HTMLAnchorElement.prototype.click).mockImplementation(function (
            this: HTMLAnchorElement,
        ) {
            clicked.push({ href: this.href, download: this.download })
        })

        await downloadFile(PATH, FILENAME)

        expect(URL.createObjectURL).toHaveBeenCalledOnce()
        expect(vi.mocked(URL.createObjectURL).mock.calls[0][0]).toBe(body)
        expect(document.createElement).toHaveBeenCalledExactlyOnceWith('a')
        expect(clicked).toEqual([{ href: OBJECT_URL, download: FILENAME }])
    })

    it('revokes the object URL once, forty seconds after the click', async () => {
        await downloadFile(PATH, FILENAME)

        vi.advanceTimersByTime(39_999)
        expect(URL.revokeObjectURL).not.toHaveBeenCalled()

        vi.advanceTimersByTime(1)
        expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith(OBJECT_URL)
    })

    it('saves nothing and rejects when the request fails', async () => {
        const failure = new Error('Admin access required.')
        vi.mocked(client.get).mockRejectedValue(failure)

        await expect(downloadFile(PATH, FILENAME)).rejects.toBe(failure)

        expect(URL.createObjectURL).not.toHaveBeenCalled()
        expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled()
    })
})
