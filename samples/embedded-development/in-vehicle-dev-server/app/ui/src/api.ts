/**
 * The app's API as the views call it: the SDK's, with ?present=<lang> on every request while presentation mode is
 * on (i18n/index.ts), so that the backend shows the people as their role (backend/team/display.py).
 */
import { useMemo } from 'react'
import { useAppApi as useSdkApi, type AppApi } from '@kirocrew/app-sdk'
import { lang, presentation } from './i18n'

export function withPresent(path: string): string {
  if (!presentation()) return path
  return `${path}${path.includes('?') ? '&' : '?'}present=${lang()}`
}

export function useAppApi(): AppApi {
  const api = useSdkApi()
  return useMemo(() => {
    if (!presentation()) return api
    const out: AppApi = {
      get: (p, init) => api.get(withPresent(p), init),
      post: (p, body, init) => api.post(withPresent(p), body, init),
      put: (p, body, init) => api.put(withPresent(p), body, init),
      patch: (p, body, init) => api.patch(withPresent(p), body, init),
      del: (p, init) => api.del(withPresent(p), init),
    }
    if (api.raw) out.raw = (p, init) => api.raw!(withPresent(p), init)
    if (api.request) out.request = (p, init) => api.request!(withPresent(p), init)
    return out
  }, [api])
}
