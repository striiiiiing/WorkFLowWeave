import { createRouter, createWebHistory } from 'vue-router'
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: () => import('@/pages/dashboard/DashboardPage.vue'),
    },
    { path: '/workflows', component: () => import('@/views/WorkflowsView.vue') },
    { path: '/workflows/new', component: () => import('@/views/WorkflowEditView.vue') },
    {
      path: '/workflows/:id/edit',
      name: 'workflow-edit',
      component: () => import('@/views/WorkflowEditView.vue'),
    },
    { path: '/runs', name: 'runs', component: () => import('@/pages/runs/RunListPage.vue') },
    { path: '/runs/:id', name: 'run-detail', component: () => import('@/views/RunDetailView.vue') },
    {
      path: '/resources',
      name: 'resources',
      component: () => import('@/pages/resources/ResourcesPage.vue'),
    },
    { path: '/collector-demo', redirect: '/workflows' },
    {
      path: '/plugins',
      name: 'plugins',
      component: () => import('@/pages/plugins/PluginsPage.vue'),
    },
    { path: '/agents', component: () => import('@/views/AgentsView.vue') },
    { path: '/agents/:sessionId', component: () => import('@/views/AgentsView.vue') },
    { path: '/:pathMatch(.*)*', component: () => import('@/views/NotFoundView.vue') },
  ],
})
