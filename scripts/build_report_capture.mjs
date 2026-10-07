// Copy the pinned capture library and its license for offline editor loading.
import { readFile, writeFile } from 'node:fs/promises';
for (const [source, target] of [
  ['dist/html2canvas.min.js', 'html2canvas.min.js'],
  ['LICENSE', 'html2canvas_LICENSE.txt'],
]) {
  const content = await readFile(new URL('../node_modules/html2canvas/' + source, import.meta.url));
  const destination = new URL('../docassemble/ALWeaver/data/static/' + target, import.meta.url);
  if (process.argv.includes('--check')) {
    if (!(await readFile(destination)).equals(content)) throw new Error('Run npm run build:report-capture');
  } else await writeFile(destination, content);
}
