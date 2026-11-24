<script setup lang="ts">
import { computed, ref, watch } from "vue";
import Spinner from "../ui/Spinner.vue";
import AppIcon from "../ui/AppIcon.vue";

const MAX_DISPLAY_ROWS = 1000;

const props = defineProps<{
  content: string;
  delimiter?: "," | "\t";
  readonly?: boolean;
  saving?: boolean;
}>();

const emit = defineEmits<{
  save: [csvText: string];
}>();

function parseDelimited(raw: string, delim: string): { headers: string[]; rows: string[][] } {
  if (!raw) return { headers: ["列 1"], rows: [] };
  const allRows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let inQuotes = false;

  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i];
    if (inQuotes) {
      if (ch === '"') {
        if (raw[i + 1] === '"') {
          cell += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        cell += ch;
      }
      continue;
    }

    if (ch === '"') {
      inQuotes = true;
    } else if (ch === delim) {
      row.push(cell);
      cell = "";
    } else if (ch === "\r" || ch === "\n") {
      if (ch === "\r" && raw[i + 1] === "\n") i++;
      row.push(cell);
      cell = "";
      if (row.some((c) => c.length > 0) || allRows.length > 0) {
        allRows.push(row);
      }
      row = [];
    } else {
      cell += ch;
    }
  }
  if (cell.length > 0 || row.length > 0) {
    row.push(cell);
    allRows.push(row);
  }

  if (!allRows.length) return { headers: ["列 1"], rows: [] };
  const colCount = Math.max(1, ...allRows.map((r) => r.length));
  const normalize = (r: string[]) => {
    const out = r.slice();
    while (out.length < colCount) out.push("");
    return out;
  };
  const headers = normalize(allRows[0]);
  const rows = allRows.slice(1).map(normalize);
  return { headers, rows };
}

function escapeCell(val: string, delim: string): string {
  const s = val ?? "";
  if (s.includes('"') || s.includes(delim) || s.includes("\n") || s.includes("\r")) {
    return `"${s.replaceAll('"', '""')}"`;
  }
  return s;
}

function serializeDelimited(headers: string[], rows: string[][], delim: string): string {
  const lines = [
    headers.map((h) => escapeCell(h, delim)).join(delim),
    ...rows.map((r) => headers.map((_, ci) => escapeCell(r[ci] ?? "", delim)).join(delim)),
  ];
  return lines.join("\n");
}

const delim = computed(() => props.delimiter ?? ",");
const headers = ref<string[]>([]);
const rows = ref<string[][]>([]);
const editing = ref(false);
const dirty = ref(false);
const filterQuery = ref("");

function loadFromProps() {
  const parsed = parseDelimited(props.content, delim.value);
  headers.value = parsed.headers;
  rows.value = parsed.rows;
  dirty.value = false;
}

watch(
  [() => props.content, delim],
  () => {
    loadFromProps();
  },
  { immediate: true },
);

const indexedRows = computed(() => {
  const q = filterQuery.value.trim().toLowerCase();
  const list = rows.value.map((cells, idx) => ({ idx, cells }));
  if (!q) return list.slice(0, MAX_DISPLAY_ROWS);
  return list
    .filter(({ cells }) => cells.some((c) => c.toLowerCase().includes(q)))
    .slice(0, MAX_DISPLAY_ROWS);
});

function onHeaderInput(ci: number, val: string) {
  headers.value[ci] = val;
  dirty.value = true;
}

function onCellInput(ri: number, ci: number, val: string) {
  if (!rows.value[ri]) return;
  rows.value[ri][ci] = val;
  dirty.value = true;
}

function addRow() {
  rows.value.push(headers.value.map(() => ""));
  dirty.value = true;
}

function deleteRow(ri: number) {
  rows.value.splice(ri, 1);
  dirty.value = true;
}

function addColumn() {
  const name = `列 ${headers.value.length + 1}`;
  headers.value.push(name);
  for (const r of rows.value) {
    r.push("");
  }
  dirty.value = true;
}

function deleteColumn(ci: number) {
  if (headers.value.length <= 1) return;
  headers.value.splice(ci, 1);
  for (const r of rows.value) {
    r.splice(ci, 1);
  }
  dirty.value = true;
}

function cancelEdit() {
  loadFromProps();
  editing.value = false;
}

