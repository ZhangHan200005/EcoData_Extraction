import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Generated output and local material that is intentionally outside this app:
    "dist/**",
    ".vinext/**",
    ".wrangler/**",
    "node_modules/**",
    ".codex_ppt_*/**",
    "MVP_v1/**",
    "mvp_v1.1/**",
    "full_pipeline_prototype/**",
    "references/**",
    "src/**",
    "docs/archive/**",
    "docs/coordination/**",
    "docs/learning/**",
  ]),
]);

export default eslintConfig;
