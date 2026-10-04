<script setup>
import { onMounted, ref } from 'vue'
import AppShell from '../../components/AppShell.vue'
import { jsonApi } from '../../api/request.js'
import { fmtDateTime } from '../../utils.js'
const rows = ref([]); const error = ref(''); const loading = ref(false)
async function load(){ loading.value=true; error.value=''; try{rows.value=await jsonApi('/duty/admin/logs?limit=200')}catch(e){error.value=e.message}finally{loading.value=false}}
function patrolText(p){ if(!p.submitted_at) return '未完成'; return p.timing_status==='late'?'已完成（迟交）':'已完成' }
onMounted(load)
</script>
<template>
  <AppShell title="值班记录">
    <div class="page-header"><div><h2 class="page-title">值班履职记录</h2><p class="page-desc">查看每名值班学生的签到、两次巡视、异常反馈与交接情况。</p></div><button class="btn btn-secondary" @click="load">刷新</button></div>
    <div v-if="error" class="error">{{error}}</div>
    <div class="card card-pad"><div class="table-wrap"><table><thead><tr><th>日期/班次</th><th>值班学生</th><th>班级</th><th>签到</th><th>巡视完成</th><th>巡视详情</th><th>交接</th></tr></thead><tbody>
      <tr v-for="x in rows" :key="x.log_id"><td>{{x.shift_date}}<br>{{String(x.start_hour).padStart(2,'0')}}:00–{{String(x.start_hour+2).padStart(2,'0')}}:00</td><td><strong>{{x.user_name}}</strong><br><span class="muted">{{x.login_id}}</span></td><td>{{x.class_name||'—'}}</td><td>{{fmtDateTime(x.checkin_at)}}</td><td><span class="badge" :class="x.patrol_completed>=2?'green':'orange'">{{x.patrol_completed}} / 2</span><br><span v-if="x.late_patrols" class="muted">迟交 {{x.late_patrols}} 次</span></td><td><div v-for="p in x.patrols" :key="p.id" style="margin-bottom:8px"><strong>第{{p.sequence}}次：</strong>{{patrolText(p)}}<br><span class="muted">{{p.submitted_at?fmtDateTime(p.submitted_at):fmtDateTime(p.due_at)}} · {{p.issue_note||'—'}}</span></div></td><td><span class="badge" :class="x.handover_at?'green':'gray'">{{x.handover_at?'已交接':'未交接'}}</span><br><span class="muted">{{x.handover_note||'—'}}</span></td></tr>
    </tbody></table><div v-if="!rows.length&&!loading" class="empty">暂无值班记录</div></div></div>
  </AppShell>
</template>
