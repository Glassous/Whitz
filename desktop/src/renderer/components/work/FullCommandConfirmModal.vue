<script setup lang="ts">
import { ref } from "vue";
import BaseModal from "@web/components/ui/BaseModal.vue";
import BaseButton from "@web/components/ui/BaseButton.vue";

const props = defineProps<{
  open: boolean;
}>();

const emit = defineEmits<{
  close: [];
  confirm: [];
}>();

const agreed = ref(false);

function handleClose() {
  agreed.value = false;
  emit("close");
}

function handleConfirm() {
  if (!agreed.value) return;
  agreed.value = false;
  emit("confirm");
}
</script>

<template>
  <BaseModal :open="props.open" title="警告：启用完全命令模式" max-width="460px" @close="handleClose">
    <div class="space-y-4 text-[13px] leading-relaxed text-fg-muted">
      <div class="rounded-xl bg-danger-weak px-3.5 py-2.5 text-danger">
        <p class="font-semibold">高风险自动执行警告</p>
        <p class="mt-1 text-[12.5px]">
          开启「完全命令模式」后，OpenCode 在工作区内调用的<strong>全部终端命令（bash）将自动放行并立即执行</strong>，不再逐条弹窗请求你的审批。
        </p>
      </div>

      <ul class="list-disc space-y-1.5 pl-5 text-[12.5px] text-fg-muted">
        <li>模型可能直接执行依赖安装、测试构建、文件修改或删除等带有副作用的 Shell 命令；</li>
        <li>文件编辑（edit）等其他非 bash 权限仍受 OpenCode 权限配置约束；</li>
        <li>任务运行期间你仍可随时点击停止按钮或从输入框开关关闭此模式。</li>
      </ul>

      <label class="flex cursor-pointer items-start gap-2.5 rounded-xl bg-surface px-3 py-2.5 text-[12.5px] text-fg">
        <input v-model="agreed" type="checkbox" class="mt-0.5 accent-primary" />
        <span>我已充分了解自动执行终端命令的风险，并同意由本机自动批准全部 bash 命令。</span>
      </label>

      <div class="flex justify-end gap-2 pt-1">
        <BaseButton size="sm" variant="ghost" @click="handleClose">取消</BaseButton>
        <BaseButton size="sm" variant="danger" :disabled="!agreed" @click="handleConfirm">
          同意并启用完全命令模式
        </BaseButton>
      </div>
    </div>
  </BaseModal>
</template>
