import { createRouter, createWebHistory } from 'vue-router'
const agentPage = () => import('@/pages/agents/AgentPage.vue')
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: () => import('@/pages/dashboard/DashboardPage.vue'),
    },
    {
      path: '/workflows',
      name: 'workflows',
      component: () => import('@/pages/workflows/WorkflowListPage.vue'),
    },
    {
      path: '/workflows/new',
      name: 'workflow-new',
      component: () => import('@/pages/workflows/WorkflowEditPage.vue'),
    },
    {
      path: '/workflows/:id/edit',
      name: 'workflow-edit',
      component: () => import('@/pages/workflows/WorkflowEditPage.vue'),
    },
    { path: '/runs', name: 'runs', component: () => import('@/pages/runs/RunListPage.vue') },
    {
      path: '/runs/:id',
      name: 'run-detail',
      component: () => import('@/pages/runs/RunDetailPage.vue'),
    },
    {
      path: '/resources',
      name: 'resources',
      component: () => import('@/pages/resources/ResourcesPage.vue'),
    },
    {
      path: '/plugins',
      name: 'plugins',
      component: () => import('@/pages/plugins/PluginsPage.vue'),
    },
    { path: '/agents', name: 'agents', component: agentPage },
    { path: '/agents/:sessionId', name: 'agent-session', component: agentPage },
    { path: '/:pathMatch(.*)*', component: () => import('@/pages/NotFoundPage.vue') },
  ],
})
