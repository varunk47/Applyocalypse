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

      const interactiveSelector = "button:not(:disabled), .artifact-row";
      const onPointerOver = (event: PointerEvent) => {
        const target = (event.target as Element | null)?.closest<HTMLElement>(interactiveSelector);
        if (!target || !rootRef?.contains(target) || target.contains(event.relatedTarget as Node | null)) {
          return;
        }
        gsap.to(target, {
          y: -1,
          scale: 1.01,
          duration: 0.22,
          ease: "power3.out",
          overwrite: "auto"
        });
      };
      const onPointerOut = (event: PointerEvent) => {
        const target = (event.target as Element | null)?.closest<HTMLElement>(interactiveSelector);
        if (!target || !rootRef?.contains(target) || target.contains(event.relatedTarget as Node | null)) {
          return;
        }
        gsap.to(target, {
          y: 0,
          scale: 1,
          duration: 0.28,
          ease: "power3.out",
          overwrite: "auto"
        });
      };
      const onPointerDown = (event: PointerEvent) => {
        const target = (event.target as Element | null)?.closest<HTMLElement>(interactiveSelector);
        if (!target || !rootRef?.contains(target)) {
          return;
        }
        gsap.to(target, {
          y: 1,
          scale: 0.985,
          duration: 0.08,
          ease: "power2.out",
          overwrite: "auto"
        });
      };
      const onPointerUp = (event: PointerEvent) => {
        const target = (event.target as Element | null)?.closest<HTMLElement>(interactiveSelector);
        if (!target || !rootRef?.contains(target)) {
          return;
        }
        gsap.to(target, {
          y: -1,
          scale: 1.01,
          duration: 0.18,
          ease: "power3.out",
          overwrite: "auto"
        });
      };

      rootRef?.addEventListener("pointerover", onPointerOver);
      rootRef?.addEventListener("pointerout", onPointerOut);
      rootRef?.addEventListener("pointerdown", onPointerDown);
      rootRef?.addEventListener("pointerup", onPointerUp);

      return () => {
        rootRef?.removeEventListener("pointerover", onPointerOver);
        rootRef?.removeEventListener("pointerout", onPointerOut);
        rootRef?.removeEventListener("pointerdown", onPointerDown);
        rootRef?.removeEventListener("pointerup", onPointerUp);
      };
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
