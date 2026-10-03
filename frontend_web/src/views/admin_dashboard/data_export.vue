<script setup>
import { ref } from 'vue'
import AppShell from '../../components/AppShell.vue'
import { blobApi, qs } from '../../api/request.js'
import { downloadBlob } from '../../utils.js'

const startDate = ref('')
const endDate = ref('')
const status = ref('')
const loading = ref(false)
const error = ref('')

async function download() {
  loading.value = true; error.value = ''
  try {
    const { blob, headers } = await blobApi(`/bookings/admin/export.xlsx${qs({ start_date: startDate.value, end_date: endDate.value, status: status.value })}`)
    const cd = headers.get('Content-Disposition') || ''
    const match = cd.match(/filename="?([^";]+)"?/i)
    downloadBlob(blob, match?.[1] || 'duxue_bookings.xlsx')
  } catch (e) { error.value = e.message } finally { loading.value = false }
}
</script>

<template>
  <AppShell title="数据导出">
    <div class="page-header"><div><h2 class="page-title">全维度预约数据导出</h2><p class="page-desc">按日期和订单状态筛选，导出 Excel；包含用户、预约、审核、OCR、清扫核验及违规字段。</p></div></div>
    <div class="card card-pad" style="max-width:820px">
      <div v-if="error" class="error">{{ error }}</div>
      <div class="form-grid">
        <div class="field"><label class="label">开始日期</label><input v-model="startDate" class="input" type="date" style="width:100%"></div>
        <div class="field"><label class="label">结束日期</label><input v-model="endDate" class="input" type="date" style="width:100%"></div>
        <div class="field"><label class="label">预约状态</label><select v-model="status" class="select" style="width:100%"><option value="">全部</option><option value="pending_manual">待人工审核</option><option value="approved">已通过</option><option value="active">使用中</option><option value="awaiting_cleanup">待清扫</option><option value="completed">已完结</option><option value="rejected">已驳回</option><option value="invalidated">冲突失效</option><option value="cancelled">已取消</option></select></div>
      </div>
      <div style="margin-top:18px"><button class="btn btn-primary" :disabled="loading" @click="download">{{ loading ? '生成中…' : '导出 Excel' }}</button></div>
    </div>
  </AppShell>
</template>
