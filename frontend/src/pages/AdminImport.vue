<script setup lang="ts">
/** 数据导入向导（admin）：上传 → dry-run 校验报告 → 确认入库。 */
import { ElMessage } from 'element-plus'
import { onMounted, ref } from 'vue'

import { api } from '../api/client'

const batches = ref<any[]>([])
const currentBatch = ref<any | null>(null)
const uploading = ref(false)
const confirming = ref(false)

async function load() {
  batches.value = (await api.get('/imports')).data
}
onMounted(load)

async function onFile(file: File) {
  const form = new FormData()
  form.append('file', file)
  uploading.value = true
  try {
    const { data } = await api.post('/imports/dry-run', form)
    currentBatch.value = data
    await load()
    ElMessage.success(`校验完成：可入库 ${data.ok_rows} 行，错误 ${data.error_rows} 行`)
  } catch (e: any) {
    if (e?.response?.status === 422) ElMessage.error(String(e.response.data.detail))
  } finally {
    uploading.value = false
  }
  return false
}

async function confirm() {
  if (!currentBatch.value) return
  confirming.value = true
  try {
    const { data } = await api.post(`/imports/${currentBatch.value.id}/confirm`)
    currentBatch.value = data
    await load()
    ElMessage.success(`入库完成：成功 ${data.ok_rows} 行`)
  } finally {
    confirming.value = false
  }
}

function reportRows(batch: any) {
  const r = batch?.report_json
  return r?.commit_report ?? r?.report ?? []
}

const statusLabel: Record<string, string> = {
  new: '将新建', exists: '已存在', created: '已创建', error: '错误',
}
</script>

<template>
  <el-row :gutter="12">
    <el-col :span="15">
      <el-card>
        <template #header>存量数据导入</template>
        <el-upload
          drag :auto-upload="true" :show-file-list="false" accept=".xlsx"
          :before-upload="onFile"
        >
          <div style="padding: 30px" v-loading="uploading">
            把 Excel（.xlsx）拖到这里，或点击上传<br />
            <small style="color: var(--el-text-color-secondary)">
              上传后先做 dry-run 校验，确认报告无误再入库；同一文件只能提交一次（幂等）
            </small>
          </div>
        </el-upload>

        <el-alert
          type="info" :closable="false" style="margin-top: 12px" title="模板格式"
          description="表头第一行：root_type_code | price | currency | valid_from 为固定列；属性列写 attr:属性code（嵌套用 槽code.属性code，如 attr:CYLINDER.MATERIAL）；黑盒成品件列写 part:槽code，单元格填 供应商名|件名（自动建档/复用）。"
        />

        <template v-if="currentBatch">
          <el-divider />
          <h4>
            批次 #{{ currentBatch.id }}（{{ currentBatch.filename }}）
            <el-tag size="small">{{ currentBatch.status }}</el-tag>
            ：共 {{ currentBatch.total_rows }} 行，可入库 {{ currentBatch.ok_rows }}，错误 {{ currentBatch.error_rows }}
          </h4>
          <el-table :data="reportRows(currentBatch)" size="small" height="300">
            <el-table-column prop="row_no" label="行号" width="70" />
            <el-table-column label="结果" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="row.status === 'error' ? 'danger' : row.status === 'exists' ? 'warning' : 'success'">
                  {{ statusLabel[row.status] ?? row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="说明">
              <template #default="{ row }">
                {{ row.message ?? row.sku_code ?? row.matched ?? '' }} {{ row.price_note ?? '' }}
              </template>
            </el-table-column>
          </el-table>
          <el-button
            v-if="currentBatch.status === 'dry_run'" type="primary" style="margin-top: 10px"
            :loading="confirming" @click="confirm"
          >确认入库（错误行将跳过）</el-button>
        </template>
      </el-card>
    </el-col>
    <el-col :span="9">
      <el-card>
        <template #header>历史批次</template>
        <el-table :data="batches" size="small" @row-click="(r: any) => currentBatch = r">
          <el-table-column prop="id" label="#" width="50" />
          <el-table-column prop="filename" label="文件" min-width="140" />
          <el-table-column prop="status" label="状态" width="90" />
          <el-table-column prop="ok_rows" label="成功" width="60" />
        </el-table>
      </el-card>
    </el-col>
  </el-row>
</template>

<style scoped>
/* 拖拽悬停时品牌高亮（hover 边框已由令牌变工业蓝，此处补浅底反馈） */
:deep(.el-upload-dragger.is-dragover) {
  background: var(--el-color-primary-light-9);
  border-color: var(--ph-brand-600);
}
</style>
