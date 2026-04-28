import { onCleanup, onMount } from "solid-js";
import { gsap } from "gsap";
import { AppStateProvider } from "./contexts/AppState";
import { CommandCenter } from "./screens/CommandCenter";

export const App = () => {
  let rootRef: HTMLDivElement | undefined;

  onMount(() => {
    const context = gsap.context(() => {
      gsap.from("[data-gsap='nav-item']", {
        opacity: 0,
        y: 16,
        duration: 0.75,
        stagger: 0.055,
        ease: "power3.out"
      });
      gsap.from("[data-gsap='panel']", {
        opacity: 0,
        y: 28,
        duration: 1,
        stagger: 0.08,
        ease: "expo.out"
      });
      gsap.to(".pulse-dot", {
        scale: 1.6,
        opacity: 0.34,
        duration: 1.15,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut"
      });
      gsap.to(".scanline", {
        y: 18,
        opacity: 0.42,
        duration: 2.2,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut"
      });
      gsap.to(".brand-core", {
        y: -2,
        duration: 1.6,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut"
      });
    }, rootRef);

    onCleanup(() => context.revert());
  });

  return (
    <AppStateProvider>
      <div ref={rootRef} class="app-shell">
        <CommandCenter />
      </div>
    </AppStateProvider>
  );
};
