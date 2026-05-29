import { createRouter, createWebHistory } from 'vue-router'
import FaultQueryView from '@/views/FaultQueryView.vue'
import KnowledgeExtractionView from '@/views/KnowledgeExtractionView.vue'
import OntologyBuilderView from '@/views/OntologyBuilderView.vue'
import OntologyGraphView from '@/views/OntologyGraphView.vue'
import VersionManagementView from '@/views/VersionManagementView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      redirect: '/ontology-builder',
    },
    {
      path: '/ontology',
      name: 'ontology',
      component: OntologyGraphView,
      meta: {
        title: '图谱展示',
        subtitle: 'Neo4j 图谱视图',
      },
    },
    {
      path: '/fault-query',
      name: 'fault-query',
      component: FaultQueryView,
      meta: {
        title: '故障链查询',
        subtitle: '故障现象推演',
      },
    },
    {
      path: '/ontology-builder',
      name: 'ontology-builder',
      component: OntologyBuilderView,
      meta: {
        title: '本体构建',
        subtitle: '本体编辑模块',
      },
    },
    {
      path: '/knowledge-extraction',
      name: 'knowledge-extraction',
      component: KnowledgeExtractionView,
      meta: {
        title: '图谱构建',
        subtitle: '多源知识导入',
      },
    },
    {
      path: '/version-management',
      name: 'version-management',
      component: VersionManagementView,
      meta: {
        title: '版本管理',
        subtitle: '图谱版本记录',
      },
    },
  ],
})

export default router
