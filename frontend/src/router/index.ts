import { createRouter, createWebHistory } from 'vue-router'
import DashboardView from '@/views/DashboardView.vue'
import WorkflowsView from '@/views/WorkflowsView.vue'
import WorkflowEditView from '@/views/WorkflowEditView.vue'
import RunsView from '@/views/RunsView.vue'
import RunDetailView from '@/views/RunDetailView.vue'
import ResourcesView from '@/views/ResourcesView.vue'
import PluginsView from '@/views/PluginsView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: DashboardView,
    },
    {
      path: '/workflows',
      name: 'workflows',
      component: WorkflowsView,
    },
    {
      path: '/workflows/new',
      name: 'workflow-new',
      component: WorkflowEditView,
    },
    {
      path: '/workflows/:id/edit',
      name: 'workflow-edit',
      component: WorkflowEditView,
    },
    {
      path: '/runs',
      name: 'runs',
      component: RunsView,
    },
    {
      path: '/runs/:id',
      name: 'run-detail',
      component: RunDetailView,
    },
    {
      path: '/resources',
      name: 'resources',
      component: ResourcesView,
    },
    {
      path: '/plugins',
      name: 'plugins',
      component: PluginsView,
    },
  ],
})
