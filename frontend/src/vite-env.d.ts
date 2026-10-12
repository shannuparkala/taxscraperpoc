/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL for the backend API. Empty in dev — Vite proxies /api. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
