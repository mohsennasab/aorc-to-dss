import { readFile, readdir, stat, mkdir, writeFile } from "node:fs/promises"
import { resolve, relative, sep } from "node:path"
import { zipSync } from "fflate"

const root = resolve(import.meta.dirname, "..")
const pluginRoot = resolve(root, "geolibre-plugin")
const releaseRoot = resolve(root, "release")
const manifest = JSON.parse(await readFile(resolve(pluginRoot, "plugin.json"), "utf8"))
const files = {}

async function collect(directory) {
  for (const entry of await readdir(directory)) {
    const absolute = resolve(directory, entry)
    const info = await stat(absolute)
    if (info.isDirectory()) {
      await collect(absolute)
      continue
    }
    const archivePath = relative(pluginRoot, absolute).split(sep).join("/")
    if (/private|memory|handoff|\.md$/i.test(archivePath)) {
      throw new Error(`Refusing to package private or working file: ${archivePath}`)
    }
    files[archivePath] = new Uint8Array(await readFile(absolute))
  }
}

for (const required of [manifest.entry, manifest.style]) {
  if (!required) continue
  await stat(resolve(pluginRoot, required))
}

await collect(pluginRoot)
await mkdir(releaseRoot, { recursive: true })
const output = resolve(releaseRoot, `AORCtoDSS-plugin-${manifest.version}.zip`)
await writeFile(output, zipSync(files, { level: 9 }))
console.log(`Packaged ${Object.keys(files).length} files to ${output}`)
