<script setup>
import { useRouter } from 'vue-router'
import { clearSession } from '../api/request.js'
const router = useRouter()
function exit() { clearSession(); router.replace('/login') }
</script>
<template>
  <div class="login-page"><div class="card login-card">
    <div class="login-brand">当前账号未进入 Web 工作模式</div>
    <div class="login-sub">普通学生请使用微信小程序预约；值班电脑登录后会自动进入值班工作台。</div>
    <button class="btn btn-primary" @click="exit">返回登录</button>
  </div></div>
</template>
