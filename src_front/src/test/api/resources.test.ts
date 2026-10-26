/** @file Each operation `resource()` builds calls the shared client on the right path. */

import { beforeEach, describe, expect, it, vi } from 'vitest'

import client, { fetchAll } from '../../api/client'
import { resource } from '../../api/resources'

vi.mock('../../api/client', () => ({
    default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
    fetchAll: vi.fn(),
}))

/** A record of the stand-in resource. */
interface Thing {
    id: number
    name: string
}

/** The body the stand-in resource accepts. */
interface ThingPayload {
    name: string
}

const thing: Thing = { id: 8, name: 'Widget' }
const payload: ThingPayload = { name: 'Widget' }
const things = resource<Thing, ThingPayload>('/v1/things')

describe('resource', () => {
    beforeEach(() => {
        vi.resetAllMocks()
    })

    it('list fetches every page of the resource path', async () => {
        vi.mocked(fetchAll).mockResolvedValue([thing])

        await expect(things.list()).resolves.toEqual([thing])

        expect(fetchAll).toHaveBeenCalledTimes(1)
        expect(fetchAll).toHaveBeenCalledWith('/v1/things')
    })

    it('create posts the payload and returns the created record', async () => {
        vi.mocked(client.post).mockResolvedValue({ data: thing })

        await expect(things.create(payload)).resolves.toBe(thing)

        expect(client.post).toHaveBeenCalledTimes(1)
        expect(client.post).toHaveBeenCalledWith('/v1/things', payload)
    })

    it('update puts the payload to the record path and returns the record', async () => {
        vi.mocked(client.put).mockResolvedValue({ data: thing })

        await expect(things.update(8, payload)).resolves.toBe(thing)

        expect(client.put).toHaveBeenCalledTimes(1)
        expect(client.put).toHaveBeenCalledWith('/v1/things/8', payload)
    })

    it('remove deletes the record path and resolves with nothing', async () => {
        vi.mocked(client.delete).mockResolvedValue({ data: '' })

        await expect(things.remove(8)).resolves.toBeUndefined()

        expect(client.delete).toHaveBeenCalledTimes(1)
        expect(client.delete).toHaveBeenCalledWith('/v1/things/8')
    })
})
