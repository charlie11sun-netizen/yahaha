import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({
  baseDirectory: import.meta.dirname,
});

const eslintConfig = [
  {
    ignores: [".next/**", "node_modules/**", "lib/api-types.ts", "next-env.d.ts"],
  },
  ...compat.config({
    extends: ["next/core-web-vitals", "next/typescript"],
  }),
  {
    // Game covers, signed object URLs, and local upload previews intentionally
    // bypass the Next image proxy; their hosts and lifetimes are user-defined.
    rules: { "@next/next/no-img-element": "off" },
  },
];

export default eslintConfig;
