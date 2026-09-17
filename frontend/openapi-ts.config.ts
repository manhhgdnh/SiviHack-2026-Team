import { defineConfig } from "@hey-api/openapi-ts"

// Types and zod schemas generated from the backend's committed OpenAPI document.
// Regenerate with `npm run api:gen` after `uv run python -m app.openapi_export` in ../app.
export default defineConfig({
  input: "../app/openapi.json",
  output: { path: "src/api/generated", clean: true },
  plugins: [
    // Literal unions only: TS enums would violate `erasableSyntaxOnly`.
    { name: "@hey-api/typescript", enums: false },
    { name: "zod", compatibilityVersion: 4, definitions: true, requests: true, responses: true },
  ],
})
