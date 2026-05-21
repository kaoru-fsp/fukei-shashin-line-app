import fs from 'fs';

function applyViewBox(files, viewBox) {
  for (const file of files) {
    if (fs.existsSync(file)) {
      let content = fs.readFileSync(file, 'utf8');
      content = content.replace(/viewBox="0 0 1920 1080"/g, `viewBox="${viewBox}"`);
      fs.writeFileSync(file, content);
      console.log(`Updated ${file} with viewBox="${viewBox}"`);
    }
  }
}

applyViewBox([
  'src/assets/logo_fukeishashin-tree.svg',
  'src/assets/logo_fukeishashin.svg',
  'src/assets/logo_publishing.svg'
], "560 490 535 145"); // Landscape width ~525, height ~140

applyViewBox([
  'src/assets/logo_tree.svg',
  'src/assets/logo_kaze.svg'
], "588 500 50 90"); // Icon width ~44, height ~86
