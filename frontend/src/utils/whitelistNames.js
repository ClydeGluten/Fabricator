// Accept pasted names, a text file, or Minecraft's exported whitelist.json.
export function whitelistNames(text) {
  let values
  const trimmed = text.trim()
  if (trimmed.startsWith('[')) {
    const parsed = JSON.parse(trimmed)
    if (!Array.isArray(parsed)) throw new Error('Expected a list of player names.')
    values = parsed.map(value => typeof value === 'string' ? value : value?.name)
  } else {
    values = trimmed.split(/[\s,;]+/).filter(Boolean)
  }
  const names = new Map()
  for (const name of values) {
    if (typeof name !== 'string' || !/^[A-Za-z0-9_]{1,16}$/.test(name)) {
      throw new Error('Use Minecraft player names: 1–16 letters, digits or underscores.')
    }
    if (!names.has(name.toLowerCase())) names.set(name.toLowerCase(), name)
  }
  if (names.size > 20) throw new Error('Add at most 20 players at a time.')
  return [...names.values()]
}
