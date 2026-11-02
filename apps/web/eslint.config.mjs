import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const config = [
  ...nextCoreWebVitals,
  ...nextTypescript,
  {
    rules: {
      "react/no-danger": "error",
    },
  },
  {
    ignores: [".next/**", "out/**", "node_modules/**", "next-env.d.ts", "coverage/**"],
  },
];

export default config;
