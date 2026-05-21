import client from './client'

export interface AuthUser {
  id: number
  uuid: string
  email: string
  role: string
  created_at: string
}

export const register = (email: string, password: string) =>
  client.post<AuthUser>('/v1/auth/register', { email, password })

export const login = (email: string, password: string) =>
  client.post<AuthUser>('/v1/auth/login', { email, password })

export const logout = () => client.post('/v1/auth/logout')

export const me = () => client.get<AuthUser>('/v1/auth/me')
