<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import AppButton from '../ui/AppButton.vue'
import Panel from '../ui/Panel.vue'
import { useServerStore } from '../../stores/server'
import { getInstances, previewInstanceSync, applyInstanceSync } from '../../api/instanceSync'

const store = useServerStore()
const info = ref(null)
const instance = ref('')
const plan = ref(null)
const result = ref(null)
const error = ref('')
const busy = ref('')
let generation = 0
const stopped = computed(() => store.serverStatus.status === 'stopped')
const counts = computed(() => {
  const value = { add: 0, replace: 0, remove: 0 }
  for (const change of plan.value?.changes || []) value[change.action]++
  return value
})

async function load() {
  const id = store.currentServerId
  const version = ++generation
  busy.value = 'load'
  error.value = ''
  plan.value = null
  try {
    const response = await getInstances(id)
    if (version !== generation) return
    info.value = response
    const selected = instance.value || response.instance || ''
    instance.value = response.instances.some(row => row.id === selected) ? selected : ''
  } catch (e) { if (version === generation) error.value = e.message }
  finally { if (version === generation) busy.value = '' }
}

async function preview() {
  const version = generation
  const id = store.currentServerId
  busy.value = 'preview'
  error.value = ''
  result.value = null
  plan.value = null
  try {
    const response = await previewInstanceSync(id, instance.value)
    if (version === generation) plan.value = response
  } catch (e) { if (version === generation) error.value = e.message }
  finally { if (version === generation) busy.value = '' }
}

async function apply() {
  if (!plan.value || busy.value) return
  const version = generation
  const id = store.currentServerId
  busy.value = 'apply'
  error.value = ''
  try {
    const response = await applyInstanceSync(id, plan.value.planToken)
    if (version !== generation) return
    result.value = response
    plan.value = null
    info.value.instance = response.instance
    info.value.lastSyncAt = response.lastSyncAt
    await Promise.all([store.loadServer({ silent: true }), store.loadMods()])
  } catch (e) {
    if (version === generation) {
      error.value = e.message
      plan.value = null // expired or changed: require a new preview
    }
  } finally { if (version === generation) busy.value = '' }
}

watch(() => store.currentServerId, () => {
  info.value = null
  instance.value = ''
  result.value = null
  if (store.currentServerId) load()
  else generation++
}, { immediate: true })
watch(instance, () => { plan.value = null; result.value = null })
onBeforeUnmount(() => { generation++ })
</script>

