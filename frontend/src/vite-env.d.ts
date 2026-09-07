/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Absolute base URL of the backend API; empty string means same origin. */
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}