<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  slots: { type: Array, required: true },
  label: { type: String, required: true },
})
const selectedSlot = ref(null)
const bySlot = computed(() => new Map(props.items.map(item => [item.slot, item])))
const selected = computed(() => bySlot.value.get(selectedSlot.value))
const title = item => item ? item.id.split(':').at(-1).replaceAll('_', ' ') : ''
watch(() => props.items, () => {
  if (!bySlot.value.has(selectedSlot.value)) selectedSlot.value = null
})
</script>

<template>
  <section class="inventory" :aria-label="label">
    <h3>{{ label }} <span>{{ $t('playerCard.readOnly') }}</span></h3>
    <div class="inventory__grid" :class="{ 'inventory__grid--equipment': slots.length < 9 }">
      <button v-for="slot in slots" :key="slot" type="button" class="inventory__slot"
        :class="{ 'inventory__slot--filled': bySlot.has(slot), 'inventory__slot--selected': selectedSlot === slot }"
        :aria-label="`${label}, ${slot}: ${bySlot.has(slot) ? `${bySlot.get(slot).id} × ${bySlot.get(slot).count}` : $t('playerCard.emptySlot')}`"
        :aria-pressed="selectedSlot === slot" :title="bySlot.get(slot)?.id || String(slot)"
        @click="selectedSlot = selectedSlot === slot ? null : slot">
        <span class="inventory__slot-id">{{ slot }}</span>
        <span v-if="bySlot.has(slot)" class="inventory__item">{{ title(bySlot.get(slot)) }}</span>
        <span v-if="bySlot.has(slot)" class="inventory__count">{{ bySlot.get(slot).count }}</span>
      </button>
    </div>
    <div v-if="selected" class="inventory__detail">
      <strong>{{ selected.id }} × {{ selected.count }}</strong>
      <details><summary>{{ $t('playerCard.itemData') }}</summary><pre>{{ selected.data }}</pre></details>
    </div>
  </section>
</template>

<style scoped>
.inventory h3 { margin: 0 0 var(--space-2); color: var(--text-primary); font-size: var(--text-sm); }
.inventory h3 span { margin-left: var(--space-2); color: var(--text-muted); font-size: var(--text-xs); font-weight: 400; }
.inventory__grid { display: grid; grid-template-columns: repeat(9, minmax(0, 1fr)); gap: 5px; }
.inventory__grid--equipment { grid-template-columns: repeat(auto-fit, minmax(70px, 1fr)); }
.inventory__slot { position: relative; min-height: 70px; padding: 17px 4px 16px; border: 1px solid var(--border-color); border-radius: var(--radius-sm); background: var(--bg-tertiary); color: var(--text-muted); cursor: pointer; font: inherit; }
.inventory__slot--filled { background: var(--bg-secondary); color: var(--text-primary); }
.inventory__slot:hover, .inventory__slot--selected { border-color: var(--primary); }
.inventory__slot:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.inventory__slot-id { position: absolute; top: 3px; left: 5px; color: var(--text-muted); font-size: 10px; }
.inventory__item { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; font-size: 11px; line-height: 1.2; }
.inventory__count { position: absolute; bottom: 2px; right: 5px; font-size: 12px; font-weight: 700; }
.inventory__detail { margin-top: var(--space-2); padding: var(--space-2); background: var(--bg-tertiary); border-radius: var(--radius-sm); overflow-wrap: anywhere; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 11px; max-height: 180px; overflow: auto; }
summary { cursor: pointer; margin-top: var(--space-2); }
@media (max-width: 500px) { .inventory__slot { min-height: 62px; padding-inline: 1px; } .inventory__item { font-size: 9px; } .inventory__grid { gap: 3px; } }
</style>
