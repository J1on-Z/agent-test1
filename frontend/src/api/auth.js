import request from './request'

export const login = (username, password) =>
  request.post('/auth/login', { username, password }, { _silent: true })

export const refreshTokenRequest = (refreshToken) =>
  request.post('/auth/refresh', { refresh_token: refreshToken }, { _silent: true })

export const logout = (refreshToken) =>
  request.post('/auth/logout', { refresh_token: refreshToken }, { _silent: true })

export const register = (username, password) =>
  request.post('/auth/register', { username, password })

export const changePassword = (oldPassword, newPassword) =>
  request.post('/auth/change-password', { old_password: oldPassword, new_password: newPassword })

export const getMe = () => request.get('/auth/me')
