import js from "@eslint/js";
import globals from "globals";
import jsdoc from "eslint-plugin-jsdoc";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["src_front/src/**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
      "no-console": "warn",
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          varsIgnorePattern: "^_",
          argsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
    },
  },
  {
    // One screen per function. Test files are exempt: every over-length
    // function there is a `describe()` suite wrapper, which is a namespace
    // rather than a unit read top to bottom, and no `it()` body comes close
    // to the cap. The Python side is covered by
    // `scripts/check_function_length.py`, since ruff has no equivalent rule.
    name: "function-length/source",
    files: ["src_front/src/**/*.{ts,tsx}"],
    ignores: ["src_front/src/test/**"],
    rules: {
      "max-lines-per-function": [
        "error",
        { max: 50, skipBlankLines: false, skipComments: false },
      ],
    },
  },
  {
    name: "jsdoc/source",
    files: ["src_front/src/**/*.{ts,tsx}"],
    ignores: ["src_front/src/test/**"],
    extends: [jsdoc.configs["flat/recommended-typescript-error"]],
    rules: {
      // Where a doc block is mandatory. Fixers are off everywhere they would
      // write a placeholder: lint-staged runs `eslint --fix` on commit, and an
      // auto-inserted empty block or `@param root0` stub would land in the
      // working tree while the commit still failed on the description rules.
      "jsdoc/require-jsdoc": [
        "error",
        {
          enableFixer: false,
          require: {
            ArrowFunctionExpression: false,
            FunctionExpression: false,
            FunctionDeclaration: true,
            ClassDeclaration: true,
            MethodDefinition: true,
          },
          contexts: [
            "VariableDeclarator > ArrowFunctionExpression",
            "TSInterfaceDeclaration",
            "TSTypeAliasDeclaration",
          ],
          exemptEmptyFunctions: false,
        },
      ],
      "jsdoc/require-file-overview": [
        "error",
        { tags: { file: { mustExist: true, preventDuplicates: true } } },
      ],

      // What a doc block must contain.
      "jsdoc/require-description": ["error", { descriptionStyle: "body" }],
      "jsdoc/require-param": [
        "error",
        { enableFixer: false, checkDestructured: true },
      ],
      "jsdoc/check-param-names": ["error", { enableFixer: false }],
      "jsdoc/require-param-description": "error",
      "jsdoc/require-returns": "error",
      "jsdoc/require-returns-description": "error",
      "jsdoc/require-returns-check": "error",

      // TypeScript supplies the types; `no-types` from the preset bans
      // duplicating them into @param/@returns tags.
      "jsdoc/no-types": "error",

      // The preset's bare `tag-lines` default (startLines: 0) makes --fix
      // delete the blank line between the description and the first tag.
      "jsdoc/tag-lines": ["error", "never", { startLines: 1 }],
    },
  },
);
