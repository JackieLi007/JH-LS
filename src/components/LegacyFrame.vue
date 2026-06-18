<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref } from 'vue'

defineProps<{
  src: string
  title: string
}>()

const frameRef = ref<HTMLIFrameElement | null>(null)
const frameHeight = ref('960px')

let frameResizeObserver: ResizeObserver | null = null

function stopFrameObserver() {
  if (frameResizeObserver) {
    frameResizeObserver.disconnect()
    frameResizeObserver = null
  }
}

function syncFrameHeight() {
  const frame = frameRef.value
  const doc = frame?.contentDocument
  if (!frame || !doc) return

  const body = doc.body
  const html = doc.documentElement
  const nextHeight = Math.max(
    body?.scrollHeight ?? 0,
    body?.offsetHeight ?? 0,
    html?.scrollHeight ?? 0,
    html?.offsetHeight ?? 0,
    720,
  )
  frameHeight.value = `${nextHeight}px`
}

function observeFrameSize() {
  stopFrameObserver()
  const doc = frameRef.value?.contentDocument
  if (!doc?.body) return

  syncFrameHeight()
  frameResizeObserver = new ResizeObserver(() => {
    syncFrameHeight()
  })
  frameResizeObserver.observe(doc.body)
  frameResizeObserver.observe(doc.documentElement)
}

function handleLoad() {
  nextTick(() => {
    observeFrameSize()
    syncFrameHeight()
  })
}

onBeforeUnmount(() => {
  stopFrameObserver()
})
</script>

<template>
  <div class="legacy-frame-wrap">
    <iframe
      ref="frameRef"
      class="legacy-frame"
      :src="src"
      :title="title"
      :style="{ height: frameHeight }"
      @load="handleLoad"
    />
  </div>
</template>

<style scoped>
.legacy-frame-wrap {
  width: 100%;
  min-height: 720px;
  overflow: visible;
  border: 1px solid #dbe6f3;
  border-radius: 8px;
  background: #f8fbff;
  box-shadow: 0 18px 44px rgba(22, 47, 89, 0.08);
}

.legacy-frame {
  width: 100%;
  display: block;
  border: 0;
  background: #f8fbff;
}
</style>
