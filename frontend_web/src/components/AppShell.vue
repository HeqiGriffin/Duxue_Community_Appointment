<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { clearSession, getSession } from '../api/request.js'

const props = defineProps({ title: { type: String, required: true } })
const router = useRouter()
const session = getSession() || {}
const isAdmin = computed(() => session.role === 'admin')
const canDuty = computed(() => session.mode === 'duty' || isAdmin.value)
function logout() { clearSession(); router.replace('/login') }
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-title">笃学书院 · 空间管理</div>
        <div class="brand-sub">Community Space Console</div>
      </div>
      <nav class="nav">
        <template v-if="isAdmin">
          <div class="nav-section">管理中心</div>
          <router-link to="/admin/bookings">预约 / 违规管理</router-link>
          <router-link to="/admin/schedule">值班排班</router-link>
          <router-link to="/admin/appeals">申诉处理</router-link>
          <router-link to="/admin/duty-history">值班记录</router-link>
          <router-link to="/admin/duty-terminal">值班电脑绑定</router-link>
          <router-link to="/admin/export">数据导出</router-link>
        </template>
        <template v-if="canDuty">
          <div class="nav-section">值班工作台</div>
          <router-link to="/duty/handover">值班任务 / 巡视</router-link>
          <router-link to="/duty/rooms">实时房间雷达</router-link>
          <router-link to="/duty/print">打印中心</router-link>
        </template>
      </nav>
      <div class="sidebar-footer">
        <div class="user-name">{{ session.name || session.login_id }}</div>
        <div class="user-meta">{{ session.role === 'admin' ? '管理员' : '值班学生' }} · {{ session.login_id }}</div>
        <button class="logout" @click="logout">退出登录</button>
      </div>
    </aside>
    <main class="main">
      <header class="topbar">
        <h1>{{ props.title }}</h1>
        <div class="mode">{{ session.mode === 'duty' ? '值班终端模式' : '管理模式' }}</div>
      </header>
      <div class="page"><slot /></div>
    </main>
  </div>
</template>
