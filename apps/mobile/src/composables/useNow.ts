import { onMounted, onUnmounted, ref, type Ref } from "vue";

export function useNow(intervalMs = 1000): Ref<Date> {
  const now = ref(new Date());
  let timer = 0;

  function tick(): void {
    now.value = new Date();
  }

  function start(): void {
    stop();
    if (document.hidden) {
      return;
    }
    timer = window.setInterval(tick, intervalMs);
  }

  function stop(): void {
    window.clearInterval(timer);
  }

  function onVisibility(): void {
    tick();
    if (document.hidden) {
      stop();
      return;
    }
    start();
  }

  onMounted(() => {
    tick();
    start();
    document.addEventListener("visibilitychange", onVisibility);
  });

  onUnmounted(() => {
    stop();
    document.removeEventListener("visibilitychange", onVisibility);
  });

  return now;
}
