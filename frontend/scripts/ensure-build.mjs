#!/usr/bin/env node
/**
 * 确保前端构建产物是最新的。
 *
 * 背景：frontend/dist 不再纳入版本控制（每次构建文件名带 hash，提交它只会产生
 * 大量无意义 diff）。但 start.bat / start.sh 依赖 dist 存在才能提供界面 ——
 * 因此启动脚本必须能自己把前端建出来，否则新克隆的仓库打开只有 404。
 *
 * 逻辑：
 *   - dist/index.html 不存在 → 构建
 *   - node_modules 不存在   → 先 npm install 再构建
 *   - src/ 下有文件比 dist/index.html 新 → 重新构建
 *   - 否则跳过（避免每次启动都等一次构建）
 *
 * 退出码：0 = 可用；1 = 构建失败（调用方应中止启动）
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

/** 递归取目录下最新文件的 mtime，用于判断源码是否比构建产物新 */
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
          /* 读取失败的文件忽略即可，不影响构建判断 */
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
    // 配置文件改动同样应触发重建
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
