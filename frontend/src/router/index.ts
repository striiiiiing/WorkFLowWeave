import { createRouter, createWebHistory } from 'vue-router'
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: () => import('@/views/DashboardView.vue') },
    { path: '/workflows', component: () => import('@/views/WorkflowsView.vue') },
    { path: '/workflows/new', component: () => import('@/views/WorkflowEditView.vue') },
    { path: '/workflows/:id/edit', component: () => import('@/views/WorkflowEditView.vue') },
    { path: '/runs', component: () => import('@/views/RunsView.vue') },
    { path: '/runs/:id', component: () => import('@/views/RunDetailView.vue') },
    { path: '/resources', component: () => import('@/views/ResourcesView.vue') },
    { path: '/plugins', component: () => import('@/views/PluginsView.vue') },
    { path: '/:pathMatch(.*)*', component: () => import('@/views/NotFoundView.vue') },
  ],
})
