<script setup lang="ts">
/** 用户管理（admin）。 */
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import { api } from '../api/client'

const rows = ref<any[]>([])
const dialog = reactive({
  visible: false,
  form: { username: '', password: '', display_name: '', role: 'sales', can_set_price: false },
})

async function load() {
  rows.value = (await api.get('/users')).data
}
onMounted(load)

async function create() {
  await api.post('/users', dialog.form)
  dialog.visible = false
  dialog.form = { username: '', password: '', display_name: '', role: 'sales', can_set_price: false }
  await load()
  ElMessage.success('已创建')
}

async function toggle(row: any, field: string, value: any) {
  await api.patch(`/users/${row.id}`, { [field]: value })
  await load()
}

async function resetPassword(row: any) {
  const { value } = await (await import('element-plus')).ElMessageBox.prompt(
    `为 ${row.display_name} 设置新密码（至少 8 位）`, '重置密码',
    { inputPattern: /^.{8,}$/, inputErrorMessage: '至少 8 位' },
  )
  await api.patch(`/users/${row.id}`, { password: value })
  ElMessage.success('已重置')
}
</script>

<template>
  <el-card>
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        用户管理
        <el-button type="primary" size="small" @click="dialog.visible = true">新建账号</el-button>
      </div>
    </template>
    <el-table :data="rows">
      <el-table-column prop="username" label="用户名" width="140" />
      <el-table-column prop="display_name" label="姓名" width="140" />
      <el-table-column label="角色" width="120">
        <template #default="{ row }">
          <el-tag :type="row.role === 'admin' ? 'danger' : 'primary'" size="small">
            {{ row.role === 'admin' ? '管理员' : '业务员' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="录价权" width="110">
        <template #default="{ row }">
          <el-switch
            :model-value="row.can_set_price" :disabled="row.role === 'admin'"
            @update:model-value="(v: boolean) => toggle(row, 'can_set_price', v)"
          />
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-switch
            :model-value="row.is_active"
            @update:model-value="(v: boolean) => toggle(row, 'is_active', v)"
          />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button size="small" @click="resetPassword(row)">重置密码</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <el-dialog v-model="dialog.visible" title="新建账号" width="460">
    <el-form label-width="90px">
      <el-form-item label="用户名" required><el-input v-model="dialog.form.username" /></el-form-item>
      <el-form-item label="初始密码" required>
        <el-input v-model="dialog.form.password" placeholder="至少 8 位" />
      </el-form-item>
      <el-form-item label="姓名" required><el-input v-model="dialog.form.display_name" /></el-form-item>
      <el-form-item label="角色">
        <el-radio-group v-model="dialog.form.role">
          <el-radio value="sales">业务员</el-radio>
          <el-radio value="admin">管理员</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="dialog.form.role === 'sales'" label="录价权">
        <el-switch v-model="dialog.form.can_set_price" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialog.visible = false">取消</el-button>
      <el-button type="primary" @click="create">创建</el-button>
    </template>
  </el-dialog>
</template>
