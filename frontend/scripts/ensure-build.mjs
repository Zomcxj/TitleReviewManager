#!/usr/bin/env node
/**
 * Ensure the frontend build output is up to date.
 *
 * Background: frontend/dist is no longer version-controlled (every build emits hashed file
 * names, so committing it only produces piles of meaningless diffs). But start.bat /
 * start.sh depend on dist existing to serve the UI — so the startup scripts must be able to
 * build the frontend themselves, or a freshly cloned repo opens to nothing but 404.
 *
 * Logic:
 *   - dist/index.html does not exist → build
 *   - node_modules does not exist    → npm install first, then build
 *   - a file under src/ is newer than dist/index.html → rebuild
 *   - otherwise skip (avoid waiting for a build on every startup)
 *
 * Exit codes: 0 = usable; 1 = build failed (the caller should abort startup)
 */
import { existsSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const frontendDir = resolve(here, "..");
const distIndex = join(frontendDir, "dist", "index.html");
const srcDir = join(frontendDir, "src");
const nodeModules = join(frontendDir, "node_modules");

/** Recursively find the newest file mtime under a directory, used to check whether sources are newer than the build output */
function newestMtime(dir) {
  let newest = 0;
  const walk = (current) => {
    let entries;
    try {
      entries = readdirSync(current, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const full = join(current, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else {
        try {
          const t = statSync(full).mtimeMs;
          if (t > newest) newest = t;
        } catch {
          /* files that fail to stat can simply be ignored; they do not affect the build decision */
        }
      }
    }
  };
  walk(dir);
  return newest;
}

function run(command, args, label) {
  console.log(`        ${label}`);
  const result = spawnSync(command, args, {
    cwd: frontendDir,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  if (result.error) {
    console.error(`  ✗ ${label} 执行失败: ${result.error.message}`);
    return false;
  }
  if (result.status !== 0) {
    console.error(`  ✗ ${label} 失败（退出码 ${result.status}）`);
    return false;
  }
  return true;
}

function main() {
  const needsBuild = (() => {
    if (!existsSync(distIndex)) {
      console.log("        dist 不存在，需要构建");
      return true;
    }
    if (!existsSync(nodeModules)) {
      console.log("        node_modules 不存在，需要安装依赖");
      return true;
    }
    const distTime = statSync(distIndex).mtimeMs;
    const srcTime = newestMtime(srcDir);
    // Config file changes should also trigger a rebuild
    const configTime = Math.max(
      ...[
        "vite.config.ts",
        "package.json",
        "tsconfig.json",
        "index.html",
      ]
        .map((f) => join(frontendDir, f))
        .filter((f) => existsSync(f))
        .map((f) => {
          try {
            return statSync(f).mtimeMs;
          } catch {
            return 0;
          }
        }),
      0,
    );
    const newestSource = Math.max(srcTime, configTime);
    if (newestSource > distTime) {
      console.log("        源码比 dist 新，需要重新构建");
      return true;
    }
    console.log("        dist 已是最新，跳过构建");
    return false;
  })();

  if (!needsBuild) return 0;

  if (!existsSync(nodeModules)) {
    if (!run("npm", ["install", "--no-audit", "--no-fund"], "安装前端依赖...")) {
      return 1;
    }
  }

  if (!run("npm", ["run", "build"], "构建前端...")) {
    return 1;
  }

  if (!existsSync(distIndex)) {
    console.error("  ✗ 构建结束但 dist/index.html 仍不存在");
    return 1;
  }

  console.log("        前端构建完成");
  return 0;
}

process.exit(main());
