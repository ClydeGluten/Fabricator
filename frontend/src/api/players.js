/**
 * Player Management API Client
 *
 * Wraps the per-server player endpoints exposed by backend/server/players/routes.py.
 */

import { get, post, patch, del } from './client'

export function getPlayerDetails(serverId, name, options = {}) {
  return get(`/api/servers/${serverId}/players/${encodeURIComponent(name)}/details`, {}, options)
}

export function sendPlayerAction(serverId, name, action) {
  return post(`/api/servers/${serverId}/players/${encodeURIComponent(name)}/actions`, action)
}

export function addWhitelistBatch(serverId, names) {
  return post(`/api/servers/${serverId}/players/whitelist/batch`, { names })
}

export async function getPlayersState(serverId) {
  return get(`/api/servers/${serverId}/players/state`)
}

export async function getOnlinePlayers(serverId) {
  return get(`/api/servers/${serverId}/players/online`)
}

export async function addToWhitelist(serverId, name) {
  return post(`/api/servers/${serverId}/players/whitelist`, { name })
}

export async function removeFromWhitelist(serverId, name) {
  return del(`/api/servers/${serverId}/players/whitelist`, { name })
}

export async function setWhitelistActive(serverId, active) {
  return patch(`/api/servers/${serverId}/players/whitelist/active`, { active })
}

export async function addOp(serverId, name, level) {
  return post(`/api/servers/${serverId}/players/ops`, { name, level })
}

export async function setOpLevel(serverId, name, level) {
  return patch(`/api/servers/${serverId}/players/ops`, { name, level })
}

export async function removeOp(serverId, name) {
  return del(`/api/servers/${serverId}/players/ops`, { name })
}

export async function banPlayer(serverId, name, reason) {
  return post(`/api/servers/${serverId}/players/bans`, { name, reason })
}

export async function unbanPlayer(serverId, name) {
  return del(`/api/servers/${serverId}/players/bans`, { name })
}

export async function kickPlayer(serverId, name, reason = null) {
  return post(`/api/servers/${serverId}/players/kick`, { name, ...(reason ? { reason } : {}) })
}

export async function banIp(serverId, ip, reason = null) {
  return post(`/api/servers/${serverId}/players/bans/ip`, { ip, ...(reason ? { reason } : {}) })
}

export async function unbanIp(serverId, ip) {
  return del(`/api/servers/${serverId}/players/bans/ip`, { ip })
}

export async function forgetPlayer(serverId, name) {
  return del(`/api/servers/${serverId}/players/known`, { name })
}

export async function setEnforceWhitelist(serverId, active) {
  return patch(`/api/servers/${serverId}/players/whitelist/enforce`, { active })
}
