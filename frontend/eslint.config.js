import globals from "globals";
import pluginJs from "@eslint/js";
import pluginReact from "eslint-plugin-react";
import pluginReactHooks from "eslint-plugin-react-hooks";
import pluginUnusedImports from "eslint-plugin-unused-imports";

export default [
  {
    files: [
      "src/components/**/*.{js,mjs,cjs,jsx}",
      "src/pages/**/*.{js,mjs,cjs,jsx}",
      "src/Layout.jsx",
    ],
    ignores: ["src/lib/**/*", "src/components/ui/**/*"],
    ...pluginJs.configs.recommended,
    ...pluginReact.configs.flat.recommended,
    languageOptions: {
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: 2022,
        sourceType: "module",
        ecmaFeatures: {
          jsx: true,
        },
      },
    },
    settings: {
      react: {
        version: "detect",
      },
    },
    plugins: {
      react: pluginReact,
      "react-hooks": pluginReactHooks,
      "unused-imports": pluginUnusedImports,
    },
    rules: {
      "no-unused-vars": "off",
      "react/jsx-uses-vars": "error",
      "react/jsx-uses-react": "error",
      "unused-imports/no-unused-imports": "error",
      "unused-imports/no-unused-vars": [
        "warn",
        {
          vars: "all",
          varsIgnorePattern: "^_",
          args: "after-used",
          argsIgnorePattern: "^_",
        },
      ],
      "react/prop-types": "off",
      "react/react-in-jsx-scope": "off",
      "react/no-unknown-property": [
        "error",
        { ignore: ["cmdk-input-wrapper", "toast-close"] },
      ],
      "react-hooks/rules-of-hooks": "error",
    },
  },
  {
    // A handler used outside the scope that defines it is a ReferenceError that
    // only fires on click, so nothing renders wrong until a person presses it.
    // no-undef is off project-wide (it needs a clean baseline), but the inbox
    // chat surface is clean and must stay that way.
    files: ["src/components/inbox/ChannelChat.jsx", "src/components/inbox/whatsapp/**/*.jsx", "src/pages/Inbox.jsx"],
    rules: { "no-undef": "error" },
  },
  {
    // A name used but never defined is a ReferenceError that only fires when the screen is
    // actually used, so the build, the unit tests and the SSR render tests all stay green:
    // createCountQueue, setPayError and commitDecision each shipped that way and each blanked a
    // screen in the live stack. The components tree is clean apart from three browser globals, so
    // it is held to no-undef from here on.
    files: ["src/cashier/components/**/*.{js,jsx}", "src/cashier/routes/**/*.{js,jsx}"],
    languageOptions: {
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: 2022,
        sourceType: "module",
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: { "react-hooks": pluginReactHooks },
    rules: { "no-undef": "error" },
  },
];
