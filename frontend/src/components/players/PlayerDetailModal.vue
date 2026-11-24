<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import BaseModal from '../modals/BaseModal.vue'
import AppButton from '../ui/AppButton.vue'
import PlayerAvatar from './PlayerAvatar.vue'
import InventoryGrid from './InventoryGrid.vue'
import { getPlayerDetails, sendPlayerAction } from '../../api/players'
import { t } from '../../i18n'

const props = defineProps({
  show: Boolean, player: Object, serverId: String, running: Boolean,
  onlinePlayers: { type: Array, default: () => [] },
})
defineEmits(['close'])
const data = ref(null)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const mode = ref('survival')
const destination = ref('')
const coords = ref({ x: '', y: '', z: '', dimension: 'minecraft:overworld' })
let controller
let generation = 0
const canAct = computed(() => props.running && (data.value?.online ?? props.player?.isOnline) && !busy.value && !loading.value)
const targets = computed(() => props.onlinePlayers.filter(p => p.name !== props.player?.name))
const mainSlots = [...Array.from({ length: 27 }, (_, i) => i + 9), ...Array.from({ length: 9 }, (_, i) => i)]
const enderSlots = Array.from({ length: 27 }, (_, i) => i)
const equipmentSlots = computed(() => [...new Set(['head', 'chest', 'legs', 'feet', 'offhand', ...(data.value?.equipment || []).map(i => i.slot)])])
const number = value => value == null ? '—' : Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })
const savedAt = computed(() => data.value?.capturedAt ? new Date(data.value.capturedAt).toLocaleString() : '')

async function refresh(fillForm = false) {
  if (!props.show || !props.player || !props.serverId) return
  controller?.abort()
  controller = new AbortController()
  const current = ++generation
  loading.value = true
  error.value = ''
  try {
    const response = await getPlayerDetails(props.serverId, props.player.name, { signal: controller.signal })
    if (generation !== current) return
    data.value = response
    if (fillForm && response.position) coords.value = { ...response.position, dimension: response.dimension || 'minecraft:overworld' }
    if (fillForm && response.gameMode) mode.value = response.gameMode
  } catch (e) {
    if (generation === current && e.name !== 'AbortError') error.value = e.message
  } finally {
    if (generation === current) loading.value = false
  }
}

async function act(action) {
  if (!canAct.value) return
  busy.value = true
  notice.value = ''
  error.value = ''
  const current = generation
  try {
    await sendPlayerAction(props.serverId, props.player.name, action)
    if (generation !== current) return
    notice.value = t('playerCard.commandSent')
    await refresh()
  } catch (e) {
    if (generation === current) error.value = e.message
  } finally { busy.value = false }
}

watch(() => [props.show, props.player?.name, props.serverId], () => {
  controller?.abort()
  generation++
  data.value = null
  notice.value = ''
  error.value = ''
  destination.value = ''
  coords.value = { x: '', y: '', z: '', dimension: 'minecraft:overworld' }
  if (props.show) refresh(true)
}, { immediate: true })
onBeforeUnmount(() => {
  generation++
  controller?.abort()
  if (props.show) document.body.style.overflow = ''
})
</script>

