<script setup lang="ts">
import DynamischeView from './Dynamische.vue'
</script>

<template>
  <div class="integrated-page">
    <DynamischeView initial-view="fault" embedded />
  </div>
</template>

<style scoped>
.integrated-page {
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
</style>
