<script setup>
import { ref } from 'vue'
import AppShell from '../../components/AppShell.vue'
import { getDutyTerminalToken, jsonApi, setDutyTerminalToken } from '../../api/request.js'
const token=ref(getDutyTerminalToken()); const error=ref(''); const success=ref(''); const verified=ref(false)
async function save(){error.value='';success.value='';verified.value=false; setDutyTerminalToken(token.value.trim()); try{const r=await jsonApi('/auth/terminal-status'); verified.value=!!r.is_duty_terminal; success.value=verified.value?'该浏览器已成功绑定为值班终端。现在退出管理员账号，由值班学生登录即可进入值班工作台。':'Token 已保存，但服务器未识别为值班终端，请核对服务器 .env 中 DUTY_TERMINAL_TOKEN。'}catch(e){error.value=e.message}}
function clear(){setDutyTerminalToken('');token.value='';verified.value=false;success.value='已清除本浏览器的值班终端绑定。'}
</script>
<template><AppShell title="值班电脑绑定"><div class="page-header"><div><h2 class="page-title">绑定社区值班公共电脑</h2><p class="page-desc">只需在公共电脑上操作一次。Token 保存在该浏览器本地，不写入网页源码。</p></div></div><div v-if="error" class="error">{{error}}</div><div v-if="success" class="success">{{success}}</div><div class="card card-pad" style="max-width:760px"><div class="field"><label class="label">值班终端 Token</label><input v-model="token" class="input" type="password" style="width:100%" placeholder="填写服务器 .env 中 DUTY_TERMINAL_TOKEN 的值"></div><div class="actions" style="margin-top:14px"><button class="btn btn-primary" :disabled="!token.trim()" @click="save">保存并验证</button><button class="btn btn-ghost" @click="clear">解除本机绑定</button></div><p class="muted">建议只在固定的书院公共值班电脑上绑定。学生在其他电脑或手机登录仍是普通模式。</p></div></AppShell></template>
