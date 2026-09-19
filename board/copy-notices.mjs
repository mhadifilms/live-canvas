import {
  readdirSync,
  readFileSync,
  existsSync,
  mkdirSync,
  copyFileSync,
} from "node:fs";
import { join } from "node:path";
export function copyNotices(out) {
  const dest = join(out, "licenses");
  mkdirSync(dest, { recursive: true });
  function packages(dir) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (!entry.isDirectory() || entry.name.startsWith(".")) continue;
      const path = join(dir, entry.name);
      if (entry.name.startsWith("@")) {
        packages(path);
        continue;
      }
      const manifest = join(path, "package.json");
      if (!existsSync(manifest)) continue;
      const p = JSON.parse(readFileSync(manifest, "utf8"));
      // macOS-only development watcher; it is not part of the browser bundle.
      if (p.name === "fsevents") continue;
      const target = join(dest, p.name.replaceAll("/", "__") + "-" + p.version);
      for (const file of readdirSync(path)) {
        if (
          /^(license|licence|notice|copying)(\..*)?$/i.test(file) &&
          !file.includes("/")
        ) {
          mkdirSync(target, { recursive: true });
          try {
            copyFileSync(join(path, file), join(target, file));
          } catch {}
        }
      }
      if (existsSync(join(path, "node_modules")))
        packages(join(path, "node_modules"));
    }
  }
  packages("node_modules");
}
