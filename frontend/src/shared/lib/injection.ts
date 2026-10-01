import { inject, type InjectionKey } from 'vue'

export function requireDependency<T>(key: InjectionKey<T>, name: string): T {
  const dependency = inject(key)
  if (!dependency) throw new Error(`缺少 ${name} 注入；请在 app/bootstrap 中装配依赖`)
  return dependency
}
