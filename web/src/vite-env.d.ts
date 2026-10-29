/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Public default for the sign-in form's API address. Not a secret. */
  readonly VITE_API_BASE_URL?: string;
  /** "1" only in development: render the bundled synthetic DEMO fixture. */
  readonly VITE_MOCK?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
