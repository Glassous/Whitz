<script setup lang="ts">
import { computed, ref } from "vue";
import { useWorkStore } from "../../stores/work";

const work = useWorkStore();
const query = ref("");
const editingId = ref<string | null>(null);
const editingTitle = ref("");

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return work.conversations;
  return work.conversations.filter((item) => item.title.toLowerCase().includes(q));
});

async function create() {
  await work.create();
  editingId.value = null;
}

function startRename(id: string, title: string) {
  editingId.value = id;
  editingTitle.value = title;
}

async function commitRename() {
  if (!editingId.value) return;
  const id = editingId.value;
  const title = editingTitle.value.trim();
  editingId.value = null;
  if (title) await work.rename(id, title);
}

async function remove(id: string, title: string) {
  if (!window.confirm(`删除本地对话「${title}」？此操作不可恢复。`)) return;
  await work.remove(id);
  if (!work.current) {
    const next = work.conversations[0];
    if (next) await work.select(next.id);
  }
}
</script>

<template>
  <aside class="flex h-full w-[264px] shrink-0 flex-col border-r border-line bg-sidebar/70">
    <div class="flex items-center justify-between px-3.5 pb-2 pt-3.5">
      <div class="flex items-center gap-2">
        <span class="h-1.5 w-1.5 rounded-full" style="background: var(--work-accent)"></span>
        <span class="text-[11px] font-medium uppercase tracking-[0.16em] text-fg-faint">本地会话</span>
      </div>
      <button
        type="button"
        class="focus-ring rounded-lg border border-line bg-canvas px-2 py-1 text-[11.5px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
        @click="create"
      >
        新建
      </button>
    </div>

    <div class="px-3 pb-2">
      <input
        v-model="query"
        type="search"
        placeholder="搜索本地对话"
        class="focus-ring w-full rounded-lg border border-line bg-canvas px-2.5 py-1.5 text-[12px] text-fg placeholder:text-fg-faint"
      />
    </div>

    <nav class="min-h-0 flex-1 overflow-y-auto custom-scrollbar px-2 pb-3">
      <div
        v-for="item in filtered"
        :key="item.id"
        role="button"
        tabindex="0"
        class="group mb-0.5 flex w-full cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors"
        :class="work.current?.conversation.id === item.id ? 'bg-active text-fg' : 'text-fg-muted hover:bg-hover hover:text-fg'"
        @click="work.select(item.id)"
        @dblclick="startRename(item.id, item.title)"
        @keydown.enter.prevent="work.select(item.id)"
      >
        <template v-if="editingId === item.id">
          <input
            v-model="editingTitle"
            type="text"
            autofocus
            class="w-full rounded border border-line bg-canvas px-1.5 py-0.5 text-[12.5px] text-fg"
            @keydown.enter.prevent="commitRename"
            @keydown.esc.prevent="editingId = null"
            @click.stop
          />
        </template>
        <template v-else>
          <span class="min-w-0 flex-1 truncate text-[12.5px]">{{ item.title }}</span>
          <button
            type="button"
            class="focus-ring hidden shrink-0 rounded px-1 text-[10.5px] text-fg-faint hover:text-danger group-hover:block"
            title="删除"
            @click.stop="remove(item.id, item.title)"
          >
            删除
          </button>
        </template>
      </div>

      <p v-if="!filtered.length" class="px-2.5 py-6 text-[12px] text-fg-faint">
        还没有本地对话。新建一个，所有消息只留在本机。
      </p>
    </nav>

    <div class="border-t border-line px-3.5 py-3 text-[11px] text-fg-faint">
      仅保存在本机 · 不同步云端
    </div>
  </aside>
</template>
