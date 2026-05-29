<script setup lang="ts">
defineProps<{
  src: string
  title: string
}>()
</script>

<template>
  <div class="legacy-frame-wrap">
    <iframe class="legacy-frame" :src="src" :title="title" />
  </div>
</template>

<style scoped>
.legacy-frame-wrap {
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  border: 1px solid #dbe6f3;
  border-radius: 8px;
  background: #f8fbff;
  box-shadow: 0 18px 44px rgba(22, 47, 89, 0.08);
}

.legacy-frame {
  width: 100%;
  height: 100%;
  display: block;
  border: 0;
  background: #f8fbff;
}
</style>
