<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'

type MenuItem = {
  to: string
  index: string
  title: string
  note: string
}

const route = useRoute()

const menuItems: MenuItem[] = [
  {
    to: '/ontology-builder',
    index: '01',
    title: '本体构建',
    note: '可视化编辑排故知识图谱本体',
  },
  {
    to: '/knowledge-extraction',
    index: '02',
    title: '图谱构建',
    note: '表格、文档、图片多源图谱构建',
  },
  {
    to: '/version-management',
    index: '03',
    title: '版本管理',
    note: '查看和回退图谱导入版本',
  },
  {
    to: '/ontology',
    index: '04',
    title: '图谱展示',
    note: '查看图谱树、全量图谱和节点关系',
  },
  {
    to: '/fault-query',
    index: '05',
    title: '故障链查询',
    note: '输入故障现象并查看推演链路',
  },
]

const title = computed(() => String(route.meta.title ?? '智能排故知识图谱'))
const subtitle = computed(() => String(route.meta.subtitle ?? '统一菜单入口'))
</script>

<template>
  <div class="app-shell">
    <aside class="app-sidebar">
      <div class="brand-block">
        <div class="brand-kicker">Knowledge Graph</div>
        <h1>智能排故知识图谱</h1>
      </div>

      <nav class="nav-list" aria-label="主菜单">
          <RouterLink
            v-for="item in menuItems"
            :key="item.to"
            :to="item.to"
            class="nav-item"
            active-class="active"
          >
            <span class="nav-index">{{ item.index }}</span>
            <span class="nav-copy">
              <span class="nav-title">{{ item.title }}</span>
              <span class="nav-note">{{ item.note }}</span>
            </span>
          </RouterLink>
      </nav>
    </aside>

    <main class="app-main">
      <header class="app-topbar">
        <div>
          <h2>{{ title }}</h2>
        </div>
        <span>{{ subtitle }}</span>
      </header>

      <section class="route-panel">
        <RouterView />
      </section>
    </main>
  </div>
</template>

<style scoped>
:global(body) {
  margin: 0;
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  color: #13253f;
  background: #edf4fb;
}

:global(*) {
  box-sizing: border-box;
}

.app-shell {
  min-height: 100vh;
  height: 100vh;
  display: grid;
  grid-template-columns: 292px minmax(0, 1fr);
  background: linear-gradient(180deg, #eef4fb, #f8fbff);
  overflow: hidden;
}

.app-sidebar {
  padding: 22px 16px;
  color: #edf5ff;
  background:
    radial-gradient(circle at 24px 24px, rgba(83, 145, 255, 0.38), transparent 26%),
    linear-gradient(180deg, #0b1a31, #0f2b4d 58%, #133a69);
  overflow: auto;
}

.brand-block {
  padding: 4px 6px 18px;
}

.brand-kicker {
  font-size: 12px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: #95baff;
}

.brand-block h1 {
  margin: 10px 0 0;
  font-size: 28px;
  line-height: 1.1;
}

.nav-list {
  display: grid;
  gap: 12px;
}

.nav-item {
  min-width: 0;
  border: 1px solid rgba(198, 216, 245, 0.18);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  padding: 12px;
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
  color: #eaf3ff;
  text-decoration: none;
  transition:
    transform 0.18s ease,
    border-color 0.18s ease,
    background 0.18s ease;
}

.nav-item:hover {
  transform: translateY(-1px);
  border-color: rgba(147, 189, 255, 0.42);
  background: rgba(255, 255, 255, 0.07);
}

.nav-item.active {
  border-color: #8ab2ff;
  background: linear-gradient(180deg, rgba(92, 141, 232, 0.22), rgba(49, 87, 163, 0.18));
  box-shadow: inset 0 0 0 1px rgba(157, 193, 255, 0.22);
}

.nav-index {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: rgba(255, 255, 255, 0.12);
  color: #9fc0ff;
  font-size: 12px;
  font-weight: 900;
}

.nav-copy {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.nav-title {
  color: #fff;
  font-size: 14px;
  font-weight: 900;
}

.nav-note {
  color: #bdd1ef;
  font-size: 11px;
  line-height: 1.4;
}

.app-main {
  min-width: 0;
  min-height: 0;
  padding: 14px;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 12px;
  overflow: hidden;
}

.app-topbar {
  min-height: 72px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 18px;
  padding: 0 4px;
}

.app-topbar h2 {
  margin: 0;
  color: #17355e;
  font-size: 28px;
  line-height: 1.05;
}

.app-topbar > span {
  display: inline-flex;
  align-items: center;
  min-height: 34px;
  padding: 0 14px;
  border-radius: 999px;
  background: #dbeee5;
  color: #127653;
  font-size: 13px;
  font-weight: 800;
}

.route-panel {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

@media (max-width: 980px) {
  .app-shell {
    grid-template-columns: 1fr;
    grid-template-rows: auto minmax(0, 1fr);
  }

  .app-sidebar {
    max-height: 42vh;
  }

  .app-main {
    min-height: 0;
  }
}
</style>