function saveChanges() {
  if (props.saving) return;
  const serialized = serializeDelimited(headers.value, rows.value, delim.value);
  emit("save", serialized);
  dirty.value = false;
  editing.value = false;
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <!-- Toolbar -->
    <div class="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-line/70 px-3 py-2">
      <div class="flex min-w-0 items-center gap-2">
        <input
          v-model="filterQuery"
          type="text"
          placeholder="筛选表格内容…"
          class="focus-ring h-7 w-40 rounded-lg bg-surface px-2.5 text-[12px] text-fg placeholder:text-fg-faint sm:w-52"
        />
        <span class="shrink-0 text-[11.5px] tabular-nums text-fg-faint">
          {{ rows.length }} 行 × {{ headers.length }} 列
        </span>
      </div>

      <div v-if="!readonly" class="flex items-center gap-1.5">
        <template v-if="editing">
          <button
            type="button"
            class="focus-ring rounded-lg bg-surface px-2 py-1 text-[11.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            @click="addRow"
          >
            + 行
          </button>
          <button
            type="button"
            class="focus-ring rounded-lg bg-surface px-2 py-1 text-[11.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            @click="addColumn"
          >
            + 列
          </button>
          <button
            type="button"
            class="focus-ring rounded-lg px-2 py-1 text-[11.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            :disabled="saving"
            @click="cancelEdit"
          >
            取消
          </button>
          <button
            type="button"
            class="focus-ring inline-flex items-center gap-1 rounded-lg bg-primary px-2.5 py-1 text-[11.5px] font-medium text-primary-fg transition-colors hover:bg-primary-hover disabled:opacity-50"
            :disabled="saving || !dirty"
            @click="saveChanges"
          >
            <Spinner v-if="saving" :size="11" />
            <span>{{ saving ? "保存中…" : "保存表格" }}</span>
          </button>
        </template>
        <button
          v-else
          type="button"
          class="focus-ring inline-flex items-center gap-1 rounded-lg bg-surface px-2.5 py-1 text-[11.5px] font-medium text-fg transition-colors hover:bg-hover"
          @click="editing = true"
        >
          <AppIcon name="edit" class="h-3.5 w-3.5" :stroke-width="1.9" />
          <span>编辑表格</span>
        </button>
      </div>
    </div>

    <!-- Table Grid -->
    <div v-scrollbar class="custom-scrollbar min-h-0 flex-1 overflow-auto p-3">
      <div class="inline-block min-w-full overflow-hidden rounded-xl border border-line bg-canvas">
        <table class="w-full border-collapse text-left text-[12.5px]">
          <thead class="sticky top-0 z-10 bg-surface">
            <tr>
              <th class="w-10 border-b border-r border-line px-2 py-1.5 text-center text-[11px] font-medium text-fg-faint">
                #
              </th>
              <th
                v-for="(h, ci) in headers"
                :key="ci"
                class="min-w-[110px] border-b border-r border-line px-2.5 py-1.5 font-semibold text-fg last:border-r-0"
              >
                <div v-if="editing" class="flex items-center gap-1">
                  <input
                    :value="h"
                    type="text"
                    class="w-full min-w-0 rounded bg-canvas px-1.5 py-0.5 text-[12.5px] font-semibold text-fg outline-none ring-1 ring-line focus:ring-accent"
                    @input="onHeaderInput(ci, ($event.target as HTMLInputElement).value)"
                  />
                  <button
                    v-if="headers.length > 1"
                    type="button"
                    class="flex h-5 w-5 shrink-0 items-center justify-center rounded text-fg-faint hover:bg-danger-weak hover:text-danger"
                    title="删除此列"
                    @click="deleteColumn(ci)"
                  >
                    ×
                  </button>
                </div>
                <span v-else class="block whitespace-nowrap">{{ h || `列 ${ci + 1}` }}</span>
              </th>
              <th v-if="editing" class="w-9 border-b border-line px-1.5 py-1.5 text-center text-[11px] text-fg-faint">
                删
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in indexedRows"
              :key="item.idx"
              class="border-b border-line/70 last:border-b-0 odd:bg-canvas even:bg-sidebar/40 hover:bg-hover/40"
            >
              <td class="border-r border-line/70 px-2 py-1.5 text-center text-[11px] tabular-nums text-fg-faint">
                {{ item.idx + 1 }}
              </td>
              <td
                v-for="(_, ci) in headers"
                :key="ci"
                class="border-r border-line/70 px-2.5 py-1.5 align-top text-fg last:border-r-0"
              >
                <input
                  v-if="editing"
                  :value="item.cells[ci] ?? ''"
                  type="text"
                  class="w-full min-w-[90px] rounded bg-canvas px-1.5 py-0.5 text-[12.5px] text-fg outline-none ring-1 ring-transparent focus:ring-accent"
                  @input="onCellInput(item.idx, ci, ($event.target as HTMLInputElement).value)"
                />
                <span v-else class="block max-w-[320px] whitespace-pre-wrap break-words">{{ item.cells[ci] ?? "" }}</span>
              </td>
              <td v-if="editing" class="px-1.5 py-1 text-center">
                <button
                  type="button"
                  class="flex h-6 w-6 items-center justify-center rounded text-fg-faint hover:bg-danger-weak hover:text-danger"
                  title="删除此行"
                  @click="deleteRow(item.idx)"
                >
                  ×
                </button>
              </td>
            </tr>
            <tr v-if="indexedRows.length === 0">
              <td :colspan="headers.length + (editing ? 2 : 1)" class="py-8 text-center text-[12.5px] text-fg-faint">
                {{ filterQuery.trim() ? "未找到匹配的表格行" : "表格暂无数据行" }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="rows.length > MAX_DISPLAY_ROWS" class="mt-2 text-center text-[11.5px] text-fg-faint">
        表格共 {{ rows.length }} 行，当前显示前 {{ MAX_DISPLAY_ROWS }} 行。
      </p>
    </div>
  </div>
</template>
