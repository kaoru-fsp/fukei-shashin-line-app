import { initializeApp } from 'firebase/app';
import { getFirestore, doc, setDoc } from 'firebase/firestore';
import fs from 'fs';

const config = JSON.parse(fs.readFileSync('./firebase-applet-config.json', 'utf8'));

const app = initializeApp(config);
const db = getFirestore(app, config.firestoreDatabaseId);

const images = [
  {
    url: 'https://drive.google.com/file/d/11hO581a9_0fyKXA7ZF9m41ASnXC5_8QM/view?usp=drive_link',
    caption: '『風景写真』2026年5-6月号巻頭ギャラリー\n林惣一「こころ葉」より'
  },
  {
    url: 'https://drive.google.com/file/d/1HhI0C2lKh9Vbio3iIGBojlzMmt1JJm_N/view?usp=drive_link',
    caption: '『風景写真』2026年5-6月号巻頭ギャラリー\n林惣一「こころ葉」より'
  },
  {
    url: 'https://drive.google.com/file/d/1sg9kmAVN3IRejfRM2i_LvmPbq0BfmhFy/view?usp=drive_link',
    caption: '『風景写真』2026年5-6月号特集ギャラリー\n「心ゆくまで夏楽園」より・佐藤尚（ツツジ）'
  },
  {
    url: 'https://drive.google.com/file/d/15G4n112_3spjxi7BW7UZ9c8fYGn-fQfI/view?usp=drive_link',
    caption: '『風景写真』2026年5-6月号特集ギャラリー\n「心ゆくまで夏楽園」より・萩原れい子（ニッコウキスゲ）'
  },
  {
    url: 'https://drive.google.com/file/d/1YXSEu5lBYg8eAoRtewyD05XoraVewIKt/view?usp=drive_link',
    caption: '『風景写真』2026年5-6月号特集ギャラリー\n「心ゆくまで夏楽園」より・喜多規子（ヤマボウシ）'
  }
];

async function run() {
  await setDoc(doc(db, "settings", "slideshow"), { 
    images: images, 
    updatedAt: new Date()
  });
  console.log("Success updating slideshow");
  process.exit();
}
run();
