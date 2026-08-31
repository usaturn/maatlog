import js from "@eslint/js";
import compat from "eslint-plugin-compat";
import globals from "globals";

export default [
  {
    ignores: ["build/**", "dist/**", "docs/_build/**", "public/**", "tests/**/generated/**"],
  },
  js.configs.recommended,
  {
    files: ["src/maatlog/themes/**/*.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        ...globals.browser,
      },
    },
    plugins: {
      compat,
    },
    rules: {
      "compat/compat": "error",
    },
  },
];
