<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { jsonApi, setSession } from '../api/request.js'

const router = useRouter()
const loginId = ref('')
const password = ref('')
const oldPassword = ref('')
const newPassword = ref('')
const session = ref(null)
const loading = ref(false)
const error = ref('')

function goHome(s) {
  if (s.role === 'admin') router.replace('/admin/bookings')
  else if (s.mode === 'duty') router.replace('/duty/handover')
  else router.replace('/forbidden')
}

async function login() {
  loading.value = true; error.value = ''
  try {
    const data = await jsonApi('/auth/login', { method: 'POST', body: { login_id: loginId.value.trim(), password: password.value } })
    setSession(data)
    if (data.must_change_password) { session.value = data; oldPassword.value = password.value; return }
    goHome(data)
  } catch (e) { error.value = e.message } finally { loading.value = false }
}

async function changePassword() {
  if (!/[A-Za-z]/.test(newPassword.value) || !/\d/.test(newPassword.value)) { error.value = '新密码必须同时包含字母和数字'; return }
  loading.value = true; error.value = ''
  try {
    const data = await jsonApi('/auth/change-password', { method: 'POST', body: { old_password: oldPassword.value, new_password: newPassword.value } })
    setSession(data); goHome(data)
  } catch (e) { error.value = e.message } finally { loading.value = false }
}
</script>

<template>
  <div class="login-page">
    <div class="card login-card">
      <div class="login-brand">笃学书院社区空间管理</div>
      <div class="login-sub">管理后台 / 值班工作台</div>
      <div v-if="error" class="error">{{ error }}</div>
      <template v-if="!session">
        <div class="field"><label class="label">学号 / 工号</label><input v-model="loginId" class="input" autocomplete="username" @keyup.enter="login" /></div>
        <div class="field"><label class="label">密码</label><input v-model="password" class="input" type="password" autocomplete="current-password" @keyup.enter="login" /></div>
        <button class="btn btn-primary" :disabled="loading || !loginId || !password" @click="login">{{ loading ? '登录中…' : '登录' }}</button>
      </template>
      <template v-else>
        <div class="success">首次登录必须修改密码后才能继续。</div>
        <div class="field"><label class="label">原密码</label><input v-model="oldPassword" class="input" type="password" /></div>
        <div class="field"><label class="label">新密码（至少包含字母和数字）</label><input v-model="newPassword" class="input" type="password" /></div>
        <button class="btn btn-primary" :disabled="loading || !newPassword" @click="changePassword">修改密码并进入系统</button>
      </template>
    </div>
  </div>
</template>
