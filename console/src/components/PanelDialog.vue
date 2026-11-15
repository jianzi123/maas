<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from "vue";
const props = defineProps<{ title: string; busy?: boolean }>();
const emit = defineEmits<{ close: [] }>();
const element = ref<HTMLDialogElement>();
let previous: HTMLElement | null = null;
function close() {
  if (!props.busy) emit("close");
}
onMounted(() => {
  previous = document.activeElement as HTMLElement | null;
  const d = element.value;
  if (d?.showModal) d.showModal();
  else d?.setAttribute("open", "");
});
onBeforeUnmount(() => {
  element.value?.close?.();
  if (previous?.isConnected) previous.focus();
});
</script>
<template>
  <dialog
    ref="element"
    class="panel-dialog"
    aria-labelledby="dialog-title"
    @cancel.prevent="close"
    @click="
      (event) => {
        if (event.target === element) close();
      }
    "
  >
    <section class="dialog-body">
      <div class="dialog-heading">
        <h2 id="dialog-title">{{ title }}</h2>
        <button
          type="button"
          class="quiet"
          aria-label="关闭弹窗"
          :disabled="busy"
          @click="close"
        >
          ×
        </button>
      </div>
      <slot />
    </section>
  </dialog>
</template>
