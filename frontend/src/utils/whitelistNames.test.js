import test from 'node:test'
import assert from 'node:assert/strict'
import { whitelistNames } from './whitelistNames.js'

test('pasted friends list is deduplicated without losing account case', () => {
  assert.deepEqual(whitelistNames('Steve, Alex\nsteve; Third_Player'), ['Steve', 'Alex', 'Third_Player'])
})
test('Minecraft whitelist export can be imported by names', () => {
  assert.deepEqual(whitelistNames('[{"name":"Alex","uuid":"ignored"},{"name":"Steve"}]'), ['Alex', 'Steve'])
})
test('selectors, injected commands, invalid JSON and oversized imports are rejected', () => {
  for (const input of ['@a', '["Steve\\nstop"]', '[{"uuid":"missing-name"}]', '[',
    Array.from({length: 21}, (_, i) => `Player${i}`).join(',')]) {
    assert.throws(() => whitelistNames(input))
  }
})
