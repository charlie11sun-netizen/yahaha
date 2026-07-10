import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const npmCli = process.env.npm_execpath;
const generatedTypes = resolve("lib/api-types.ts");
const schemaFile = resolve(".openapi.json");
const before = readFileSync(generatedTypes, "utf8");

function run(script) {
  if (!npmCli) throw new Error("npm_execpath is unavailable; run this check through `npm run openapi:check`.");
  const result = spawnSync(process.execPath, [npmCli, "run", script], {
    cwd: process.cwd(),
    encoding: "utf8",
    stdio: "inherit",
  });
  if (result.status !== 0) {
    const error = new Error(result.error?.message || `npm run ${script} failed`);
    error.exitCode = result.status ?? 1;
    throw error;
  }
}

try {
  run("openapi:schema");
  run("openapi:types");
  const after = readFileSync(generatedTypes, "utf8");
  if (after !== before) {
    writeFileSync(generatedTypes, before, "utf8");
    console.error("Generated OpenAPI types are stale. Run `npm run openapi:generate` and commit lib/api-types.ts.");
    process.exitCode = 1;
  } else {
    console.log("Generated OpenAPI types match the backend schema.");
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = error?.exitCode ?? 1;
} finally {
  rmSync(schemaFile, { force: true });
}
