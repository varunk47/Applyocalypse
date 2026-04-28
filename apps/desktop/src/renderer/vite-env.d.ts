import type { ApplyocalypsePreloadApi } from "../preload";

declare global {
  interface Window {
    applyocalypse: ApplyocalypsePreloadApi;
  }
}

export {};
