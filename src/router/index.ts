import { createRouter, createWebHistory } from 'vue-router'

import MainShell from '@/layouts/MainShell.vue'
import { useAuthStore, type AuthRole } from '@/stores/auth'
import FaultQueryView from '@/views/FaultQueryView.vue'
import KnowledgeExtractionView from '@/views/KnowledgeExtractionView.vue'
import LoginView from '@/views/LoginView.vue'
import OntologyBuilderView from '@/views/OntologyBuilderView.vue'
import OntologyGraphView from '@/views/OntologyGraphView.vue'
import VersionManagementView from '@/views/VersionManagementView.vue'

const editorRoles: AuthRole[] = ['editor']
const viewerRoles: AuthRole[] = ['viewer']

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: LoginView,
      meta: {
        public: true,
        title: '账号登录',
      },
    },
    {
      path: '/',
      component: MainShell,
      meta: {
        requiresAuth: true,
      },
      children: [
        {
          path: '',
          name: 'home',
          component: OntologyBuilderView,
          meta: {
            requiresAuth: true,
            roles: editorRoles,
            title: '本体构建',
            subtitle: '本体编辑模块',
          },
        },
        {
          path: 'ontology-builder',
          name: 'ontology-builder',
          component: OntologyBuilderView,
          meta: {
            requiresAuth: true,
            roles: editorRoles,
            title: '本体构建',
            subtitle: '本体编辑模块',
          },
        },
        {
          path: 'knowledge-extraction',
          name: 'knowledge-extraction',
          component: KnowledgeExtractionView,
          meta: {
            requiresAuth: true,
            roles: editorRoles,
            title: '图谱构建',
            subtitle: '多源知识导入',
          },
        },
        {
          path: 'version-management',
          name: 'version-management',
          component: VersionManagementView,
          meta: {
            requiresAuth: true,
            roles: editorRoles,
            title: '版本管理',
            subtitle: '图谱版本记录',
          },
        },
        {
          path: 'ontology',
          name: 'ontology',
          component: OntologyGraphView,
          meta: {
            requiresAuth: true,
            roles: viewerRoles,
            title: '图谱展示',
            subtitle: 'Neo4j 图谱视图',
          },
        },
        {
          path: 'fault-query',
          name: 'fault-query',
          component: FaultQueryView,
          meta: {
            requiresAuth: true,
            roles: viewerRoles,
            title: '故障链查询',
            subtitle: '故障现象推演',
          },
        },
      ],
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/',
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.restoreSession()

  if (to.meta.public) {
    return auth.user ? auth.user.homePath : true
  }

  if (!auth.user) {
    return {
      name: 'login',
      query: to.fullPath === '/' ? {} : { redirect: to.fullPath },
    }
  }

  const roles = to.meta.roles as AuthRole[] | undefined
  if (roles?.length && !roles.includes(auth.user.role)) {
    return auth.user.homePath
  }

  if (to.name === 'home') {
    return auth.user.homePath
  }

  return true
})

export default router
