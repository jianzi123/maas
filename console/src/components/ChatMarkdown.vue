<script setup lang="ts">
import { computed } from "vue";
import { renderMarkdown } from "../chat/render";
const props = defineProps<{ content: string }>();
const html = computed(() => renderMarkdown(props.content));
</script>
<template><div class="chat-markdown" v-html="html"></div></template>
