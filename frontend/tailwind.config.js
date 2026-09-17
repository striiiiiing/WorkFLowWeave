/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // [Design Decision DEC-COLOR-01 & DEC-COLOR-02]
        // 映射设计文档中定义的语义色彩与 AAA 对比度色阶
        brand: {
          50: '#eff6ff',
          100: '#dbeafe',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
        },
      },
      fontFamily: {
        // [Design Decision DEC-TYPO-01 & DEC-TYPO-02]
        sans: [
          '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto',
          '"PingFang SC"', '"Hiragino Sans GB"', '"Microsoft YaHei"', 'sans-serif'
        ],
        mono: [
          '"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo',
          'Monaco', 'Consolas', 'monospace'
        ]
      },
      minHeight: {
        // [Design Decision DEC-LAYOUT-02] 移动端最小 44px 触控目标
        touch: '44px',
      },
      minWidth: {
        touch: '44px',
      }
    },
  },
  plugins: [],
}