<template>
  <Panel :title="$t('instanceSync.title')">
    <section class="instance-sync" :aria-label="$t('instanceSync.title')">
      <p class="instance-sync__hint">{{ $t('instanceSync.description') }}</p>
      <p v-if="error" role="alert" class="instance-sync__error">{{ error }}</p>
      <template v-if="info && !info.configured">
        <p>{{ $t('instanceSync.connect') }}</p>
        <a href="https://github.com/ClydeGluten/Fabricator/blob/main/docs/MODRINTH_SYNC_RU.md" target="_blank" rel="noopener noreferrer">{{ $t('instanceSync.setupGuide') }}</a>
      </template>
      <template v-else-if="info?.configured && info.supported">
        <label for="modrinth-instance">{{ $t('instanceSync.instance') }}</label>
        <div class="instance-sync__controls">
          <select id="modrinth-instance" v-model="instance" :disabled="!!busy">
            <option value="">{{ $t('instanceSync.choose') }}</option>
            <option v-for="row in info.instances" :key="row.id" :value="row.id">{{ row.name }} ({{ row.modCount }})</option>
          </select>
          <AppButton variant="ghost" :disabled="!!busy" @click="load">{{ $t('instanceSync.refresh') }}</AppButton>
          <AppButton :loading="busy === 'preview'" :disabled="!!busy || !instance" @click="preview">{{ $t('instanceSync.preview') }}</AppButton>
        </div>
        <p class="instance-sync__hint">{{ $t('instanceSync.newInstances') }}</p>
        <p v-if="info.lastSyncAt" class="instance-sync__hint">{{ $t('instanceSync.lastSync', { instance: info.instance, date: new Date(info.lastSyncAt).toLocaleString() }) }}</p>
        <p v-if="!info.instances.length">{{ $t('instanceSync.empty') }}</p>
      </template>
      <p v-else-if="info?.configured">{{ $t('instanceSync.unsupported') }}</p>
      <p v-if="busy === 'preview'" role="status">{{ $t('instanceSync.scanning') }}</p>
      <div v-if="result" class="instance-sync__success" role="status">
        <p>{{ $t('instanceSync.success', { copied: result.copied, removed: result.removed }) }}</p>
        <p class="instance-sync__hint">{{ $t('instanceSync.backup') }} <code>{{ result.backup }}</code></p>
      </div>
      <div v-if="plan" class="instance-sync__plan" aria-live="polite">
        <p class="instance-sync__counts">{{ $t('instanceSync.counts', counts) }}</p>
        <ul v-if="plan.conflicts.length" class="instance-sync__error"><li v-for="message in plan.conflicts" :key="message">{{ message }}</li></ul>
        <ul v-if="plan.warnings.length" class="instance-sync__warning"><li v-for="message in plan.warnings" :key="message">{{ message }}</li></ul>
        <details v-if="plan.unknown.length" class="instance-sync__warning">
          <summary>{{ $t('instanceSync.unknown', { n: plan.unknown.length }) }}</summary>
          <ul><li v-for="name in plan.unknown" :key="name">{{ name }}</li></ul>
        </details>
        <ul v-if="plan.changes.length" class="instance-sync__changes">
          <li v-for="change in plan.changes" :key="change.action + change.filename">
            <span class="instance-sync__action" :class="change.action">{{ $t(`instanceSync.actions.${change.action}`) }}</span>
            <div><strong>{{ change.title || change.filename }}</strong><span v-if="change.title">{{ change.filename }}</span><span v-if="change.replaces?.length">{{ $t('instanceSync.replaces') }} {{ change.replaces.join(', ') }}</span><span v-if="change.reason">{{ change.reason }}</span></div>
          </li>
        </ul>
        <p v-else>{{ $t('instanceSync.noChanges') }}</p>
        <details v-if="plan.skipped.length">
          <summary>{{ $t('instanceSync.skipped', { n: plan.skipped.length }) }}</summary>
          <ul><li v-for="mod in plan.skipped" :key="mod.filename"><strong>{{ mod.title }}</strong> — {{ mod.filename }}<br /><span class="instance-sync__hint">{{ mod.reason }}</span></li></ul>
        </details>
        <details v-if="plan.preserved.length"><summary>{{ $t('instanceSync.preserved', { n: plan.preserved.length }) }}</summary><ul><li v-for="name in plan.preserved" :key="name">{{ name }}</li></ul></details>
        <details v-if="plan.unchanged.length"><summary>{{ $t('instanceSync.unchanged', { n: plan.unchanged.length }) }}</summary><ul><li v-for="mod in plan.unchanged" :key="mod.filename">{{ mod.filename }}</li></ul></details>
        <details v-if="plan.disabled.length"><summary>{{ $t('instanceSync.disabled', { n: plan.disabled.length }) }}</summary><ul><li v-for="name in plan.disabled" :key="name">{{ name }}</li></ul></details>
        <p v-if="!stopped" class="instance-sync__warning">{{ $t('instanceSync.stopFirst') }}</p>
        <p class="instance-sync__hint">{{ $t('instanceSync.applyHint') }}</p>
        <AppButton :loading="busy === 'apply'" :disabled="!!busy || !stopped || !!plan.conflicts.length" @click="apply">{{ $t('instanceSync.apply') }}</AppButton>
      </div>
    </section>
  </Panel>
</template>

<style scoped>
.instance-sync, .instance-sync__plan { display: flex; flex-direction: column; gap: var(--space-3); min-width: 0; }
.instance-sync p { margin: 0; }
.instance-sync__hint { color: var(--text-muted); font-size: var(--text-xs); }
.instance-sync label, .instance-sync summary { color: var(--text-secondary); font-size: var(--text-sm); }
.instance-sync summary { cursor: pointer; padding: var(--space-2) 0; }
.instance-sync__controls { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.instance-sync select { min-width: 0; flex: 1 1 200px; max-width: 100%; padding: var(--space-2); font: inherit; color: var(--text-primary); background: var(--bg-tertiary); border: 1px solid var(--border-color); border-radius: var(--radius-sm); }
.instance-sync select:focus-visible { outline: 2px solid var(--primary); }
.instance-sync__error { color: #fca5a5; }
.instance-sync__warning { color: #facc78; }
.instance-sync__success { color: #86efac; }
.instance-sync__counts { font-weight: 600; }
.instance-sync__plan { border-top: 1px solid var(--border-color); padding-top: var(--space-3); }
.instance-sync ul { margin: 0; padding-left: var(--space-5); overflow-wrap: anywhere; font-size: var(--text-sm); }
.instance-sync details ul { max-height: 250px; overflow: auto; }
.instance-sync li { margin-bottom: var(--space-2); }
.instance-sync .instance-sync__changes { list-style: none; padding: 0; max-height: 330px; overflow: auto; }
.instance-sync__changes li { display: flex; gap: var(--space-3); padding: var(--space-2); background: var(--bg-tertiary); border-radius: var(--radius-sm); }
.instance-sync__changes li > div { min-width: 0; }
.instance-sync__changes strong { font-size: var(--text-sm); font-weight: 500; }
.instance-sync__changes span:not(.instance-sync__action) { display: block; color: var(--text-muted); font-size: var(--text-xs); }
.instance-sync__action { flex: 0 0 65px; font-size: var(--text-xs); }
.instance-sync__action.add { color: #86efac; }
.instance-sync__action.replace { color: #facc78; }
.instance-sync__action.remove { color: #fca5a5; }
.instance-sync code { overflow-wrap: anywhere; }
.instance-sync__plan > .app-btn { align-self: flex-start; }
</style>
