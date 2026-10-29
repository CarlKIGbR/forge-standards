// typescript-eslint strict; no `any` without a comment (STANDARDS spec section 4).
import tseslint from "typescript-eslint";

export default tseslint.config(
  ...tseslint.configs.strict,
  {
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/ban-ts-comment": ["error", { "ts-ignore": true, "ts-nocheck": true, "ts-expect-error": "allow-with-description" }],
    },
  },
);
