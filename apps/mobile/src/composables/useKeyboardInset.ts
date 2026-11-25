import { onMounted, onUnmounted } from "vue";

export function useKeyboardInset(): void {
  function update(): void {
    const viewport = window.visualViewport;
    const inset = viewport ? Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop) : 0;
    document.documentElement.style.setProperty("--keyboard-inset", `${inset}px`);
  }

  onMounted(() => {
    update();
    window.visualViewport?.addEventListener("resize", update);
    window.visualViewport?.addEventListener("scroll", update);
  });

  onUnmounted(() => {
    window.visualViewport?.removeEventListener("resize", update);
    window.visualViewport?.removeEventListener("scroll", update);
    document.documentElement.style.setProperty("--keyboard-inset", "0px");
  });
}
