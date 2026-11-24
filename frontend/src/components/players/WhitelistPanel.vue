<script setup>
import { computed, ref } from 'vue'
import AppButton from '../ui/AppButton.vue'
import ToggleRow from '../ui/ToggleRow.vue'
import { usePlayersStore } from '../../stores/players'
import { useServerStore } from '../../stores/server'
import { useToast } from '../../composables/useToast'
import { addWhitelistBatch } from '../../api/players'
import { whitelistNames } from '../../utils/whitelistNames'
import { t } from '../../i18n'

const store = usePlayersStore()
const serverStore = useServerStore()
const toast = useToast()
const names = ref('')
const search = ref('')
const busy = ref(false)
const error = ref('')
const results = ref([])
const upload = ref(null)
const entries = computed(() => store.whitelist.filter(p => p.name.toLowerCase().includes(search.value.toLowerCase())).sort((a, b) => a.name.localeCompare(b.name)))

async function enable(active) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try { await store.toggleWhitelistActive(active) } catch (e) { error.value = e.message }
  finally { busy.value = false }
}

async function add() {
  if (busy.value) return
  error.value = ''
  results.value = []
  try {
    const parsed = whitelistNames(names.value)
    if (!parsed.length) return
    busy.value = true
    const response = await addWhitelistBatch(serverStore.currentServerId, parsed)
    results.value = response.results
    names.value = response.results.filter(r => !r.added).map(r => r.name).join('\n')
    if (response.warning) error.value = response.warning
    await store.loadAll()
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}

async function remove(entry) {
  busy.value = true
  error.value = ''
  try {
    await store.removeWhitelist(entry.name)
    toast.action(t('players.removedFromWhitelist', { name: entry.name }), t('common.undo'), async () => {
      try {
        const response = await addWhitelistBatch(serverStore.currentServerId, [entry.name])
        if (!response.results[0]?.added) throw new Error(response.results[0]?.error || t('common.operationFailed'))
        await store.loadAll()
      } catch (e) { toast.error(e.message) }
    })
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}

async function importNames(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  error.value = ''
  try {
    if (file.size > 1024 * 1024) throw new Error(t('whitelistEditor.fileTooLarge'))
    names.value = whitelistNames(await file.text()).join('\n')
  } catch (e) { error.value = e.message }
}

function exportNames() {
  const url = URL.createObjectURL(new Blob([JSON.stringify(store.whitelist, null, 2)], { type: 'application/json' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'whitelist.json'
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
</script>

<template>
  <section class="whitelist-editor" :aria-label="$t('whitelistEditor.title')">
    <div class="whitelist-editor__heading"><h2>{{ $t('whitelistEditor.title') }} <span>{{ store.whitelist.length }}</span></h2><AppButton variant="ghost" size="sm" :disabled="!store.whitelist.length" @click="exportNames">{{ $t('whitelistEditor.export') }}</AppButton></div>
    <fieldset :disabled="busy" class="whitelist-editor__switch">
      <ToggleRow :label="$t('whitelistEditor.enabled')" :model-value="store.whitelistActive" @update:model-value="enable" />
    </fieldset>
    <p class="whitelist-editor__hint">{{ $t('whitelistEditor.persistent') }}</p>
    <p v-if="error" class="whitelist-editor__error" role="alert">{{ error }}</p>
    <form class="whitelist-editor__add" @submit.prevent="add">
      <label for="whitelist-names">{{ $t('whitelistEditor.addNames') }}</label>
      <textarea id="whitelist-names" v-model="names" rows="2" :placeholder="$t('whitelistEditor.placeholder')" :disabled="busy" />
      <div class="whitelist-editor__buttons">
        <AppButton type="submit" :loading="busy" :disabled="!names.trim()">{{ $t('whitelistEditor.add') }}</AppButton>
        <AppButton variant="ghost" :disabled="busy" @click="upload?.click()">{{ $t('whitelistEditor.import') }}</AppButton>
        <input ref="upload" type="file" accept=".txt,.json" hidden @change="importNames" />
      </div>
    </form>
    <ul v-if="results.length" class="whitelist-editor__results" aria-live="polite"><li v-for="r in results" :key="r.name" :class="{ 'whitelist-editor__error': !r.added }">{{ r.name }} — {{ r.added ? $t('whitelistEditor.added') : r.error }}</li></ul>
    <input v-if="store.whitelist.length" v-model="search" type="search" :placeholder="$t('whitelistEditor.search')" :aria-label="$t('whitelistEditor.search')" />
    <ul class="whitelist-editor__entries">
      <li v-for="entry in entries" :key="entry.uuid || entry.name"><span>{{ entry.name }}</span><AppButton variant="ghost" size="sm" :disabled="busy" :aria-label="$t('whitelistEditor.removeName', { name: entry.name })" @click="remove(entry)">{{ $t('whitelistEditor.remove') }}</AppButton></li>
    </ul>
    <p v-if="!store.whitelist.length" class="whitelist-editor__hint">{{ $t('whitelistEditor.empty') }}</p>
  </section>
</template>

<style scoped>
.whitelist-editor { border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: var(--space-4); display: flex; flex-direction: column; gap: var(--space-3); }
.whitelist-editor__heading { display: flex; justify-content: space-between; align-items: center; }
h2 { color: var(--text-primary); font-size: var(--text-md); margin: 0; } h2 span { color: var(--text-muted); font-size: var(--text-sm); }
.whitelist-editor__switch { border: 0; margin: 0; padding: 0; min-width: 0; }
.whitelist-editor__add { display: flex; flex-direction: column; gap: var(--space-2); }
.whitelist-editor__buttons { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.whitelist-editor__hint { color: var(--text-muted); font-size: var(--text-xs); margin: 0; }
input[type=search], textarea { font: inherit; color: var(--text-primary); background: var(--bg-tertiary); border: 1px solid var(--border-color); border-radius: var(--radius-sm); padding: var(--space-2); width: 100%; box-sizing: border-box; }
textarea { resize: vertical; min-height: 62px; }
input:focus, textarea:focus { outline: 2px solid var(--primary); }
label { color: var(--text-secondary); font-size: var(--text-sm); }
.whitelist-editor__error { color: #fca5a5; font-size: var(--text-sm); margin: 0; }
.whitelist-editor__entries { list-style: none; display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: var(--space-2); margin: 0; padding: 0; max-height: 260px; overflow: auto; }
.whitelist-editor__entries li { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); padding: var(--space-2); background: var(--bg-tertiary); border-radius: var(--radius-sm); }
.whitelist-editor__results { padding-left: 18px; margin: 0; font-size: var(--text-xs); }
</style>
