import type { WorkApi } from "../shared/ipc-contract";

declare global {
  interface Window {
    whitzDesktop?: WorkApi;
  }
}

export {};
