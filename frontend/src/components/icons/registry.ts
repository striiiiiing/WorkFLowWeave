import {
  Database,
  Bot,
  Mail,
  Workflow,
  Play,
  Menu,
  Cpu,
  Settings,
  Sun,
  Moon,
  LayoutDashboard,
} from 'lucide-vue-next'

export const icons = {
  database: Database,
  bot: Bot,
  mail: Mail,
  workflow: Workflow,
  play: Play,
  menu: Menu,
  cpu: Cpu,
  settings: Settings,
  sun: Sun,
  moon: Moon,
  dashboard: LayoutDashboard,
} as const
export type IconName = keyof typeof icons
