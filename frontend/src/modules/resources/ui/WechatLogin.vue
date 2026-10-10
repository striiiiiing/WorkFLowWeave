<script setup lang="ts">
import type { JsonObject } from '@/shared/types'
import { useWechatLogin } from '../composables/useWechatLogin'

const props = defineProps<{ options: JsonObject }>()
const emit = defineEmits<{ update: [value: JsonObject] }>()
const { status, error, busy, code, start, cancel, verify } = useWechatLogin(
  () => props.options, (value) => emit('update', value),
)
</script>

<template>
  <section class="wechat-login mb-4" aria-label="微信扫码登录">
    <p>网页扫码登录微信，Token 将自动保存到本地文件供后续使用。</p>
    <p class="muted text-sm">微信 iLink 平台限制：每条用户消息对应的 context_token 最多只能回复 10 条消息。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <p v-if="status" role="status">{{ status.message }}</p>
    <p v-else-if="options.account_id" role="status">已配置账号：{{ options.account_id }}</p>
    <img v-if="status?.qr_image" :src="status.qr_image" alt="微信登录二维码" width="256" height="256" />
    <p v-if="status?.qr_url">
      <a :href="status.qr_url" target="_blank" rel="noopener noreferrer">打开微信二维码链接</a>
    </p>
    <div v-if="status?.state === 'verify_required'" class="mb-3">
      <el-input v-model="code" aria-label="微信数字确认码" inputmode="numeric" maxlength="16"
        placeholder="手机微信显示的数字" @keyup.enter="verify" />
      <el-button :loading="busy" @click="verify">提交数字</el-button>
    </div>
    <div class="flex flex-wrap gap-2 mt-3">
      <el-button type="primary" :loading="busy" @click="start">
        {{ status && !['connected', 'failed'].includes(status.state) ? '刷新二维码' : '扫码登录' }}
      </el-button>
      <el-button v-if="status && !['connected', 'failed'].includes(status.state)" @click="cancel">取消登录</el-button>
    </div>
  </section>
</template>

<style scoped>
.wechat-login img { max-width: 100%; height: auto; }
.wechat-login p { overflow-wrap: anywhere; }
</style>