<template>
  <BaseModal :show="show" :title="player?.name || $t('playerCard.title')" size="large" @close="$emit('close')">
    <div class="player-card">
      <div class="player-card__header">
        <PlayerAvatar :name="player?.name || ''" :uuid="data?.uuid || player?.uuid" />
        <div class="player-card__identity">
          <strong>{{ (data?.online ?? player?.isOnline) ? $t('players.online') : $t('playerCard.offline') }}</strong>
          <span v-if="data?.available">{{ data.source === 'live' ? $t('playerCard.liveRead') : $t('playerCard.lastSave') }} · {{ savedAt }}</span>
          <span v-if="data?.uuid" class="player-card__uuid">{{ data.uuid }}</span>
        </div>
        <AppButton variant="ghost" :loading="loading" :disabled="busy" @click="refresh()">{{ $t('playerCard.refresh') }}</AppButton>
      </div>
      <p v-if="error" class="player-card__error" role="alert">{{ error }}</p>
      <p v-if="notice" class="player-card__notice" role="status">{{ notice }}</p>
      <p v-if="data?.warning" class="player-card__warning" role="status">{{ data.warning }}</p>
      <p v-if="data && !data.available" class="player-card__muted">{{ $t('playerCard.noSave') }}</p>
      <template v-if="data?.available">
        <div class="player-card__stats">
          <div><span>{{ $t('playerCard.health') }}</span><strong>{{ number(data.health) }} HP</strong></div>
          <div><span>{{ $t('playerCard.food') }}</span><strong>{{ number(data.food) }} / 20</strong></div>
          <div><span>{{ $t('playerCard.experience') }}</span><strong>{{ number(data.experienceLevel) }}</strong></div>
          <div><span>{{ $t('playerCard.gameMode') }}</span><strong>{{ data.gameMode || '—' }}</strong></div>
        </div>
        <div class="player-card__location">
          <strong>{{ $t('playerCard.coordinates') }}</strong>
          <code v-if="data.position">X {{ number(data.position.x) }} · Y {{ number(data.position.y) }} · Z {{ number(data.position.z) }}</code>
          <span v-else>—</span>
          <span>{{ data.dimension || '—' }}</span>
        </div>
      </template>
      <section class="player-card__controls">
        <h3>{{ $t('playerCard.actions') }}</h3>
        <p v-if="!running || (data && !data.online)" class="player-card__muted">{{ $t('playerCard.onlineOnly') }}</p>
        <div class="player-card__buttons">
          <AppButton :disabled="!canAct" @click="act({ action: 'heal' })">{{ $t('playerCard.heal') }}</AppButton>
          <AppButton :disabled="!canAct" @click="act({ action: 'feed' })">{{ $t('playerCard.feed') }}</AppButton>
          <AppButton variant="ghost" :disabled="!canAct" @click="act({ action: 'clear_effects' })">{{ $t('playerCard.clearEffects') }}</AppButton>
        </div>
        <form class="player-card__form" @submit.prevent="act({ action: 'gamemode', mode })">
          <label>{{ $t('playerCard.gameMode') }}<select v-model="mode" :disabled="!canAct"><option v-for="value in ['survival','creative','adventure','spectator']" :key="value">{{ value }}</option></select></label>
          <AppButton type="submit" variant="ghost" :disabled="!canAct">{{ $t('playerCard.applyMode') }}</AppButton>
        </form>
        <form class="player-card__form player-card__teleport" @submit.prevent="act({ action: 'teleport', ...coords })">
          <label v-for="axis in ['x', 'y', 'z']" :key="axis">{{ axis.toUpperCase() }}<input v-model="coords[axis]" type="number" step="any" min="-29999984" max="29999984" required :disabled="!canAct" /></label>
          <label class="player-card__dimension">{{ $t('playerCard.dimension') }}<input v-model="coords.dimension" list="player-dimensions" required :disabled="!canAct" /></label>
          <datalist id="player-dimensions"><option value="minecraft:overworld" /><option value="minecraft:the_nether" /><option value="minecraft:the_end" /></datalist>
          <AppButton type="submit" variant="ghost" :disabled="!canAct">{{ $t('playerCard.teleport') }}</AppButton>
        </form>
        <form v-if="targets.length" class="player-card__form" @submit.prevent="act({ action: 'teleport_player', target: destination })">
          <label>{{ $t('playerCard.toPlayer') }}<select v-model="destination" required :disabled="!canAct"><option value="" disabled>{{ $t('playerCard.selectPlayer') }}</option><option v-for="p in targets" :key="p.name">{{ p.name }}</option></select></label>
          <AppButton type="submit" variant="ghost" :disabled="!canAct || !destination">{{ $t('playerCard.teleport') }}</AppButton>
        </form>
      </section>
      <template v-if="data?.available">
        <InventoryGrid :items="data.inventory" :slots="mainSlots" :label="$t('playerCard.inventory')" />
        <InventoryGrid :items="data.equipment" :slots="equipmentSlots" :label="$t('playerCard.equipment')" />
        <InventoryGrid :items="data.enderChest" :slots="enderSlots" :label="$t('playerCard.enderChest')" />
      </template>
    </div>
  </BaseModal>
</template>

<style scoped>
.player-card { display: flex; flex-direction: column; gap: var(--space-4); }
.player-card__header { display: flex; align-items: center; gap: var(--space-3); }
.player-card__identity { display: flex; flex-direction: column; flex: 1; min-width: 0; gap: 3px; }
.player-card__identity strong, h3 { color: var(--text-primary); }
.player-card__identity span { font-size: var(--text-xs); }
.player-card__uuid { color: var(--text-muted); overflow-wrap: anywhere; }
.player-card__stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-2); }
.player-card__stats > div { display: flex; flex-direction: column; gap: 4px; padding: var(--space-3); background: var(--bg-tertiary); border-radius: var(--radius-md); }
.player-card__stats span { font-size: var(--text-xs); }
.player-card__stats strong { color: var(--text-primary); }
.player-card__location { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3); padding: var(--space-3); border: 1px solid var(--border-color); border-radius: var(--radius-md); }
.player-card__location code { color: var(--text-primary); }
.player-card__controls { display: flex; flex-direction: column; gap: var(--space-3); }
h3 { margin: 0; font-size: var(--text-sm); }
p { margin: 0; }
.player-card__buttons, .player-card__form { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: end; }
label { display: flex; flex-direction: column; gap: 4px; font-size: var(--text-xs); }
input, select { color: var(--text-primary); background: var(--bg-tertiary); border: 1px solid var(--border-color); border-radius: var(--radius-sm); padding: 7px 8px; font: inherit; min-width: 0; }
input:focus, select:focus { outline: 2px solid var(--primary); }
input:disabled, select:disabled { opacity: .5; }
.player-card__teleport label { width: 85px; }
.player-card__teleport .player-card__dimension { flex: 1; min-width: 180px; }
.player-card__error, .player-card__warning, .player-card__notice { padding: var(--space-3); border-radius: var(--radius-sm); overflow-wrap: anywhere; }
.player-card__error { color: #fca5a5; background: #ef444415; }
.player-card__warning { color: #fcd34d; background: #f59e0b15; }
.player-card__notice { color: #86efac; background: #22c55e15; }
.player-card__muted { color: var(--text-muted); }
@media (max-width: 500px) { .player-card__stats { grid-template-columns: repeat(2, 1fr); } }
</style>
