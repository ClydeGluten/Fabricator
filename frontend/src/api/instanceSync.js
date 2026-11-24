import { get, post } from './client'

const base = id => `/api/servers/${encodeURIComponent(id)}/modrinth-sync`
export const getInstances = id => get(base(id))
export const previewInstanceSync = (id, instance) => post(`${base(id)}/preview`, { instance })
export const applyInstanceSync = (id, planToken) => post(`${base(id)}/apply`, { planToken })
